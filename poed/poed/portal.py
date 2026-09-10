"""xdg-desktop-portal GlobalShortcuts session.

Productionized from spikes/spike_portal.py. The spike proved the full
CreateSession -> BindShortcuts flow works under xdg-desktop-portal-hyprland
(xdph) 1.3.12 and returns response code 0, with no approval dialog. See that
file's ## Findings block for the de-risking detail; this module just ports the
proven DBus sequence.

Design: session creation is asynchronous (the portal replies via a Request ->
Response signal, not the method return value). bind() therefore does not block:
it kicks off CreateSession, stashes the requested shortcuts, and binds them from
the CreateSession Response callback once the session_handle exists. This is the
simplest correct shape for a GLib main-loop program -- everything is driven by
signal callbacks on the loop the caller is already running. bind() may be called
before the loop starts; the work runs as soon as the loop dispatches.

Pitfalls applied (from spike Findings):
  - sys.exit in callbacks: NEVER called here. GLib's dispatcher swallows
    SystemExit; failures are logged and the on_error hook is invoked instead.
  - subscription-id cell: each call_with_request captures its subscription id in
    a per-call local (not a shared mutable cell), so a late Response can't
    unsubscribe the wrong handler.
  - token charset: tokens are derived from uuid4 with dashes -> underscores so
    they match the portal's required [a-zA-Z0-9_]+.
  - ListShortcuts unreliable: we do NOT call ListShortcuts and do NOT gate on
    it. BindShortcuts Response code=0 is the source of truth.
  - trigger_description empty / preferred_trigger advisory: we pass
    preferred_trigger but do not depend on it being honoured; the trigger is
    bound by the compositor/user and we just listen for Activated.
  - signal callbacks take 7 positional args (incl. trailing user_data).
"""

import logging
import uuid

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
GS_IFACE = "org.freedesktop.portal.GlobalShortcuts"
REQUEST_IFACE = "org.freedesktop.portal.Request"


def _token() -> str:
    """A fresh handle token matching the portal's [a-zA-Z0-9_]+ requirement."""
    return "poed_" + uuid.uuid4().hex


def _log(step: str, msg: str) -> None:
    logging.getLogger("waystone.portal").info("[%s] %s", step, msg)


class GlobalShortcuts:
    """xdg-desktop-portal GlobalShortcuts session.

    on_activated(shortcut_id) is invoked when a bound shortcut fires.
    on_error(message) (optional) is invoked if session creation or binding
    fails; callbacks never call sys.exit (GLib swallows it).
    """

    def __init__(self, app_id: str, on_activated, on_error=None, on_bound=None):
        self.app_id = app_id
        self.on_activated = on_activated
        self.on_error = on_error
        self._on_bound = on_bound
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        unique = self.bus.get_unique_name()
        # Sender fragment of the predicted Request path: ":1.42" -> "1_42".
        self.sender = unique.lstrip(":").replace(".", "_")
        self.session_handle = None
        self._pending_shortcuts = None
        _log("bus", f"connected, unique={unique}, sender={self.sender}")
        self._subscribe_activated()

    # --- public API -------------------------------------------------------

    def bind(self, shortcuts):
        """Bind shortcuts. shortcuts: list[(id, description, preferred_trigger)].

        e.g. [("price-check", "PoE2 price check", "SHIFT+space")]

        Non-blocking: kicks off async CreateSession; the actual BindShortcuts
        happens from the CreateSession Response callback. Run a GLib.MainLoop
        for the callbacks to fire.

        Not re-entry safe — call once per instance.
        """
        self._pending_shortcuts = list(shortcuts)
        self._create_session()

    # --- Request/Response plumbing ----------------------------------------

    def _request_path_for(self, token: str) -> str:
        return f"{PORTAL_PATH}/request/{self.sender}/{token}"

    def _call_with_request(self, method, params, token, on_response):
        """Invoke a GlobalShortcuts method that follows the Request pattern.

        Subscribes to the predicted Request path BEFORE calling so an immediate
        Response can't be missed; verifies the returned path and re-subscribes
        defensively if it differs. on_response(code, results) fires on Response.
        """
        expected = self._request_path_for(token)

        # Per-call subscription id, captured in a closure local (NOT a shared
        # mutable cell) so a late Response unsubscribes only its own handler.
        sub_holder = {}

        def on_signal(conn, sender, path, iface, sig, params_variant, user_data):
            try:
                code, results = params_variant.unpack()
            except (ValueError, TypeError) as e:
                # Malformed Response: GLib would swallow a raise here and the
                # request would hang with a live subscription. Treat it as a
                # failure response so the caller can proceed/log.
                _log(method, f"malformed Response on {path}: {e!r}")
                code, results = 1, {}
            _log(method, f"Response code={code} results={results}")
            sid = sub_holder.get("id")
            if sid is not None:
                conn.signal_unsubscribe(sid)
            on_response(code, results)

        sub_holder["id"] = self.bus.signal_subscribe(
            PORTAL_BUS, REQUEST_IFACE, "Response", expected, None,
            Gio.DBusSignalFlags.NONE, on_signal, None,
        )

        ret = self.bus.call_sync(
            PORTAL_BUS, PORTAL_PATH, GS_IFACE, method, params,
            GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, -1, None,
        )
        returned_path = ret.unpack()[0]
        if returned_path != expected:
            _log(method, f"path differs; resubscribing on {returned_path}")
            old = sub_holder.get("id")
            if old is not None:
                self.bus.signal_unsubscribe(old)
            sub_holder["id"] = self.bus.signal_subscribe(
                PORTAL_BUS, REQUEST_IFACE, "Response", returned_path, None,
                Gio.DBusSignalFlags.NONE, on_signal, None,
            )

    # --- steps ------------------------------------------------------------

    def _create_session(self):
        _log("CreateSession", "starting")
        token = _token()
        options = {
            "handle_token": GLib.Variant("s", token),
            "session_handle_token": GLib.Variant("s", _token()),
            "app_id": GLib.Variant("s", self.app_id),
        }
        params = GLib.Variant("(a{sv})", (options,))
        self._call_with_request(
            "CreateSession", params, token, self._on_session_created
        )

    def _on_session_created(self, code, results):
        if code != 0:
            self._fail(f"CreateSession failed (code={code})")
            return
        self.session_handle = results.get("session_handle")
        _log("CreateSession", f"OK session_handle={self.session_handle}")
        self._bind_shortcuts()

    def _bind_shortcuts(self):
        _log("BindShortcuts", "starting")
        shortcuts = []
        for sid, description, preferred_trigger in self._pending_shortcuts:
            meta = {
                "description": GLib.Variant("s", description),
                "preferred_trigger": GLib.Variant("s", preferred_trigger),
            }
            shortcuts.append((sid, meta))
        token = _token()
        options = {"handle_token": GLib.Variant("s", token)}
        params = GLib.Variant(
            "(oa(sa{sv})sa{sv})",
            (self.session_handle, shortcuts, "", options),
        )
        self._call_with_request(
            "BindShortcuts", params, token, self._on_shortcuts_bound
        )

    def _on_shortcuts_bound(self, code, results):
        # code=0 is the source of truth (ListShortcuts is unreliable on xdph).
        if code != 0:
            self._fail(f"BindShortcuts failed (code={code})")
            return
        _log("BindShortcuts", f"OK bound={results.get('shortcuts')}")
        if self._on_bound:
            self._on_bound()

    # --- Activated signal -------------------------------------------------

    def _subscribe_activated(self):
        def on_activated(conn, sender, path, iface, sig, params_variant, ud):
            data = params_variant.unpack()
            # (session_handle, shortcut_id, timestamp, options)
            # Guard: ignore signals for other apps' sessions or signals that
            # arrive before our session is ready (session_handle still None).
            if self.session_handle is None or data[0] != self.session_handle:
                return
            shortcut_id = data[1] if len(data) > 1 else None
            _log("Activated", f"shortcut={shortcut_id}")
            if shortcut_id is not None:
                self.on_activated(shortcut_id)

        self.bus.signal_subscribe(
            PORTAL_BUS, GS_IFACE, "Activated", PORTAL_PATH, None,
            Gio.DBusSignalFlags.NONE, on_activated, None,
        )
        _log("Activated", "subscribed")

    # --- error handling ---------------------------------------------------

    def _fail(self, message: str):
        # Never sys.exit here: GLib swallows SystemExit. Log + hand off.
        _log("error", message)
        if self.on_error is not None:
            self.on_error(message)
