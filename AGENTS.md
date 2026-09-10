# POE2-Overlay

Path of Exile 2 price-checking overlay, built Wayland-first for Arch Linux + Hyprland. Exists because every existing tool (Exiled Exchange 2, Sidekick) is broken on Wayland — Electron refuses the portal GlobalShortcuts API (electron#38288, "not planned"), so we go around it.

## Architecture

Two processes, one Unix socket, JSON-lines protocol:

- **poed (Python)** — owns everything Wayland/desktop: GTK4 + gtk4-layer-shell overlay panel, global hotkeys via xdg-desktop-portal GlobalShortcuts (Gio DBus), clipboard (`wl-paste`), Ctrl+C injection into the game window (xdotool — PoE2 runs under Proton/XWayland), brain child-process lifecycle.
- **brain (Node/TypeScript)** — owns everything PoE: item-text parser, trade-query builder, trade2 + bulk API clients, rate limiter, cache. Vendored from Exiled Exchange 2 (MIT) under `vendor/ee2/` — see PROVENANCE.md there; keep modifications minimal so upstream pulls stay easy. Currency/material prices come from poe2scout (poe2scout.com/api — aggregated, volume-weighted, bulk-pulled into an in-memory TTL map keyed by tradeTag); the trade2 bulk exchange is only a fallback when poe2scout lacks an item. Gear/item listings still use trade2 search/fetch.

Rule of thumb: if it touches the compositor, portal, clipboard, or pixels → Python. If it touches item text, trade APIs, or game data → Node. Don't let PoE logic leak into Python; the Python side must stay dumb enough to test without a game running.

## Flow

Hotkey (`Alt+Z`, dynamically bound/unbound while PoE2 window exists — via `hyprctl eval 'hl.bind(...)'` on Lua-config systems, `hyprctl keyword bind` on hyprlang) → portal `Activated` → focused-window guard (`hyprctl activewindow`) → inject Ctrl+C → `wl-paste` → `{"cmd": "price", "clipboard": ...}` to brain → ParsedItem → brain auto-detects currency (`BaseType.tradeTag`) and returns `kind: "currency"` (exchange rates + stack value) or `kind: "price"` (listings) → layer-shell panel. Panel stays open until Esc; hotkey while open re-looks up the hovered item.

## Key constraints

- **Never** use Electron-style global shortcut APIs or X11 global grabs — portal GlobalShortcuts only. That failure mode is the whole reason this project exists.
- Overlay windows are wlr-layer-shell surfaces (overlay layer, keyboard `on_demand` — an `exclusive` grab seizes the whole seat and starves sibling surfaces), never normal toplevels — no Hyprland window-rule hacks. One-press Esc comes from a visibility-scoped consuming Esc bind, not a keyboard grab.
- Surfaces are TOP+LEFT-anchored and positioned via margins; draggable by a grab-handle strip. Live drag reads `hyprctl cursorpos` (compositor-absolute) — NOT the gesture's own offset, which feeds back through async margin commits and halves/jumps. Positions persist to `~/.local/state/waystone/positions.json`.
- Respect trade-API rate limits — EE2's `RateLimiter.ts` handles this; route all API calls through it.
- Game data (`vendor/ee2/data/*.ndjson`, ~2.4 MB) is regenerated upstream by EE2's `dataParser/` pipeline. On PoE2 patches: re-pull from the EE2 repo, don't hand-edit, don't run the pipeline locally.
- `AppConfig` is stubbed static (`language: "en"`, league from config) — non-English clients out of scope.

## Config

`~/.config/waystone/config.toml` (written with defaults on first run; old `poe2-overlay` dirs auto-migrate): league, hotkey_price, panel_position, panel_width, account name, game_window_class, poesessid (optional session cookie — keep the file chmod 600), unique_min_exalted (unique-scan highlight threshold; the scan hotkey is Alt+X).

## Testing

- Brain: vitest, golden clipboard samples (real PoE2 item text → expected ParsedItem + query JSON).
- Protocol: pytest round-trip against live brain child.
- E2E without game: canned clipboard through the full path.

**Never push without confirmed-green builds first**: `cd poed && python -m pytest`
and `cd brain && npx vitest run && npx tsc --noEmit` must pass, exit codes
checked directly — never piped through `tail`/`grep`, which swallow failures
(that exact mistake shipped a red suite once). Tests green is the smoke test;
no green, no push.

**Never `git push` without explicit permission** — committing locally is fine,
pushing requires the user's go-ahead each time. Ask, don't assume earlier
pushes granted a standing one.

## System deps (Arch)

`python-gobject gtk4 gtk4-layer-shell xdg-desktop-portal-hyprland wl-clipboard xdotool nodejs`
