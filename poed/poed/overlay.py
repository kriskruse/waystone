import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, Gtk4LayerShell as LayerShell  # noqa: E402

from . import views
from . import draggable

# Launcher MUST set LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so before exec —
# setting it from inside Python after GI loads is too late (spike findings).

# Brain progress stages -> loading-label text. Unknown stages are ignored
# (forward compat with new brain stages).
_LOADING_STAGES = {
    "exchange": "checking currency exchange…",
    "listings": "searching trade listings…",
    "uniquescan": "scanning screen for uniques…",
}

_CSS = b"""
.poe-panel { background: rgba(11,11,14,0.96); border: 1px solid #3d3a2f;
             border-radius: 8px; padding: 12px; color: #cfcfc4; }
.poe-card { border: 1px solid #6b5a24; border-radius: 6px; padding: 10px;
            background: #15140f; }
.poe-name { color: #e8e154; font-weight: bold; }
.poe-name-unique { color: #af6025; font-weight: bold; }
.poe-base { color: #9a9786; font-size: 11px; }
.poe-label { color: #7f7c6a; font-size: 9px; }
.poe-mod { color: #8888ff; font-size: 12px; }
.poe-prop { color: #cfcfc4; font-size: 12px; }
.poe-row { padding: 4px 6px; border-top: 1px solid #22211b; }
.poe-dim { color: #7f7c6a; font-size: 11px; }
.poe-good { color: #7fff7f; font-weight: bold; }
.poe-badges { background: transparent; }
.poe-badge { color: #cfcfc4; background: rgba(0,0,0,0.75); padding: 1px 4px;
             border-radius: 3px; font-size: 11px; }
.poe-badge-good { color: #7fff7f; background: rgba(0,0,0,0.85); padding: 1px 4px;
                  border-radius: 3px; font-size: 12px; font-weight: bold; }
.poe-price { color: #ffffff; font-weight: bold; }
.poe-vbox { background: #0b0b0e; border: 1px solid #3a3850; color: #d8d8ff;
            font-size: 11px; min-height: 0; min-width: 0; padding: 0 4px; }
.poe-stat-on { color: #a8a8ff; font-size: 12px; }
.poe-stat-off { color: #55534a; font-size: 12px; }
.poe-btn { background: #1b1a14; border: 1px solid #6b5a24; color: #cfcfc4;
           font-size: 11px; padding: 2px 10px; }
.poe-btn:hover { background: #2a2820; }
.poe-btn:active { background: #3a3526; border-color: #e8e154; }
.poe-th { color: #9a9786; font-size: 12px; font-weight: bold; }
.poe-cur-num { color: #fff; font-weight: bold; font-size: 16px; }
.poe-cur-dim { color: #7f7c6a; font-size: 13px; }
.poe-cur-th { color: #9a9786; font-size: 14px; font-weight: bold; }
separator { background: #22211b; min-height: 1px; }
.poe-drag { background: #1b1a14; border-bottom: 1px solid #3d3a2f; }
.poe-drag:hover { background: #2a2820; }
.poe-trend-up { color: #7fc97f; font-weight: bold; font-size: 12px; }
.poe-trend-down { color: #cf6679; font-weight: bold; font-size: 12px; }
"""


def _default_pos(mon_w: int) -> tuple[int, int]:
    """Centered-ish panel default on a monitor of width mon_w (width unknown
    pre-layout, so eyeball ~760px)."""
    return (max(0, mon_w // 2 - 380), 80)


def _esc(s) -> str:
    return GLib.markup_escape_text(str(s))


def _icon(path, size: int):
    """Gtk.Image for a cached icon file, or None for text fallback.

    Gtk.Image.set_pixel_size CAPS the render size; Gtk.Picture +
    set_size_request only set a minimum and let big icons stay big.
    """
    if not path:
        return None
    img = Gtk.Image.new_from_file(path)
    img.set_pixel_size(size)
    return img


def _label(markup: str, css: str, xalign: float = 0.0, wrap: bool = True) -> Gtk.Label:
    lbl = Gtk.Label(xalign=xalign, wrap=wrap)
    lbl.set_markup(markup)
    lbl.add_css_class(css)
    return lbl


def _icon_or_text(path, size: int, fallback_text, fallback_css: str = "poe-dim"):
    """Cached icon image, or a text label when the icon is missing."""
    ic = _icon(path, size)
    return ic if ic else _label(_esc(fallback_text), fallback_css)


def _card_header(card: dict) -> Gtk.Widget:
    """Icon + name/base + props line. Shared by the read-only hover card and the
    interactive search card."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

    head = Gtk.Box(spacing=8)
    icon = _icon(card.get("icon"), 44)
    if icon:
        head.append(icon)
    names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    name_css = "poe-name-unique" if card.get("rarity") == "Unique" else "poe-name"
    names.append(_label(f"<b>{_esc(card.get('name', ''))}</b>", name_css, wrap=False))
    if card.get("base"):
        names.append(_label(_esc(card["base"]), "poe-base", wrap=False))
    head.append(names)
    box.append(head)

    if card.get("props"):
        parts = " · ".join(
            f"{_esc(p['text'])} <b>{_esc(p['value'])}</b>" for p in card["props"]
        )
        box.append(_label(parts, "poe-prop", wrap=False))
    return box


def build_card_widget(card: dict) -> Gtk.Widget:
    """Item card: icon + name/base header, grouped mod sections. Used for the
    top looked-up item AND hover popovers (from displayItem)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.add_css_class("poe-card")
    box.append(_card_header(card))

    for group_label, lines in card.get("groups", []):
        box.append(_label(_esc(group_label.upper()), "poe-label", wrap=False))
        for line in lines:
            tier = line.get("tier")
            suffix = f' <span alpha="45%">(T{int(tier)})</span>' if tier else ""
            lbl = _label(f"{_esc(line['text'])}{suffix}", "poe-mod")
            lbl.set_max_width_chars(46)
            lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            box.append(lbl)
    return box


def build_currency_card(v: dict) -> Gtk.Widget:
    """Single bordered currency card (mockup B): head strip (icon + name/stack +
    trend) over the ninja-style rate grid. `v` is a views.currency_view dict."""
    # One bordered poe-card box wraps the head strip AND the grid so the
    # whole currency column reads as a single framed card (mockup B).
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    card.add_css_class("poe-card")

    # Head row: [icon][name/stack vbox]  <hexpand spacer>  [trend label]
    head = Gtk.Box(spacing=8)
    icon = _icon(v["icon"], 44)
    if icon:
        head.append(icon)
    names = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    names.append(_label(f"<b>{_esc(v['name'])}</b>", "poe-name", wrap=False))
    names.append(_label(f"stack {_esc(v['stack'])}", "poe-base", wrap=False))
    head.append(names)
    if v["trend"] is not None:
        spacer = Gtk.Box(hexpand=True)
        head.append(spacer)
        trend_css = "poe-trend-up" if v["trend"] >= 0 else "poe-trend-down"
        head.append(_label(_esc(f"{v['trend']:+.1f}%"), trend_css, xalign=1.0, wrap=False))
    card.append(head)

    grid = Gtk.Grid(column_spacing=32, row_spacing=12)
    # Ninja-style fixed direction: every row reads "1 <item> = X <have>".
    # The header "1 <item> =" box anchors the shared left side; per-row cells
    # carry the rate (X + payment icon), stack value, and offer count.

    # Header row: "1 ×" + item icon + "=", then column titles.
    head_box = Gtk.Box(spacing=4)
    head_box.append(_label("<b>1 ×</b>", "poe-cur-th", wrap=False))
    head_box.append(_icon_or_text(v["one_icon"], 26, v["name"], "poe-cur-dim"))
    head_box.append(_label("=", "poe-cur-th", wrap=False))
    grid.attach(head_box, 0, 0, 1, 1)
    grid.attach(_label("Stack", "poe-cur-th", wrap=False), 1, 0, 1, 1)
    grid.attach(_label("offers", "poe-cur-th", wrap=False), 2, 0, 1, 1)

    grid_row = 1  # row 0 = header; each rate row gets a separator above it
    for r in v["rows"]:
        # Thin separator line above every rate row (including the first),
        # spanning all 4 columns; styled via CSS `separator { … }`.
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        grid.attach(sep, 0, grid_row, 4, 1)
        grid_row += 1

        # Rate cell: "X" + payment icon (26px), plus a dim inverse hint (16px) for sub-1.
        rate_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        top = Gtk.Box(spacing=4)
        top.append(_label(f"<b>{_esc(r['n'])}</b>", "poe-cur-num", wrap=False))
        top.append(_icon_or_text(r["icon"], 26, r["have"], "poe-cur-dim"))
        rate_box.append(top)
        if r["inverse"]:
            hint = Gtk.Box(spacing=4)
            hint.append(_label("1", "poe-cur-dim", wrap=False))
            hint.append(_icon_or_text(r["icon"], 16, r["have"], "poe-cur-dim"))
            hint.append(_label(f"= {_esc(r['inverse'])}", "poe-cur-dim", wrap=False))
            rate_box.append(hint)
        grid.attach(rate_box, 0, grid_row, 1, 1)
        # Stack value carries a 22px payment icon next to the number.
        stack_box = Gtk.Box(spacing=4)
        stack_box.append(_label(f"~<b>{_esc(r['stack_value'])}</b>", "poe-cur-num", wrap=False))
        stack_box.append(_icon_or_text(r["icon"], 22, r["have"], "poe-cur-dim"))
        grid.attach(stack_box, 1, grid_row, 1, 1)
        grid.attach(_label(_esc(r["total"]), "poe-cur-dim", wrap=False), 2, grid_row, 1, 1)
        grid_row += 1
    card.append(grid)
    return card


class OverlayPanel:
    def __init__(self, app: Gtk.Application, cfg: dict, on_requery=None, on_visibility=None, positions=None):
        self._cfg = cfg
        self._on_requery = on_requery
        self._on_visibility = on_visibility
        self._positions = positions
        self._overrides: dict[int, dict] = {}        # stat overrides, keyed by id -> {"i": id, ...}
        self._prop_overrides: dict[str, dict] = {}   # prop overrides, keyed by key -> {"p": key, ...}
        self._loginbox = None
        self._leaguebox = None
        self._requery_id = 0
        self._popovers: list = []
        self._active_pop = None
        self._busy_spinner: Gtk.Spinner | None = None
        self._loading_label: Gtk.Label | None = None
        self._win = Gtk.Window(application=app)
        LayerShell.init_for_window(self._win)
        LayerShell.set_layer(self._win, LayerShell.Layer.OVERLAY)
        # Start NONE; _present switches to EXCLUSIVE so Esc works without a
        # click. The panel pauses game input only while open — user-approved.
        LayerShell.set_keyboard_mode(self._win, LayerShell.KeyboardMode.NONE)

        # Always anchor TOP+LEFT and position via margins so the panel is draggable.
        # Follow the game: attach this surface to the monitor showing a game
        # window (when the game is already running at startup) so saved margins
        # are read relative to THAT monitor's origin, not gtk-layer-shell's
        # default one. The per-present re-attach in _present chases the game
        # between monitors.
        self._game_class = cfg.get("game_window_class", "")
        target = draggable.game_window_monitor(self._game_class)
        gdkm = draggable.attach_monitor(self._win, target.get("name") if target else None)
        saved = positions.get("panel") if positions is not None else None
        if gdkm is not None:
            geo = gdkm.get_geometry()
            self._pos = draggable.position_on_monitor(saved, geo.width, geo.height, _default_pos)
        else:
            # No game monitor (game not running, or resolution failed): union-
            # wide default placement as before.
            mon_w, _mon_h = draggable.monitor_geometry()
            self._pos = saved if saved is not None else _default_pos(mon_w)
        draggable.anchor_top_left(self._win, *self._pos)
        # No fixed default size: the layer-shell surface sizes to its content.
        # Price view keeps the listings column usable via the scroll's min
        # content size; currency view hides the scroll so the window shrinks to
        # the narrow card column.

        provider = Gtk.CssProvider()
        provider.load_from_data(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._card_slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        # minimum card width — 350px first test; natural sizing still grows beyond
        self._card_slot.set_size_request(350, -1)
        # Card column takes its natural width; listings flex on the right.
        self._header = Gtk.Box(spacing=6)  # currency view summary strip only
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        # Keep the listings column usable in price view; currency view hides the
        # scroll so these minimums don't pin the window wide.
        self._scroll.set_min_content_width(480)
        self._scroll.set_min_content_height(520)
        self._scroll.set_child(self._list)
        # Horizontal content: card column left, listings/grid right.
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left.append(self._card_slot)
        left.append(self._header)
        box.append(left)
        box.append(self._scroll)
        # Vertical root: drag handle on top, the horizontal content below.
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("poe-panel")
        root.append(draggable.make_drag_handle(self._win, self._get_pos, self._save_pos))
        root.append(box)
        self._win.set_child(root)

        ctl = Gtk.EventControllerKey()
        ctl.connect("key-pressed", self._on_key)
        self._win.add_controller(ctl)

    def _on_key(self, _ctl, keyval, *_):
        if keyval == Gdk.KEY_Escape:
            # Entry focus lives in a Gtk.Text child; first Esc drops focus so the
            # box stops swallowing keys, second Esc hides the panel.
            focus = self._win.get_focus()
            if isinstance(focus, (Gtk.Entry, Gtk.Text)):
                self._win.set_focus(None)
                return
            self.hide()

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
            self._positions.set("panel", *self._pos)
        draggable.set_position(self._win, *self._pos)

    def _cancel_requery(self):
        if self._requery_id:
            GLib.source_remove(self._requery_id)
            self._requery_id = 0

    def _clear(self):
        self._cancel_requery()
        if self._busy_spinner is not None:
            self._busy_spinner.stop()
            self._busy_spinner.set_visible(False)
        for pop in self._popovers:
            pop.popdown()
            pop.unparent()
        self._popovers = []
        self._active_pop = None
        self._loading_label = None
        for container in (self._list, self._card_slot, self._header):
            while (child := container.get_first_child()) is not None:
                container.remove(child)

    def _price_row(self, r: dict) -> Gtk.Widget:
        row = Gtk.Box(spacing=8)
        row.add_css_class("poe-row")
        amount = f"<b><u>{_esc(r['amount'])} ×</u></b>" if r["mine"] else f"<b>{_esc(r['amount'])} ×</b>"
        row.append(_label(amount, "poe-price", wrap=False))
        icon = _icon(r["icon"], 24)
        if icon:
            row.append(icon)
        else:
            parts = r["price"].split(" ", 1)
            fallback = parts[1] if len(parts) > 1 else ""
            row.append(_label(_esc(fallback), "poe-dim", wrap=False))
        dot = "●" if r["status"] == "online" else "○"
        who = _label(
            f"{dot} {_esc(r['ign'] or r['seller'])} · {_esc(r['age'])}", "poe-dim", 1.0, wrap=False
        )
        who.set_hexpand(True)
        row.append(who)

        if r.get("display_item"):
            pop = Gtk.Popover()
            pop.set_parent(row)
            pop.set_autohide(False)
            pop.set_position(Gtk.PositionType.RIGHT)
            sw = Gtk.ScrolledWindow(max_content_height=480, propagate_natural_height=True,
                                    max_content_width=380, propagate_natural_width=True)
            sw.set_child(build_card_widget(views.display_item_card(r["display_item"])))
            pop.set_child(sw)
            self._popovers.append(pop)

            pending = {"id": 0}

            def _on_enter(*_):
                # Instant switch: hide whatever popover is showing now, skipping
                # its leave debounce, so hovering down the list never lingers.
                if self._active_pop is not None and self._active_pop is not pop:
                    self._active_pop.popdown()
                if pending["id"]:
                    GLib.source_remove(pending["id"])
                    pending["id"] = 0
                self._active_pop = pop
                pop.popup()

            def _popdown():
                pending["id"] = 0
                if pop.get_parent() is not None:
                    pop.popdown()
                if self._active_pop is pop:
                    self._active_pop = None
                return GLib.SOURCE_REMOVE

            def _on_leave(*_):
                if pending["id"]:
                    GLib.source_remove(pending["id"])
                pending["id"] = GLib.timeout_add(150, _popdown)

            motion = Gtk.EventControllerMotion()
            motion.connect("enter", _on_enter)
            motion.connect("leave", _on_leave)
            row.add_controller(motion)
        return row

    # -- public API (GLib main thread only) --------------------------------

    def attach_loginbox(self, box) -> None:
        """Bind a LoginBox so it shows/hides with the panel."""
        self._loginbox = box

    def attach_leaguebox(self, box) -> None:
        """Bind a LeagueBox so it shows/hides with the panel."""
        self._leaguebox = box

    def show_loading(self) -> None:
        # New lookup: drop any pending user intent from the previous item.
        self._overrides = {}
        self._prop_overrides = {}
        self._clear()
        self._scroll.set_visible(True)
        self._loading_label = _label("checking price…", "poe-dim", wrap=False)
        self._header.append(self._loading_label)
        self._list.append(Gtk.Spinner(spinning=True))
        self._present()

    def set_loading_stage(self, stage: str) -> None:
        """Update the loading text while a lookup is in flight; no-op once
        results are delivered (label cleared) or for unknown stages."""
        text = _LOADING_STAGES.get(stage)
        if text is None or self._loading_label is None:
            return
        self._loading_label.set_label(text)

    def _overrides_list(self) -> list[dict]:
        # Merge stat ({"i": id}) and prop ({"p": key}) overrides into one list.
        out = [{"i": sid, **fields} for sid, fields in self._overrides.items()]
        out += [{"p": key, **fields} for key, fields in self._prop_overrides.items()]
        return out

    def _dispatch_requery(self) -> None:
        # on_requery returns True when dispatched, False when dropped by the
        # in-flight guard. On a drop, re-arm via _schedule_requery: the retry
        # fires 800ms later, by when the in-flight request will have cleared —
        # without this the user's last edit is silently lost (lost-update race).
        if self._on_requery is None:
            return
        overrides_list = self._overrides_list()
        if self._on_requery(overrides_list):
            if self._busy_spinner is not None:
                self._busy_spinner.set_visible(True)
                self._busy_spinner.start()
        else:
            self._schedule_requery()

    def _schedule_requery(self) -> None:
        self._cancel_requery()

        def _fire():
            self._requery_id = 0
            self._dispatch_requery()
            return GLib.SOURCE_REMOVE

        self._requery_id = GLib.timeout_add(800, _fire)

    def _interactive_card(self, result: dict) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("poe-card")

        # Header (mockup A): big 128px item icon on the left, a vertical box on
        # the right carrying name, base, and the prop rows — so properties sit
        # visually "next to the icon". (The hover-popover _card_header stays 44px.)
        card = views.item_card(result.get("item"))
        prop_rows = views.prop_rows(result)
        head = Gtk.Box(spacing=8)
        icon = _icon((card or {}).get("icon"), 128) if card else None
        if icon:
            icon.set_valign(Gtk.Align.START)
            head.append(icon)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info.set_hexpand(True)
        if card:
            name_css = "poe-name-unique" if card.get("rarity") == "Unique" else "poe-name"
            info.append(_label(f"<b>{_esc(card.get('name', ''))}</b>", name_css, wrap=False))
            if card.get("base"):
                info.append(_label(_esc(card["base"]), "poe-base", wrap=False))
        # Props (Quality/Evasion/ES/Armour/RW/ilvl etc.) render directly under the
        # name/base block, same filter-row widget as stats but routed to {"p": key}.
        if prop_rows:
            for r in prop_rows:
                info.append(self._filter_row(r))
        head.append(info)
        box.append(head)

        for group_label, rows in views.stat_groups(result):
            box.append(_label(_esc(group_label.upper()), "poe-label", wrap=False))
            for r in rows:
                box.append(self._filter_row(r))

        # Non-scalable / item-specific lines (parsed mods with no matching stat
        # filter, e.g. evasion affixes the pipeline folds into the base total).
        # Display-only: dim, no entry box, no toggle gesture — they cannot be
        # searched, so they're shown purely for context under an "ITEM" label.
        unsearchable = views.unsearchable_lines(result)
        if unsearchable:
            box.append(_label("ITEM", "poe-label", wrap=False))
            for line in unsearchable:
                box.append(_label(_esc(line["text"]), "poe-stat-off"))

        # Search button + busy spinner row
        btn_row = Gtk.Box(spacing=6, orientation=Gtk.Orientation.HORIZONTAL)
        search_btn = Gtk.Button(label="Search")
        search_btn.add_css_class("poe-btn")
        spinner = Gtk.Spinner()
        spinner.set_visible(False)
        self._busy_spinner = spinner

        def _on_search(_btn):
            self._cancel_requery()
            self._dispatch_requery()

        search_btn.connect("clicked", _on_search)
        btn_row.append(search_btn)
        btn_row.append(spinner)
        box.append(btn_row)

        # Min-price summary at the card bottom: "N <16px icon>" left, "M listings"
        # right (hexpand spacer between). Replaces the old _header_price strip.
        summary = views.price_summary(result)
        sum_row = Gtk.Box(spacing=6)
        sum_row.add_css_class("poe-row")
        if summary["min"] is not None:
            sum_row.append(_label(f"<b>{_esc(summary['min'])} ×</b>", "poe-price", wrap=False))
            icon = _icon(summary["icon"], 16)
            if icon:
                sum_row.append(icon)
            elif summary["currency"]:
                sum_row.append(_label(_esc(summary["currency"]), "poe-dim", wrap=False))
        sum_row.append(Gtk.Box(hexpand=True))
        sum_row.append(_label(_esc(summary["count"]), "poe-dim", 1.0, wrap=False))
        box.append(sum_row)
        return box

    def _filter_row(self, r: dict) -> Gtk.Widget:
        """Editable+toggleable filter row, shared by stats and props.

        Prop rows (kind=="prop") route to self._prop_overrides keyed by the bare
        prop key (the "p:" id prefix is stripped) and emit {"p": key}; every other
        row (stats, and property-tagged stats with kind=="stat") routes to
        self._overrides keyed by integer id and emits {"i": id}.
        """
        if r.get("kind") == "prop":
            store = self._prop_overrides
            key = r["id"][2:] if r["id"].startswith("p:") else r["id"]
        else:
            store = self._overrides
            key = r["id"]
        enabled = r["enabled"]
        css = "poe-stat-on" if enabled else "poe-stat-off"

        row = Gtk.Box(spacing=6)
        row.add_css_class(css)

        text = Gtk.Label(xalign=0.0)
        # Bounded soft-wrap: max_width_chars caps natural width so the
        # GTK min>natural measure warning cannot return (wrap=True alone,
        # with no upper bound, triggers it on wide stat strings).
        text.set_wrap(True)
        text.set_max_width_chars(46)
        text.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        # Human-readable label: value substituted into the `#` template
        # ("30 to Dexterity", "Item Level 80"); falls back to the raw template.
        text.set_text(r.get("label") or r["text"])  # plain text, no markup
        text.add_css_class(css)

        spacer = Gtk.Box(hexpand=True)

        # Roll-less stats (value is None) have no number to filter on, so they get
        # a fixed-width placeholder instead of a dead, useless min-Entry.
        if r["value"] is None:
            placeholder = Gtk.Label(label="—", width_chars=4)
            placeholder.add_css_class("poe-dim")
            row.append(placeholder)
            row.append(text)
            row.append(spacer)
        else:
            entry = Gtk.Entry(width_chars=4)
            entry.set_max_width_chars(4)
            entry.add_css_class("poe-vbox")
            entry.set_text(r["min"] if r["min"] is not None else "")
            row.append(entry)
            row.append(text)
            row.append(spacer)

            def _on_changed(_e):
                raw = entry.get_text().strip()
                if raw == "":
                    store.setdefault(key, {})["min"] = None
                else:
                    try:
                        val = float(raw)
                    except ValueError:
                        return  # invalid — leave override untouched, don't requery
                    store.setdefault(key, {})["min"] = val
                self._schedule_requery()

            # connect AFTER set_text: a 'changed' handler live during the programmatic fill would write spurious overrides and requery-loop on every rebuild.
            entry.connect("changed", _on_changed)

        def _on_toggle(_g, _n, _x, _y):
            new_enabled = not store.get(key, {}).get("enabled", enabled)
            store.setdefault(key, {})["enabled"] = new_enabled
            new_css = "poe-stat-on" if new_enabled else "poe-stat-off"
            old_css = "poe-stat-off" if new_enabled else "poe-stat-on"
            for w in (row, text):
                w.remove_css_class(old_css)
                w.add_css_class(new_css)
            self._schedule_requery()

        # Gesture on the text label only — Entry clicks must not toggle.
        click = Gtk.GestureClick()
        click.connect("pressed", _on_toggle)
        text.add_controller(click)
        return row

    def show_price(self, result: dict) -> None:
        # NOTE: overrides are NOT cleared here — requery responses re-render and
        # brain echoes effective state, so self._overrides stays the source of
        # pending user intent across requeries (cleared only in show_loading).
        # _clear stops/hides the busy spinner before we rebuild.
        self._clear()
        self._scroll.set_visible(True)
        self._card_slot.append(self._interactive_card(result))
        for r in views.price_rows(result):
            self._list.append(self._price_row(r))
        # Size settling is handled by _present's idle _settle_size, which runs
        # after this rebuilt content has been laid out.
        # Don't re-present a panel the user already dismissed with Esc — a stale
        # in-flight response must not pop the overlay back up.
        if self.is_visible():
            self._present()

    def show_currency(self, result: dict) -> None:
        # Single-column view (mockup B): head card + grid stacked in the card
        # slot; the listings scroll is hidden so the unanchored layer window
        # shrinks toward the narrow content instead of the two-column layout.
        self._clear()
        self._scroll.set_visible(False)
        v = views.currency_view(result)
        self._card_slot.append(build_currency_card(v))
        # Size settling is handled by _present's idle _settle_size, which runs
        # after this rebuilt content has been laid out.
        if self.is_visible():
            self._present()

    def show_uniques(self, matches: list[dict], min_exalted: float,
                     elapsed: float | None = None) -> None:
        """Unique-scan results: one row per matched item, sorted by price
        (views.unique_rows), valuable rows highlighted. `elapsed` = hotkey
        press to panel delivery, shown so perceived latency stays honest."""
        self._clear()
        self._scroll.set_visible(True)
        rows = views.unique_rows(matches, min_exalted)
        timing = f" — {elapsed:.1f}s" if elapsed is not None else ""
        self._header.append(
            _label(f"uniques on screen ({len(rows)}){timing}", "poe-dim", wrap=False)
        )
        if not rows:
            self._list.append(_label("nothing recognized", "poe-dim"))
        for r in rows:
            row = Gtk.Box(spacing=8)
            row.add_css_class("poe-row")
            name = _label(
                _esc(r["name"]),
                "poe-name-unique" if r["kind"] == "unique" else "poe-prop",
                wrap=False,
            )
            name.set_hexpand(True)
            price = _label(f'{_esc(r["price"])} ex',
                           "poe-good" if r["good"] else "poe-dim", wrap=False)
            row.append(name)
            if r.get("trend"):
                row.append(_label(_esc(r["trend"]), "poe-dim", wrap=False))
            row.append(price)
            self._list.append(row)
        # Scan results always pop the panel: the hotkey is an explicit ask,
        # unlike a stale in-flight price response racing a dismissed panel.
        self._present()

    def show_error(self, message: str) -> None:
        self._clear()
        self._scroll.set_visible(True)
        self._list.append(_label(_esc(message), "poe-dim"))
        if self.is_visible():
            self._present()

    def is_visible(self) -> bool:
        return self._win.get_visible()

    def hide(self) -> None:
        self._cancel_requery()
        self._win.set_visible(False)
        # GTK4 windows never shrink once grown. Reset the default size to 1×1 so
        # that on the next present() the window re-sizes to its natural content
        # width/height rather than keeping the previous (larger) surface.
        self._win.set_default_size(1, 1)
        if self._loginbox is not None:
            self._loginbox.set_visible(False)
        if self._leaguebox is not None:
            self._leaguebox.set_visible(False)
        # Release keyboard so the game regains input the moment the panel hides.
        LayerShell.set_keyboard_mode(self._win, LayerShell.KeyboardMode.NONE)
        if self._on_visibility is not None:
            self._on_visibility(False)

    def _present(self):
        # Follow the game across monitors: re-attach on every present (the game
        # may have moved since the last lookup). Margins are read relative to
        # the target monitor's origin; saved margins are kept when they fit,
        # else defaulted onto that monitor. Failure to resolve keeps the
        # current monitor and position.
        target = draggable.game_window_monitor(self._game_class)
        gdkm = draggable.attach_monitor(self._win, target.get("name") if target else None)
        if gdkm is not None:
            geo = gdkm.get_geometry()
            self._pos = draggable.position_on_monitor(
                self._pos, geo.width, geo.height, _default_pos
            )
        # ON_DEMAND, not EXCLUSIVE: the exclusive grab seized the whole seat —
        # it blocked typing on other monitors and starved the sibling LoginBox
        # surface of pointer input. Cost: Esc needs one click on the panel
        # first when the game holds focus.
        LayerShell.set_keyboard_mode(self._win, LayerShell.KeyboardMode.ON_DEMAND)
        # Start minimal so the layout grows to natural size rather than committing
        # at a stale/huge allocation from the previous (larger) content.
        self._win.set_default_size(1, 1)
        self._win.present()
        # Re-assert the saved/centered spot after present — also exercises the
        # live-margin-after-present path the drag relies on.
        draggable.set_position(self._win, *self._pos)
        if self._loginbox is not None:
            self._loginbox.set_visible(True)
        if self._leaguebox is not None:
            self._leaguebox.set_visible(True)
        if self._on_visibility is not None:
            self._on_visibility(True)
        # The content was just rebuilt; its natural size isn't known until the
        # next layout pass. Re-commit the margin + force a resize on idle so the
        # surface settles to natural size instead of presenting huge (what a
        # manual drag was doing by hand).
        GLib.idle_add(self._settle_size)

    def _settle_size(self):
        self._win.set_default_size(1, 1)
        self._win.queue_resize()
        draggable.set_position(self._win, *self._pos)
        return GLib.SOURCE_REMOVE
