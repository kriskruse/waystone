# Vendored from Exiled Exchange 2

- **Source:** https://github.com/Kvan7/Exiled-Exchange-2
- **Commit:** `7523eb4b93f8531c483c3bcc9bd925afa7699d24` (cloned 2026-06-05)
- **License:** MIT (see `LICENSE` in this directory)
- **Upstream paths → vendor paths:**
  - `renderer/src/parser/` → `src/parser/`
  - `renderer/src/assets/data/` → `src/assets/data/`
  - `renderer/src/web/price-check/filters/` → `src/web/price-check/filters/` (`.ts` only, Vue components excluded)
  - `renderer/src/web/price-check/trade/` → `src/web/price-check/trade/` (`.ts` only)
  - `renderer/src/web/price-check/trends/getDetailsId.ts` → `src/web/price-check/trends/`
  - `renderer/src/web/background/{Prices,Leagues,TradeData}.ts` → `src/web/background/`
  - `renderer/src/assets/client-string-loader.ts` → `src/assets/`
  - `renderer/public/data/en/` + `item-drop.json` + `patrons.json` → `public/data/`
  - `renderer/src/assets/make-index-files.mjs` → `tools/`

## Local modifications

Keep this list short — the goal is byte-identical files so upstream re-pulls stay a plain copy.

1. `tools/make-index-files.mjs`: `LANGUAGES` reduced to `["en"]` (only English data vendored).
2. `src/assets/data/index.ts`: 8× mechanical replace `import.meta.env.BASE_URL` → `globalThis.EE2_DATA_BASE` (no Vite in the Node sidecar; `brain/src/bootstrap.ts` sets this global to a `file://` URL and shims `fetch` to read the vendored `public/` dir). No logic changes.
3. `src/assets/client-string-loader.ts`: 1× same mechanical `import.meta.env.BASE_URL` → `globalThis.EE2_DATA_BASE` replace (the global is a `file://` prefix so the dynamic `import()` of `client_strings.js` resolves as a native Node ESM file import). No logic changes.
4. `src/web/background/Leagues.ts`: 1× import-path edit `from "./IPC"` → `from "@/web/background/IPC"` (relative import bypassed the tsconfig stub alias). No logic changes.
5. `src/web/background/Prices.ts`: 2× import-path edits `from "../Config"` → `from "@/web/Config"` and `from "../overlay/widgets"` → `from "@/web/overlay/widgets"` (relative imports bypassed the tsconfig stub aliases). No logic changes.
6. `src/web/price-check/trade/pathofexile-trade.ts`: backported upstream's dual-shape mod handling — PoE2's trade2 fetch now returns mod blocks as objects (`{ description }`) as well as plain strings; `parseModBlock` unconditionally fed each entry to `parseAffixStrings` → `s.replace is not a function`. Added a `FetchResultMod = string | { description: string }` alias on the 8 `*Mods` fields and a `typeof s === "string"` branch in `parseModBlock`. Superseded on next re-pull by upstream's tier-aware version — drop this patch then.

All other coupling to the EE2 app (`@/web/Config`, `@/web/background/IPC`, `@/web/overlay/*`) is resolved via tsconfig path aliases pointing at stub modules in `brain/src/stubs/` — vendored files are NOT edited for this.

## Updating

On PoE2 game patches, upstream regenerates `public/data/*.ndjson` via its `dataParser/` pipeline. To update:

1. Pull latest EE2 (`git -C ~/Documents/Github/Exiled-Exchange-2 pull`).
2. Re-copy the paths above.
3. Re-apply the modifications above (1–5).
4. Run `npm run make-index-files` in `brain/`.
5. Update the commit hash at the top of this file.
