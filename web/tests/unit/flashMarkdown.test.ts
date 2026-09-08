import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { parseBlocks } from "@/lib/flash/markdown";

const HERE = dirname(fileURLToPath(import.meta.url));
const close = JSON.parse(
  readFileSync(
    resolve(HERE, "../../../tests/fixtures/flash/2026-09-03-close.json"),
    "utf8",
  ),
) as { view: { sections: { title: string; body: string }[] } };
const intraday = JSON.parse(
  readFileSync(
    resolve(HERE, "../../../tests/fixtures/flash/2026-09-03-intraday.json"),
    "utf8",
  ),
) as { view: { coverage: { body: string } } };

/**
 * The coverage body of the option-wizard premarket run of 2026-09-03, exactly
 * as `GET /api/agent-runs/run/premarket/2026-09-03` returned it (version 2,
 * read 2026-09-04). Frozen here because it is the only recorded body carrying
 * helium's pipe table, and the shipped fixture file holds the earlier version.
 */
const COVERAGE_TABLE = [
  "| Layer | Source | As-of | Status |",
  "|---|---|---|---|",
  "| Rates | ow_macro_rates liveNow (TradingView) — 2Y 4.332%, 10Y 4.75%, 30Y 5.234%, 2s10s +41.8bp | fetchedAt 2026-09-03T16:32:30.703Z | ✓ |",
  "| Credit (HY OAS) | ow_macro_rates fredDirect, BAMLH0A0HYM2 = 2.66% (FRED direct, ~1–2 day lag) | asOf 2026-09-02 | ✓ |",
  "| Credit (CCC OAS) | — | — | skipped — no CCC OAS source |",
  "| Tape | ow_spot (TradingView) — SPY 772.33, QQQ 716.56, IWM 295.03; VIX unpriced (ow_spot 422), VIX 14.58 taken from ow_macro_rates liveNow | fetchedAt 2026-09-03T16:32:33.870Z | ✓ |",
  "| Flow / GEX | ow_uw_market_state market/sector(Technology)/ETF(XLK) tide — INTRADAY-LIVE, session date 2026-09-03 | tide date 2026-09-03 | ✓ |",
  "| Events | ow_uw_calendar — Hammack/Goolsbee 2026-09-03T19:00:00Z; payrolls 2026-09-04T12:30:00Z | asOf 2026-09-03T16:32:32.058Z | ✓ |",
  "",
  "Stale-series note (ow_macro_rates staleSeries): the HY OAS daily mirror (BAMLH0A0HYM2) latest observation is 2026-08-31/2026-09-01 (~2 days behind) — the 2.66% figure above is the fresher FRED-direct point at asOf 2026-09-02, not the daily series.",
].join("\n");

describe("parseBlocks", () => {
  it("reads helium's coverage pipe table and the paragraph after it", () => {
    const blocks = parseBlocks(COVERAGE_TABLE);
    expect(blocks).toHaveLength(2);

    const table = blocks[0];
    if (table.type !== "table") throw new Error("expected a table block");
    // The |---|---| rule is structure, not a row.
    expect(table.header).toEqual(["Layer", "Source", "As-of", "Status"]);
    expect(table.rows).toHaveLength(6);
    expect(table.rows[0][0]).toBe("Rates");
    expect(table.rows[2]).toEqual([
      "Credit (CCC OAS)",
      "—",
      "—",
      "skipped — no CCC OAS source",
    ]);
    expect(table.rows[5][0]).toBe("Events");
    for (const row of table.rows) expect(row).toHaveLength(4);

    const tail = blocks[1];
    if (tail.type !== "p") throw new Error("expected a paragraph block");
    expect(tail.text).toContain("Stale-series note");
  });

  it("splits a real multi-paragraph body on its blank lines", () => {
    const body = close.view.sections.find((s) => s.title === "今日市场")!.body;
    const blocks = parseBlocks(body);
    expect(blocks).toHaveLength(4);
    expect(blocks.every((b) => b.type === "p")).toBe(true);
    const first = blocks[0];
    if (first.type !== "p") throw new Error("expected a paragraph block");
    expect(first.text.startsWith("股票磁带全线走强")).toBe(true);
    const last = blocks[3];
    if (last.type !== "p") throw new Error("expected a paragraph block");
    expect(last.text).toContain("非农");
  });

  it("cuts helium's run-together settlement records into one item each", () => {
    // The close run of 2026-09-03 wrote all three settlements as one block, so
    // the paragraph rule joins them into a single wall of prose. The record id
    // is the only seam, and it is dropped once it has done its work.
    const body = close.view.sections.find(
      (s) => s.title === "Settlements not in the ledger, dropped",
    )!.body;
    const blocks = parseBlocks(body);
    expect(blocks).toHaveLength(1);

    const list = blocks[0];
    if (list.type !== "ul") throw new Error("expected a ul block");
    expect(list.items).toHaveLength(3);
    expect(list.items[0].startsWith("QQQ 不变 — Entry 716 above")).toBe(true);
    expect(list.items[0].endsWith("Close price 717.67.")).toBe(true);
    expect(list.items[1].startsWith("SPY 不变 —")).toBe(true);
    expect(list.items[2].startsWith("SLV 加强 —")).toBe(true);
    // The ids themselves are helium's keys, not the reader's text.
    for (const item of list.items) {
      expect(item).not.toContain("2026-09-03-");
    }
  });

  it("leaves a paragraph mentioning ONE record alone", () => {
    const one = "QQQ-2026-09-03-1 QQQ 不变 — held above entry.";
    expect(parseBlocks(one)).toEqual([{ type: "p", text: one }]);
  });

  it("keeps an unrecognised body whole, as one paragraph", () => {
    const blocks = parseBlocks(intraday.view.coverage.body);
    expect(blocks).toHaveLength(1);
    const only = blocks[0];
    if (only.type !== "p") throw new Error("expected a paragraph block");
    // The run's " | "-separated layers are prose, not a table: no line starts
    // with a pipe, so nothing is reshaped.
    expect(only.text).toContain("SESSION NOTE (pitfall 07)");
    expect(only.text).toContain("POLICY PATH — SOURCE ow_argon_policy_path");
  });

  it("reads a dash list, and a single newline as a block seam", () => {
    expect(parseBlocks("- one\n- two\n- three")).toEqual([
      { type: "ul", items: ["one", "two", "three"] },
    ]);
    // helium writes block-level markdown joined by single newlines (schema 3):
    // a bare line is its own statement, never a soft wrap of the previous one.
    expect(parseBlocks("first line\nsecond line")).toEqual([
      { type: "p", text: "first line" },
      { type: "p", text: "second line" },
    ]);
    // A heading line over a bullet run — §3/§5 of the weekly review — is one
    // paragraph followed by one list, not a paragraph with inline " - ".
    expect(parseBlocks("3a macro\n- SPX — CONTINUE\n- VIX — FADE")).toEqual([
      { type: "p", text: "3a macro" },
      { type: "ul", items: ["SPX — CONTINUE", "VIX — FADE"] },
    ]);
    expect(parseBlocks("")).toEqual([]);
    expect(parseBlocks("   \n\n  ")).toEqual([]);
  });
});
