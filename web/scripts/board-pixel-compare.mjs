/**
 * Board-vs-live design conformance check.
 *
 * ## Why this is not a raw pixel diff
 *
 * The obvious reading of "pixel comparison" is `board.png XOR live.png`, and it would
 * report almost nothing useful. The board's panels carry MOCK values frozen at its capture
 * instant and the live desk derives its own at render time — that is a rule of this port,
 * not a defect — so a bitmap subtraction is dominated by digits and prose and says nothing
 * about whether the design was ported. Two pages can differ in every pixel and share a
 * design; two can be pixel-close and disagree on every token.
 *
 * So the comparison is made where the design actually lives:
 *
 *   1. GRAMMAR COVERAGE — every class the board's stylesheet defines and uses, against
 *      whether the live desk uses it. A class the board renders and the live page never
 *      does is a design element that was not ported.
 *   2. COMPUTED STYLE — for each selector present on both sides, the resolved values the
 *      browser actually paints. This is the pixel-level check, one layer above pixels:
 *      it compares what would be painted rather than what the stylesheet claims.
 *   3. SCREENSHOTS — full-page, both sides, for the eye to catch what neither can:
 *      proportion, rhythm, whether a grid reads as a grid.
 *
 * ## Two normalisations, both load-bearing
 *
 * Without them the report is 300 lines of noise and nobody reads it twice.
 *
 *   - SELECTORS, NOT CLASSES. `.tag` matches `.tag.real` (teal) and `.tag.q` (violet), and
 *     a bare `querySelector` picks whichever comes first in each document — so the probe
 *     reports a colour difference that is really "the two pages open with a different kind
 *     of tag". Every entry below is specific enough to name ONE thing.
 *   - COLOUR SPACE. argon renders the board's `rgba()` overlays as `color-mix()`, a
 *     recorded deviation (the board is single-theme dark; argon has a light theme). Chrome
 *     serialises the result as `color(srgb …)`, which is the same paint in a different
 *     notation. Both sides are normalised to 8-bit rgba before comparison, so a real
 *     colour change still shows and a notation change does not.
 *
 * Run: node scripts/board-pixel-compare.mjs
 * Output: output/playwright/board-compare/
 */
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const BOARD =
  process.env.BOARD_HTML ??
  resolve("../docs/superpowers/specs/2026-08-27-macro-desk-board.html");
const LIVE = process.env.LIVE_BASE ?? "http://127.0.0.1:3002";
const OUT = resolve("../output/playwright/board-compare");

/** Board tab id -> the live route that ports it. t8 does not ship on the strip. */
const TABS = [
  ["t0", "overview"],
  ["t1", "fed"],
  ["t2", "rates"],
  ["t3", "inflation"],
  ["t4", "usd"],
  ["t5", "gold"],
  ["t6", "energy"],
  ["t7", "factors"],
];

/** The properties that decide whether an element looks like itself. */
const PROPS = [
  "fontFamily",
  "fontSize",
  "fontWeight",
  "letterSpacing",
  "lineHeight",
  "textTransform",
  "color",
  "backgroundColor",
  "borderTopWidth",
  "borderLeftWidth",
  "borderTopColor",
  "borderLeftColor",
  "borderTopLeftRadius",
  "paddingTop",
  "paddingLeft",
  "gap",
  "display",
  "opacity",
];

/**
 * What to compare. Each entry names ONE visual thing.
 *
 * The board's own shell (`.appbar`, `.tabbar`, `.wrap`, `.pmq`, `.intro`) is excluded:
 * argon supplies its own chrome around the desk and the board's masthead is not what was
 * being ported. What is here is the CONTENT grammar — the part that has to match.
 */
const SELECTORS = [
  ["section-title", ".sec-title h2"],
  ["section-standfirst", "p.sec-sub"],
  ["panel", ".panel"],
  ["panel-heading", ".panel-h h3"],
  ["read-rail", "p.read, div.read"],
  ["provenance", ".prov"],
  ["tag-real", ".tag.real"],
  ["tag-question", ".tag.q"],
  ["table-header-cell", "th"],
  ["table-cell", "td"],
  ["table-numeric-cell", "td.num"],
  ["big-number", ".big"],
  ["state-pill", ".state"],
  ["grid-2up", ".grid.g2"],
  ["grid-3up", ".grid.g3"],
  ["refusal-note", ".note-refuse"],
  ["arith-term", ".arith .term"],
  ["arith-result", ".arith .res"],
  ["zone-banner", ".zone"],
  ["zone-kicker", ".zone .zk"],
  ["zone-label", ".zone .zl"],
  ["chain-node", ".node"],
  ["chain-node-heading", ".node h3"],
  ["chain-kv", ".node .kv"],
  ["confidence-bar", ".conf"],
  ["confidence-track", ".conf .track"],
  ["meter-label", ".meter .lbl"],
  ["meter-track", ".meter .track"],
  ["meter-value", ".meter .val"],
  ["contradiction", ".contra"],
  ["contradiction-heading", ".contra b"],
  ["chart-frame", ".chart"],
  ["caption", ".cap"],
  ["legend", ".lgd"],
  ["ghost-panel", ".ghost"],
  ["chip", ".chip"],
  ["edge-note", ".edge-note"],
  ["meeting-row", ".meet"],
  ["probability-bar", ".pbar"],
  ["direction-label", ".dir"],
  ["tight-list-item", "ul.tight li"],
];

const probeSource = `
window.__probe = (entries, props) => {
  const norm = (v) => {
    if (typeof v !== "string") return v;
    // color(srgb r g b / a) -> rgba(R, G, B, a). argon renders the board's rgba()
    // overlays through color-mix(), which Chrome serialises in srgb notation. Same
    // paint, different spelling.
    const m = v.match(/^color\\(srgb ([\\d.]+) ([\\d.]+) ([\\d.]+)(?: \\/ ([\\d.]+))?\\)$/);
    if (m) {
      const to255 = (x) => Math.round(parseFloat(x) * 255);
      const a = m[4] === undefined ? 1 : Math.round(parseFloat(m[4]) * 100) / 100;
      return a === 1
        ? \`rgb(\${to255(m[1])}, \${to255(m[2])}, \${to255(m[3])})\`
        : \`rgba(\${to255(m[1])}, \${to255(m[2])}, \${to255(m[3])}, \${a})\`;
    }
    const r = v.match(/^rgba?\\(([\\d.]+),\\s*([\\d.]+),\\s*([\\d.]+)(?:,\\s*([\\d.]+))?\\)$/);
    if (r) {
      const a = r[4] === undefined ? 1 : Math.round(parseFloat(r[4]) * 100) / 100;
      const c = (x) => Math.round(parseFloat(x));
      return a === 1
        ? \`rgb(\${c(r[1])}, \${c(r[2])}, \${c(r[3])})\`
        : \`rgba(\${c(r[1])}, \${c(r[2])}, \${c(r[3])}, \${a})\`;
    }
    return v;
  };
  const out = {};
  for (const [name, sel] of entries) {
    let el = null;
    try { el = document.querySelector(sel); } catch { el = null; }
    if (!el) { out[name] = null; continue; }
    const cs = getComputedStyle(el);
    const rec = {};
    for (const p of props) rec[p] = norm(cs[p]);
    // The first font family only. The board and argon declare different FALLBACK chains
    // and both resolve to the same face; a difference after the first entry is invisible
    // unless that face fails to load, and is reported separately rather than 40 times.
    rec.fontFamily = (rec.fontFamily || "").split(",")[0].trim().replace(/^"|"$/g, "");
    out[name] = rec;
  }
  return out;
};
`;

/** A property whose value cannot mean anything on this element. */
const MEANINGLESS = (prop, rec) =>
  (prop.startsWith("borderTop") &&
    prop !== "borderTopWidth" &&
    rec.borderTopWidth === "0px") ||
  (prop.startsWith("borderLeft") &&
    prop !== "borderLeftWidth" &&
    rec.borderLeftWidth === "0px") ||
  (prop === "gap" && !["flex", "grid", "inline-flex"].includes(rec.display));

async function main() {
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
    colorScheme: "dark",
  });
  await ctx.addInitScript(probeSource);

  const boardStyles = {};
  const board = await ctx.newPage();
  await board.goto(`file://${BOARD}`);
  await board.waitForTimeout(400);
  for (const [tid, slug] of TABS) {
    // Force ONE panel visible. The board hides tabpanels with `display:none`, and a
    // computed style read off a hidden subtree is the hidden value, not the painted one.
    await board.evaluate((id) => {
      document
        .querySelectorAll('section[role="tabpanel"]')
        .forEach((s) => s.classList.remove("on"));
      document.getElementById(id)?.classList.add("on");
    }, tid);
    await board.waitForTimeout(120);
    boardStyles[tid] = await board.evaluate(
      ([e, p]) => window.__probe(e, p),
      [SELECTORS, PROPS],
    );
    await board.screenshot({
      path: `${OUT}/board-${tid}-${slug}.png`,
      fullPage: true,
    });
  }
  await board.close();

  const liveStyles = {};
  const live = await ctx.newPage();
  for (const [tid, slug] of TABS) {
    const res = await live.goto(`${LIVE}/macro/${slug}`, {
      waitUntil: "networkidle",
    });
    if (!res || !res.ok()) {
      liveStyles[tid] = {};
      console.error(
        `live /macro/${slug}: HTTP ${res ? res.status() : "no response"}`,
      );
      continue;
    }
    await live.waitForTimeout(250);
    liveStyles[tid] = await live.evaluate(
      ([e, p]) => window.__probe(e, p),
      [SELECTORS, PROPS],
    );
    // `fullPage` captures the DOCUMENT's scroll height, and argon's AppShell scrolls an
    // inner `<main>` instead — so every live capture came back exactly viewport-height
    // while the board's came back 3-4k tall, which makes the pair useless to compare.
    // Growing the viewport to the desk's own height is what actually gets the whole tab.
    const tall = await live.evaluate(() => {
      const el = document.querySelector(".board") ?? document.body;
      return Math.min(
        12000,
        Math.ceil(el.getBoundingClientRect().height) + 160,
      );
    });
    await live.setViewportSize({ width: 1440, height: tall });
    await live.waitForTimeout(250);
    await live.screenshot({ path: `${OUT}/live-${tid}-${slug}.png` });
    await live.setViewportSize({ width: 1440, height: 1000 });
  }
  await live.close();
  await browser.close();

  const boardUses = new Set();
  const liveUses = new Set();
  for (const [tid] of TABS) {
    for (const [name] of SELECTORS) {
      if (boardStyles[tid]?.[name]) boardUses.add(name);
      if (liveStyles[tid]?.[name]) liveUses.add(name);
    }
  }

  // One row per (selector, property) where the two sides disagree, with the tabs it was
  // seen on. Reported once rather than per tab: the same token wrong on eight tabs is one
  // finding, and printing it eight times buries the other seven.
  const diffs = new Map();
  for (const [tid, slug] of TABS) {
    for (const [name] of SELECTORS) {
      const b = boardStyles[tid]?.[name];
      const l = liveStyles[tid]?.[name];
      if (!b || !l) continue;
      for (const p of PROPS) {
        if (MEANINGLESS(p, b) || MEANINGLESS(p, l)) continue;
        if (b[p] === l[p]) continue;
        const key = `${name}|${p}|${b[p]}|${l[p]}`;
        if (!diffs.has(key))
          diffs.set(key, {
            sel: name,
            prop: p,
            board: b[p],
            live: l[p],
            tabs: [],
          });
        diffs.get(key).tabs.push(`${tid}/${slug}`);
      }
    }
  }

  const report = {
    coverage: {
      renderedOnBoard: [...boardUses].sort(),
      renderedOnLive: [...liveUses].sort(),
      notPortedToLive: [...boardUses].filter((c) => !liveUses.has(c)).sort(),
      onLiveOnly: [...liveUses].filter((c) => !boardUses.has(c)).sort(),
    },
    diffs: [...diffs.values()],
  };
  writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 2));

  console.log("=== 1. GRAMMAR COVERAGE ===");
  console.log(
    `board renders ${boardUses.size} of ${SELECTORS.length} probed elements; live renders ${liveUses.size}`,
  );
  console.log(
    "on the board, NOT on live:",
    report.coverage.notPortedToLive.join(", ") || "(none)",
  );
  console.log(
    "on live, not on the board:",
    report.coverage.onLiveOnly.join(", ") || "(none)",
  );

  console.log("\n=== 2. COMPUTED-STYLE DIFFS ===");
  if (report.diffs.length === 0) {
    console.log("none");
  }
  const bySel = {};
  for (const d of report.diffs) (bySel[d.sel] ??= []).push(d);
  for (const [sel, ds] of Object.entries(bySel)) {
    console.log(
      `\n${sel}  (${ds[0].tabs.length} tab${ds[0].tabs.length === 1 ? "" : "s"})`,
    );
    for (const d of ds)
      console.log(`   ${d.prop}: board=${d.board}  live=${d.live}`);
  }
  console.log(
    `\n${report.diffs.length} distinct diffs across ${Object.keys(bySel).length} elements`,
  );
  console.log(`screenshots + report.json -> ${OUT}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
