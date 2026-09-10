"""Standalone layer-shell login/status mini-widget (mockup B).

Anchored TOP+LEFT, offset ~35% of the primary monitor width. Click-only:
the Login button is the sole trigger for cookie detection; the panel never
auto-detects at startup. Shows ○ anonymous / ● <account name> and a single
button that swaps Login/Logout per state, plus a transient status line.

All text is set via Gtk.Label.set_text (no markup) — the account name is a
remote value, and set_text needs no escaping.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gdk, Gtk4LayerShell as LayerShell  # noqa: E402

from . import draggable

_LOG = logging.getLogger("waystone.login")


def _default_pos(mon_w: int) -> tuple[int, int]:
    return (int(mon_w * 0.35), 0)


class LoginBox:
    def __init__(self, app: Gtk.Application, on_login, on_logout, positions=None,
                 game_class: str = ""):
        self._on_login = on_login
        self._on_logout = on_logout
        self._mode = "anonymous"  # "anonymous" | "logged_in" (button label source)
        self._positions = positions
        self._game_class = game_class

        self._win = Gtk.Window(application=app)
        LayerShell.init_for_window(self._win)
        LayerShell.set_layer(self._win, LayerShell.Layer.OVERLAY)
        # Pointer-only widget — never grab the keyboard from the game.
        LayerShell.set_keyboard_mode(self._win, LayerShell.KeyboardMode.NONE)

        mon_w, _mon_h = draggable.monitor_geometry()
        # Saved position wins; first run falls back to ~35% across the monitor.
        saved = positions.get("login") if positions is not None else None
        self._pos = saved if saved is not None else _default_pos(mon_w)
        # Follow the game like the panel (margins are relative to the attached
        # monitor's origin); set_visible re-attaches on every show.
        target = draggable.game_window_monitor(self._game_class)
        gdkm = draggable.attach_monitor(self._win, target.get("name") if target else None)
        if gdkm is not None:
            geo = gdkm.get_geometry()
            self._pos = draggable.position_on_monitor(saved, geo.width, geo.height, _default_pos)
        draggable.anchor_top_left(self._win, *self._pos)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("poe-panel")
        box.append(draggable.make_drag_handle(self._win, self._get_pos, self._save_pos))

        line = Gtk.Box(spacing=8)
        self._dot = Gtk.Label()
        self._dot.set_text("○")
        self._name = Gtk.Label(xalign=0.0)
        self._name.set_text("anonymous")
        self._name.set_hexpand(True)
        self._btn = Gtk.Button(label="Login")
        self._btn.add_css_class("poe-btn")
        self._btn.connect("clicked", self._on_click)
        line.append(self._dot)
        line.append(self._name)
        line.append(self._btn)
        box.append(line)

        self._status = Gtk.Label(xalign=0.0)
        self._status.add_css_class("poe-dim")
        self._status.set_text("")
        box.append(self._status)

        self._win.set_child(box)

    def _on_click(self, _btn):
        _LOG.info("button clicked")
        if self._mode == "logged_in":
            self._on_logout()
        else:
            # Visibly react before on_login runs — detection can fail fast and
            # would otherwise leave the button looking dead.
            self.set_busy()
            self._on_login()

    # -- drag-to-move ------------------------------------------------------

    def _get_pos(self):
        return self._pos

    def _save_pos(self, x: int, y: int) -> None:
        w, h = self._win.get_width(), self._win.get_height()
        if w > 0 and h > 0:
            mon_w, mon_h = draggable.monitor_geometry()
            x, y = draggable.clamp_position(x, y, mon_w, mon_h, w, h)
        self._pos = (int(x), int(y))
        if self._positions is not None:
            self._positions.set("login", *self._pos)
        draggable.set_position(self._win, *self._pos)

    # -- public API (GLib main thread only) --------------------------------

    def set_visible(self, visible: bool) -> None:
        if visible:
            target = draggable.game_window_monitor(self._game_class)
            gdkm = draggable.attach_monitor(self._win, target.get("name") if target else None)
            if gdkm is not None:
                geo = gdkm.get_geometry()
                self._pos = draggable.position_on_monitor(
                    self._pos, geo.width, geo.height, _default_pos
                )
            self._win.present()
            draggable.set_position(self._win, *self._pos)
        else:
            self._win.set_visible(False)

    def set_anonymous(self) -> None:
        self._mode = "anonymous"
        self._dot.set_text("○")
        self._name.set_text("anonymous")
        self._btn.set_label("Login")
        self._status.set_text("")

    def set_busy(self) -> None:
        self._dot.set_text("○")
        self._name.set_text("checking…")
        self._status.set_text("")

    def set_logged_in(self, name: str) -> None:
        _LOG.info("verified")
        self._mode = "logged_in"
        self._dot.set_text("●")
        self._name.set_text(name or "logged in")
        self._btn.set_label("Logout")
        self._status.set_text("")

    def set_status(self, message: str) -> None:
        _LOG.info("status — %s", message)
        # Detection failed/finished without logging in: reset the dot + button
        # out of the busy state so the user can read the message and retry.
        self._mode = "anonymous"
        self._dot.set_text("○")
        self._name.set_text("anonymous")
        self._btn.set_label("Login")
        self._status.set_text(message)
