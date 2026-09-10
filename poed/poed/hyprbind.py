"""Consume the price-check hotkey only while the game window exists.

A static Hyprland `bind` would swallow Ctrl+D system-wide (terminal EOF, ...).
Instead poed adds the bind when the PoE2 window appears and removes it when the
window closes or poed exits. Window presence comes from Hyprland's socket2
event stream.

Bind transport depends on the config provider: on hyprlang systems binds are
added via `hyprctl keyword bind ...`; on Lua-config systems (Hyprland >= 0.55,
e.g. omarchy) `hyprctl keyword` silently no-ops, so poed uses
`hyprctl eval 'hl.bind(...)'`. Detection is by `~/.config/hypr/hyprland.lua`.
"""
import json
import logging
import os
import socket
import subprocess

_LOG = logging.getLogger("waystone.hyprbind")

_PROVIDER: str | None = None
_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "hypr")


def _detect_provider(config_dir: str) -> str:
    """'lua' when the Hyprland config uses the Lua provider, else 'hyprlang'."""
    if os.path.isfile(os.path.join(config_dir, "hyprland.lua")):
        return "lua"
    return "hyprlang"


def _config_provider() -> str:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = _detect_provider(_CONFIG_DIR)
    return _PROVIDER


def _lua_keys(mods: str, key: str) -> str:
    """Hyprland Lua key spec: mods joined with ' + ', e.g. 'ALT + Z'."""
    parts = [p for p in mods.split("_") if p] if mods else []
    parts.append(key)
    return " + ".join(parts)


def _bind_cmd(name: str, mods: str, key: str) -> tuple[str, ...]:
    if _config_provider() == "lua":
        return ("eval", f'hl.bind("{_lua_keys(mods, key)}", hl.dsp.global("{name}"))')
    return ("keyword", "bind", f"{mods},{key},global,{name}")


def _unbind_cmd(mods: str, key: str) -> tuple[str, ...]:
    if _config_provider() == "lua":
        return ("eval", f'hl.unbind("{_lua_keys(mods, key)}")')
    return ("keyword", "unbind", f"{mods},{key}")


def _esc_bind_cmd(name: str) -> tuple[str, ...]:
    if _config_provider() == "lua":
        return ("eval", f'hl.bind("Escape", hl.dsp.global("{name}"))')
    return ("keyword", "bind", f",Escape,global,{name}")


def _esc_unbind_cmd() -> tuple[str, ...]:
    if _config_provider() == "lua":
        return ("eval", 'hl.unbind("Escape")')
    return ("keyword", "unbind", ",Escape")


def _norm(addr: str) -> str:
    """Normalize a Hyprland window address to bare hex (no 0x prefix, no whitespace).

    hyprctl clients -j returns addresses as "0x560e297adf80"; socket2
    openwindow events may also carry the prefix, while closewindow always uses
    bare hex.  Storing and comparing the bare form everywhere avoids mismatches.
    """
    return addr.strip().removeprefix("0x")


def _hyprctl(*args: str) -> bool:
    """Run `hyprctl <args>`, True on success.

    `eval` reports success by printing 'ok'; on any other output (error text)
    treat it as failure — a bad Lua expression must never look like success.
    """
    try:
        r = subprocess.run(["hyprctl", *args], capture_output=True, timeout=2.0)
        if r.returncode != 0:
            return False
        if args and args[0] == "eval":
            return b"ok" in r.stdout
        return True
    except (OSError, subprocess.SubprocessError):
        return False  # compositor gone; nothing sensible to do


def resolve_shortcut_name(shortcut_id: str, _raw: str | None = None) -> str | None:
    """Full 'appid:shortcut' name as the portal actually registered it.

    xdph derives the appid from the caller's systemd scope (terminal launch ->
    'xdg-terminal-exec', etc.), ignoring our DBus app_id — so the bind arg
    must be queried, never assumed.

    `_raw` is injectable for tests; production runs `hyprctl globalshortcuts -j`
    (2s timeout, any failure -> None). Returns the registered `name` whose
    suffix after the colon equals `shortcut_id`, else None.
    """
    if _raw is None:
        try:
            _raw = subprocess.run(
                ["hyprctl", "globalshortcuts", "-j"],
                capture_output=True, text=True, timeout=2.0,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
    try:
        entries = json.loads(_raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str) and name.rsplit(":", 1)[-1] == shortcut_id:
            return name
    return None


class BindManager:
    def __init__(self, game_class: str, mods: str, key: str, shortcut_id: str,
                 _ctl=_hyprctl, _resolve=resolve_shortcut_name):
        self._game_class = game_class
        self._mods = mods
        self._key = key
        self._shortcut_id = shortcut_id
        self._bind_desc = f"{mods},{key}"
        self._ctl = _ctl
        self._resolve = _resolve
        self._resolved_name: str | None = None
        self._game_windows: set[str] = set()
        self._bound = False

    # -- socket2 line protocol: "event>>data" ------------------------------

    def handle_line(self, line: str) -> None:
        event, _, data = line.partition(">>")
        if event == "openwindow":
            # data: ADDR,WORKSPACE,CLASS,TITLE (title may contain commas)
            parts = data.split(",", 3)
            if len(parts) >= 3:
                addr, _, klass = parts[0], parts[1], parts[2]
                if klass == self._game_class:
                    addr = _norm(addr)
                    if addr not in self._game_windows:
                        _LOG.info("%s: game window opened (%s)", self._shortcut_id, addr)
                    self._game_windows.add(addr)
                    self._sync()
        elif event == "closewindow":
            addr = _norm(data)
            if addr in self._game_windows:
                _LOG.info("%s: game window closed (%s)", self._shortcut_id, addr)
                self._game_windows.discard(addr)
                self._sync()

    def _sync(self) -> None:
        want = bool(self._game_windows)
        if want and not self._bound:
            if self._resolved_name is None:
                # Resolve lazily; the portal may not have registered yet.
                self._resolved_name = self._resolve(self._shortcut_id)
                if self._resolved_name is None:
                    _LOG.warning(
                        "%s: game window present but portal shortcut not "
                        "resolvable yet; retrying on next event/registration",
                        self._shortcut_id,
                    )
                    return  # defer: next _sync (or notify_registered) retries
            bind_args = _bind_cmd(self._resolved_name, self._mods, self._key)
            ok = self._ctl(*bind_args)
            if ok:
                self._bound = True
                _LOG.info(
                    "%s: bound %s,%s -> global:%s",
                    self._shortcut_id, self._mods, self._key, self._resolved_name,
                )
            else:
                _LOG.warning(
                    "%s: bind %s,%s failed (hyprctl returned non-zero)",
                    self._shortcut_id, self._mods, self._key,
                )
        elif not want and self._bound:
            unbind_args = _unbind_cmd(self._mods, self._key)
            ok = self._ctl(*unbind_args)
            if ok:
                self._bound = False
                _LOG.info("%s: unbound %s", self._shortcut_id, self._bind_desc)
            else:
                _LOG.warning(
                    "%s: unbind %s failed; still bound",
                    self._shortcut_id, self._bind_desc,
                )

    def notify_registered(self) -> None:
        """Portal BindShortcuts completed; retry a deferred bind if needed."""
        _LOG.info("%s: portal registered; re-checking bind", self._shortcut_id)
        self._sync()

    # -- lifecycle ----------------------------------------------------------

    def prime(self) -> None:
        """Bind immediately if the game is already running at poed startup."""
        try:
            out = subprocess.run(
                ["hyprctl", "clients", "-j"],
                capture_output=True, text=True, timeout=2.0,
            ).stdout
            for c in json.loads(out):
                if c.get("class") == self._game_class:
                    self._game_windows.add(_norm(c.get("address", "?")))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        if self._game_windows:
            _LOG.info(
                "%s: game window(s) already present at startup: %s",
                self._shortcut_id, ", ".join(sorted(self._game_windows)),
            )
        self._sync()

    def stop(self) -> None:
        if self._bound:
            ok = self._ctl(*_unbind_cmd(self._mods, self._key))
            if ok:
                self._bound = False
            _LOG.info("%s: stopped, unbound %s", self._shortcut_id, self._bind_desc)

    def socket_path(self) -> str:
        runtime = os.environ["XDG_RUNTIME_DIR"]
        sig = os.environ["HYPRLAND_INSTANCE_SIGNATURE"]
        return f"{runtime}/hypr/{sig}/.socket2.sock"

    def connect_events(self) -> socket.socket:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self.socket_path())
        s.setblocking(False)
        return s


class MultiBindManager:
    """Fan one socket2 event stream out to several BindManagers (one per
    hotkey). Window tracking stays per-manager; the socket is shared."""

    def __init__(self, managers: list[BindManager]):
        self._managers = managers

    @classmethod
    def create(cls, game_class: str, binds: list[tuple[str, str, str]],
               _ctl=_hyprctl, _resolve=resolve_shortcut_name) -> "MultiBindManager":
        return cls([
            BindManager(game_class, mods, key, sid, _ctl=_ctl, _resolve=_resolve)
            for mods, key, sid in binds
        ])

    def handle_line(self, line: str) -> None:
        for m in self._managers:
            m.handle_line(line)

    def notify_registered(self) -> None:
        for m in self._managers:
            m.notify_registered()

    def prime(self) -> None:
        for m in self._managers:
            m.prime()

    def stop(self) -> None:
        for m in self._managers:
            m.stop()

    def socket_path(self) -> str:
        return self._managers[0].socket_path()

    def connect_events(self) -> socket.socket:
        return self._managers[0].connect_events()


class EscBind:
    """Consume Esc ONLY while the overlay panel is visible.

    A static Esc bind would swallow Esc system-wide (the game loses Esc); bind
    on show, unbind on hide/exit. Resolution of the portal-registered shortcut
    name is lazy and cached (same xdph appid quirk as BindManager).
    """

    def __init__(self, shortcut_id: str, _ctl=_hyprctl, _resolve=resolve_shortcut_name):
        self._shortcut_id = shortcut_id
        self._ctl = _ctl
        self._resolve = _resolve
        self._resolved_name: str | None = None
        self._bound = False

    def show(self) -> None:
        if self._bound:
            return
        if self._resolved_name is None:
            self._resolved_name = self._resolve(self._shortcut_id)
            if self._resolved_name is None:
                _LOG.warning(
                    "esc: portal shortcut '%s' not resolvable yet; "
                    "retrying on next show", self._shortcut_id,
                )
                return  # defer silently: next show() retries
        bind_args = _esc_bind_cmd(self._resolved_name)
        if self._ctl(*bind_args):
            self._bound = True
            _LOG.info("esc: bound -> global:%s", self._resolved_name)
        else:
            _LOG.warning("esc: bind failed (hyprctl returned non-zero)")

    def hide(self) -> None:
        if not self._bound:
            return
        if self._ctl(*_esc_unbind_cmd()):
            self._bound = False
            _LOG.info("esc: unbound")
        else:
            _LOG.warning("esc: unbind failed; still bound")

    stop = hide
