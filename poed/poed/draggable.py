"""Drag-to-move for layer-shell surfaces.

Layer-shell windows have no compositor titlebar; we anchor a surface to
TOP+LEFT and treat its TOP/LEFT margins as (y, x). A grab-handle strip with a
Gtk.GestureDrag drives those margins live, then reports the final position so
callers can persist it.

Crucially, the drag position comes from the COMPOSITOR's absolute cursor
(`hyprctl cursorpos`), not the panel's own coordinate frame. Reading the
surface frame (GestureDrag offset OR get_point) is cursed: set_margin is async,
so the surface frame lags the actual commit, and any position formula with a
surface-frame term feeds that lag back in — halving speed (offset) or jumping
at speed (get_point). hyprctl cursorpos is frame-INDEPENDENT (global layout
coords, unaffected by our pending margin commits), so
    margin = cursor_global - output_origin - grab_local
has no surface term and therefore no feedback.
"""
import json
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gdk, GLib, Gtk4LayerShell as LayerShell  # noqa: E402


def monitor_geometry() -> tuple[int, int]:
    """Union extent (width, height) across all monitors in px.

    Returns the far edge of the multi-monitor layout — max(geo.x + geo.width)
    and max(geo.y + geo.height) — not a single monitor. Returning only the
    first monitor walls off any wider/taller sibling screen during clamp (the
    game runs on the 3440-wide DP-3, not the 2560 first monitor). Any failure
    falls back to 1920x1080.
    """
    try:
        monitors = Gdk.Display.get_default().get_monitors()
        max_w, max_h = 0, 0
        for i in range(monitors.get_n_items()):
            mon = monitors.get_item(i)
            if mon is None:
                continue
            geo = mon.get_geometry()
            max_w = max(max_w, geo.x + geo.width)
            max_h = max(max_h, geo.y + geo.height)
        if max_w > 0 and max_h > 0:
            return max_w, max_h
    except Exception:
        pass
    return (1920, 1080)


def _parse_cursorpos(raw: str) -> tuple[int, int] | None:
    """Parse `hyprctl cursorpos` output ("x, y", e.g. "2314, 880"); None on garbage."""
    parts = raw.strip().split(",")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return None


def cursor_pos() -> tuple[int, int] | None:
    """Compositor's absolute cursor in global layout coords, or None on failure."""
    try:
        out = subprocess.run(
            ["hyprctl", "cursorpos"],
            capture_output=True,
            text=True,
            timeout=0.5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _parse_cursorpos(out.stdout)


def monitor_origin_at(gx: int, gy: int) -> tuple[int, int]:
    """Top-left (x, y) of the monitor whose rect contains global point (gx, gy).

    Fallback (0, 0) on failure or no containing monitor.
    """
    try:
        out = subprocess.run(
            ["hyprctl", "monitors", "-j"],
            capture_output=True,
            text=True,
            timeout=0.5,
        )
        for mon in json.loads(out.stdout):
            mx, my = mon["x"], mon["y"]
            if mx <= gx < mx + mon["width"] and my <= gy < my + mon["height"]:
                return mx, my
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        pass
    return (0, 0)


def _monitors_json(raw: str) -> list[dict]:
    """Parse `hyprctl monitors -j` into {id,x,y,width,height,name} dicts; []
    on garbage."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [
        {
            "id": m.get("id"), "x": m.get("x"), "y": m.get("y"),
            "width": m.get("width"), "height": m.get("height"),
            "name": m.get("name"),
        }
        for m in data if isinstance(m, dict)
    ]


def _monitor_by_id(mons: list[dict], mid) -> dict | None:
    """Monitor dict whose id == mid from a _monitors_json list; None when absent."""
    if mid is None:
        return None
    for m in mons:
        if m.get("id") == mid:
            return m
    return None


def _game_window_mid(raw_active: str, raw_clients: str, game_class: str) -> int | None:
    """Monitor id of a game window from raw hyprctl json.

    Prefers the focused window when its class matches the game (price-check
    demands game focus anyway), else the first matching game client (unique-
    scan screenshots without focus). None when nothing matches.
    """
    try:
        active = json.loads(raw_active)
    except (ValueError, TypeError):
        active = None
    if isinstance(active, dict) and active.get("class") == game_class:
        mid = active.get("monitor")
        if mid is not None:
            return mid
    try:
        clients = json.loads(raw_clients)
    except (ValueError, TypeError):
        clients = None
    if isinstance(clients, list):
        for c in clients:
            if isinstance(c, dict) and c.get("class") == game_class:
                return c.get("monitor")
    return None


def game_window_monitor(game_class: str) -> dict | None:
    """Compositor monitor {name,x,y,width,height} showing a game window.

    The overlay chases this monitor so the panel renders on the same screen as
    the game instead of gtk-layer-shell's default one. None on any failure,
    letting callers keep their previous (union/default) placement.
    """
    try:
        raw_active = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True, text=True, timeout=0.5,
        ).stdout
        raw_clients = subprocess.run(
            ["hyprctl", "clients", "-j"],
            capture_output=True, text=True, timeout=0.5,
        ).stdout
        raw_mons = subprocess.run(
            ["hyprctl", "monitors", "-j"],
            capture_output=True, text=True, timeout=0.5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    mid = _game_window_mid(raw_active, raw_clients, game_class)
    if mid is None:
        return None
    return _monitor_by_id(_monitors_json(raw_mons), mid)


def gdk_monitor_by_name(name: str) -> Gdk.Monitor | None:
    """Gdk monitor whose connector matches `name` (a Hyprland monitor name);
    None when headless (tests) or the name isn't on this display."""
    display = Gdk.Display.get_default()
    if display is None:
        return None
    mons = display.get_monitors()
    for i in range(mons.get_n_items()):
        mon = mons.get_item(i)
        if mon is None:
            continue
        if mon.get_connector() == name:
            return mon
    return None


def attach_monitor(win, name: str | None) -> Gdk.Monitor | None:
    """Attach `win` to the monitor named `name`; returns its Gdk.Monitor or None.

    None means the name is unknown to the running display (or headless) and the
    surface stays on gtk-layer-shell's default monitor. The returned monitor
    lets callers read its geometry for margin placement.
    """
    if not name:
        return None
    mon = gdk_monitor_by_name(name)
    if mon is not None:
        LayerShell.set_monitor(win, mon)
    return mon


def position_on_monitor(saved, mon_w, mon_h, fallback) -> tuple[int, int]:
    """Margins for a surface on a monitor of (mon_w, mon_h).

    `saved` margins win when they fit inside the monitor — layer-shell margins
    are relative to the ATTACHED monitor's origin, so the same numbers mean the
    same spot on every monitor. A monitor switch must never leave the surface
    parked at stale margins off-screen, so non-fitting saved margins fall back
    to `fallback(mon_w)` (a per-widget default, e.g. centered).
    """
    if saved is not None and 0 <= saved[0] < mon_w and 0 <= saved[1] < mon_h:
        return int(saved[0]), int(saved[1])
    return fallback(int(mon_w))


def clamp_position(x, y, mon_w, mon_h, win_w, win_h):
    """Keep a window fully on-screen; window-larger-than-monitor pins to 0."""
    max_x = max(0, mon_w - win_w)
    max_y = max(0, mon_h - win_h)
    return (max(0, min(int(x), max_x)), max(0, min(int(y), max_y)))


def anchor_top_left(win, x: int, y: int) -> None:
    """Anchor the surface to TOP+LEFT and place it via margins (x=LEFT, y=TOP)."""
    LayerShell.set_anchor(win, LayerShell.Edge.TOP, True)
    LayerShell.set_anchor(win, LayerShell.Edge.LEFT, True)
    LayerShell.set_anchor(win, LayerShell.Edge.BOTTOM, False)
    LayerShell.set_anchor(win, LayerShell.Edge.RIGHT, False)
    set_position(win, x, y)


def set_position(win, x: int, y: int) -> None:
    LayerShell.set_margin(win, LayerShell.Edge.LEFT, int(x))
    LayerShell.set_margin(win, LayerShell.Edge.TOP, int(y))


def make_drag_handle(win, get_xy, on_moved) -> Gtk.Widget:
    """A grab strip; dragging it moves `win` via margins.

    get_xy() -> (x, y) current committed position.
    on_moved(x, y) called on drag-end with the final clamped position.
    """
    handle = Gtk.Box()
    handle.add_css_class("poe-drag")
    handle.set_size_request(-1, 14)
    grip = Gtk.Label(label="⠿⠿⠿")
    grip.add_css_class("poe-dim")
    handle.append(grip)

    drag = Gtk.GestureDrag()
    live = {
        "x": 0, "y": 0, "ox": 0, "oy": 0, "gx": 0.0, "gy": 0.0,
        # Captured once at drag-begin: monitor union + window size are
        # invariant for the duration of a drag, and a hyprctl/GDK walk per
        # motion event is pure overhead.
        "mon": (1920, 1080), "wh": (0, 0),
        # Last cursor poll, GLib monotonic µs — throttles the per-motion
        # `hyprctl cursorpos` subprocess to at most one per 10ms.
        "last_poll": 0,
    }

    def on_begin(_g, sx, sy):
        live["x"], live["y"] = get_xy()      # committed margin (for fallback + final)
        live["gx"], live["gy"] = sx, sy      # grab point in panel-local coords
        live["mon"] = monitor_geometry()
        live["wh"] = (win.get_width(), win.get_height())
        live["last_poll"] = 0
        c = cursor_pos()
        if c is None:
            live["ox"] = None                # no compositor cursor; will fall back
            return
        # output origin = top-left of the monitor the surface sits on (the one
        # under the cursor at grab). margin is relative to that origin.
        live["ox"], live["oy"] = monitor_origin_at(*c)

    def on_update(_g, off_x, off_y):
        now = GLib.get_monotonic_time()
        if now - live["last_poll"] < 10_000:  # µs — cap polls at ~100/s
            return
        live["last_poll"] = now
        if live["ox"] is None:
            # Fallback: no hyprctl cursor — use the (laggy) offset so drag still
            # half-works on non-Hypr compositors.
            nx, ny = live["x"] + off_x, live["y"] + off_y
        else:
            c = cursor_pos()
            if c is None:
                return
            # Absolute frame: panel's top-left should sit at cursor minus where
            # on the panel we grabbed, expressed in the surface's output origin.
            # No surface-frame term -> no feedback through the async margin
            # commits that halved/jumped the offset & get_point approaches.
            nx = c[0] - live["ox"] - live["gx"]
            ny = c[1] - live["oy"] - live["gy"]
        mon_w, mon_h = live["mon"]
        w, h = live["wh"]
        if w > 0 and h > 0:
            nx, ny = clamp_position(nx, ny, mon_w, mon_h, w, h)
        live["x"], live["y"] = int(nx), int(ny)
        set_position(win, live["x"], live["y"])

    def on_end(_g, _ox, _oy):
        on_moved(live["x"], live["y"])

    drag.connect("drag-begin", on_begin)
    drag.connect("drag-update", on_update)
    drag.connect("drag-end", on_end)
    handle.add_controller(drag)
    return handle
