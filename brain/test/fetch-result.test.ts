import { describe, expect, it } from "vitest";
import { __testExports } from "@/web/price-check/trade/pathofexile-trade";

const { parseFetchResult } = __testExports;

// Minimal FetchResult skeleton; per-test mod blocks are layered on top.
function makeResult(itemOverrides: Record<string, unknown>) {
  return {
    id: "x",
    item: {
      w: 2,
      h: 3,
      icon: "",
      sockets: [],
      name: "",
      typeLine: "Test Item",
      baseType: "Test Item",
      rarity: "Rare",
      identified: true,
      ...itemOverrides,
    },
    listing: {},
  } as unknown as Parameters<typeof parseFetchResult>[0];
}

describe("parseFetchResult mod blocks", () => {
  it("parses string-shaped mod blocks (legacy API shape)", () => {
    const out = parseFetchResult(
      makeResult({ explicitMods: ["+25 to maximum Life"] }),
    );
    expect(out.explicitMods?.[0].text).toBe("+25 to maximum Life");
  });

  // PoE2 trade2 fetch now returns some mod blocks as objects with a
  // `description` field instead of plain strings. Old parseModBlock fed the
  // whole object to parseAffixStrings -> "s.replace is not a function".
  it("parses object-shaped mod blocks (current API shape)", () => {
    const out = parseFetchResult(
      makeResult({
        explicitMods: [{ description: "+30 to maximum Life", mods: [] }],
      }),
    );
    expect(out.explicitMods?.[0].text).toBe("+30 to maximum Life");
  });

  it("still strips affix bracket markup on object-shaped mods", () => {
    const out = parseFetchResult(
      makeResult({
        explicitMods: [{ description: "[Life|maximum Life]", mods: [] }],
      }),
    );
    expect(out.explicitMods?.[0].text).toBe("maximum Life");
  });
});
