"""Standalone layer-shell league selector (sibling of LoginBox).

TOP+LEFT anchored, drag handle, position persisted under "league".
Pointer-only — never grabs the keyboard from the game.

No Gtk.DropDown: its popover is an xdg_popup needing a keyboard grab, which
a KeyboardMode.NONE layer surface can't back — Hyprland dismisses it on
open (observed as an instant flash). Instead the list expands inline inside
this window: a toggle row, and a ListBox that grows the surface downward.

Starts with just the configured league; set_leagues() swaps in the full
roster once the brain's `leagues` cmd answers. Selection changes call
on_change(league) once per user pick.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gtk4LayerShell as LayerShell  # noqa: E402

from . import draggable

_LOG = logging.getLogger("waystone.league")


def _default_pos(mon_w: int) -> tuple[int, int]:
    return (int(mon_w * 0.25), 0)


class LeagueBox:
    def __init__(self, app: Gtk.Application, current_league: str, on_change,
                 positions=None, game_class: str = ""):
        self._on_change = on_change
        self._positions = positions
        self._names = [current_league]
        self._current = current_league
        self._game_class = game_class

        self._win = Gtk.Window(application=app)
        LayerShell.init_for_window(self._win)
        LayerShell.set_layer(self._win, LayerShell.Layer.OVERLAY)
        LayerShell.set_keyboard_mode(self._win, LayerShell.KeyboardMode.NONE)

        mon_w, _mon_h = draggable.monitor_geometry()
        saved = positions.get("league") if positions is not None else None
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

        self._btn = Gtk.Button()
        self._btn.add_css_class("poe-btn")
        self._btn.connect("clicked", self._on_toggle)
        box.append(self._btn)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.set_visible(False)
        self._list.connect("row-activated", self._on_row)
        box.append(self._list)

        self._win.set_child(box)
        self._refresh()

    # -- drag-to-move (mirrors LoginBox) ------------------------------------

    def _get_pos(self):
        return self._pos

    def _save_pos(self, x: int, y: int) -> None:
        w, h = self._win.get_width(), self._win.get_height()
        if w > 0 and h > 0:
            mon_w, mon_h = draggable.monitor_geometry()
            x, y = draggable.clamp_position(x, y, mon_w, mon_h, w, h)
        self._pos = (int(x), int(y))
        if self._positions is not None:
            self._positions.set("league", *self._pos)
        draggable.set_position(self._win, *self._pos)

    # -- public API (GLib main thread only) ----------------------------------

    def set_leagues(self, names: list[str], current: str) -> None:
        if current not in names:
            names = [current, *names]
        self._names = list(names)
        self._current = current
        self._refresh()

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
            self._collapse()
            self._win.set_visible(False)

    # -- internal -------------------------------------------------------------

    def _refresh(self) -> None:
        self._btn.set_label(f"{self._current}  ▾")
        child = self._list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._list.remove(child)
            child = nxt
        for name in self._names:
            label = Gtk.Label(xalign=0.0)
            label.set_text(("● " if name == self._current else "  ") + name)
            row = Gtk.ListBoxRow()
            row.set_child(label)
            row.set_activatable(True)
            self._list.append(row)

    def _collapse(self) -> None:
        self._list.set_visible(False)
        # GTK4 windows never shrink once grown; force re-size to natural
        # content on the next layout pass (same trick as the overlay panel).
        self._win.set_default_size(1, 1)

    def _on_toggle(self, _btn) -> None:
        if self._list.get_visible():
            self._collapse()
        else:
            self._list.set_visible(True)

    def _on_row(self, _list, row) -> None:
        i = row.get_index()
        self._collapse()
        if not (0 <= i < len(self._names)):
            return
        league = self._names[i]
        if league != self._current:
            self._current = league
            self._refresh()
            _LOG.info("selected: %s", league)
            self._on_change(league)
