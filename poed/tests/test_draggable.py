from poed.draggable import (
    clamp_position,
    _parse_cursorpos,
    _monitors_json,
    _monitor_by_id,
    _game_window_mid,
    position_on_monitor,
    gdk_monitor_by_name,
    attach_monitor,
)


def test_clamp_within_bounds_unchanged():
    assert clamp_position(100, 200, 2560, 1440, 400, 600) == (100, 200)


def test_clamp_negative_to_zero():
    assert clamp_position(-50, -10, 2560, 1440, 400, 600) == (0, 0)


def test_clamp_past_right_bottom_edges():
    # window must stay fully on-screen: max x = mon_w - win_w
    assert clamp_position(9999, 9999, 2560, 1440, 400, 600) == (2160, 840)


def test_clamp_window_larger_than_monitor_pins_zero():
    assert clamp_position(50, 50, 800, 600, 1000, 700) == (0, 0)


def test_parse_cursorpos_typical():
    assert _parse_cursorpos("2314, 880") == (2314, 880)


def test_parse_cursorpos_square_coords():
    assert _parse_cursorpos("1440, 1440") == (1440, 1440)


def test_parse_cursorpos_garbage_returns_none():
    assert _parse_cursorpos("") is None
    assert _parse_cursorpos("nonsense") is None
    assert _parse_cursorpos("5") is None


MONITORS = [
    {"id": 0, "x": 1880, "y": 0, "width": 2560, "height": 1440, "name": "HDMI-A-1"},
    {"id": 1, "x": 0, "y": 320, "width": 2560, "height": 1440, "name": "DP-1"},
    {"id": 2, "x": 1440, "y": 1440, "width": 3440, "height": 1440, "name": "DP-3"},
]


def test_monitors_json_parse():
    raw = """[{"id":0,"x":1880,"y":0,"width":2560,"height":1440,"name":"HDMI-A-1"},
              {"id":1,"x":0,"y":320,"width":2560,"height":1440,"name":"DP-1"},
              {"id":2,"x":1440,"y":1440,"width":3440,"height":1440,"name":"DP-3"}]"""
    assert _monitors_json(raw) == MONITORS


def test_monitors_json_garbage_returns_empty():
    assert _monitors_json("not json") == []
    assert _monitors_json('{"a": 1}') == []  # not a list
    assert _monitors_json("[1, 2]") == []    # elements not dicts


def test_monitor_by_id():
    assert _monitor_by_id(MONITORS, 2)["name"] == "DP-3"
    assert _monitor_by_id(MONITORS, None) is None
    assert _monitor_by_id(MONITORS, 99) is None


ACTIVE_GAME = '{"address":"0xabc","class":"steam_app_2694490","title":"Path of Exile 2","monitor":1}'
ACTIVE_OTHER = '{"address":"0xdef","class":"codium","title":"VSCodium","monitor":2}'
CLIENTS = """[
  {"address":"0xabc","class":"steam_app_2694490","monitor":1},
  {"address":"0x123","class":"codium","monitor":2}
]"""


def test_game_window_mid_prefers_focused_game():
    assert _game_window_mid(ACTIVE_GAME, CLIENTS, "steam_app_2694490") == 1


def test_game_window_mid_falls_back_to_clients_when_not_focused():
    # unique-scan fires without game focus; screenshot target = game's monitor.
    assert _game_window_mid(ACTIVE_OTHER, CLIENTS, "steam_app_2694490") == 1


def test_game_window_mid_none_when_no_game_window():
    assert _game_window_mid(ACTIVE_OTHER, "[]", "steam_app_2694490") is None


def test_game_window_mid_garbage_active_is_ignored():
    assert _game_window_mid("error: no window", CLIENTS, "steam_app_2694490") == 1


def test_position_on_monitor_keeps_fitting_saved():
    assert position_on_monitor((1519, 365), 3440, 1440, lambda _mw: (0, 80)) == (1519, 365)


def test_position_on_monitor_defaults_when_saved_off_monitor():
    # Saved margins larger than the target monitor (game moved to a smaller
    # monitor) must not park the surface off-screen.
    assert position_on_monitor((1519, 711), 1440, 2560, lambda mw: (mw // 2 - 380, 80)) == (340, 80)


def test_position_on_monitor_none_saved_uses_default():
    assert position_on_monitor(None, 3440, 1440, lambda mw: (int(mw * 0.35), 0)) == (1204, 0)


def test_position_on_monitor_edge_off_monitor_is_defaulted():
    # A margin exactly at mon_w would place the surface fully off-monitor.
    assert position_on_monitor((3440, 1440), 3440, 1440, lambda _mw: (0, 0)) == (0, 0)


def test_gdk_monitor_by_name_headless_none(monkeypatch):
    # No display available (CI / plain pytest): must not raise or match.
    from poed import draggable
    from poed.draggable import gdk_monitor_by_name

    monkeypatch.setattr(draggable.Gdk.Display, "get_default", lambda: None)
    assert gdk_monitor_by_name("DP-1") is None


def test_attach_monitor_headless_never_calls_layer_shell(monkeypatch):
    from poed import draggable
    from poed.draggable import attach_monitor

    monkeypatch.setattr(draggable.Gdk.Display, "get_default", lambda: None)
    assert attach_monitor(object(), "DP-1") is None
    assert attach_monitor(object(), None) is None
    assert attach_monitor(object(), "") is None
