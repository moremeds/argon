/** Full-canvas artifact conformance probe. Run with the dev server on :3002. */
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const BOARD =
  process.env.BOARD_HTML ??
  resolve("../docs/superpowers/specs/2026-08-27-macro-desk-board.html");
const LIVE = process.env.LIVE_BASE ?? "http://127.0.0.1:3002";
const OUT = resolve("../output/playwright/board-compare");
const TABS = [
  ["t0", "overview"],
  ["t1", "fed"],
  ["t2", "rates"],
  ["t3", "inflation"],
  ["t4", "usd"],
  ["t5", "gold"],
  ["t6", "energy"],
  ["t7", "factors"],
  ["t8", "notes"],
];

const PROPS = [
  "display",
  "position",
  "fontFamily",
  "fontSize",
  "fontWeight",
  "letterSpacing",
  "lineHeight",
  "textTransform",
  "color",
  "backgroundColor",
  "borderTopWidth",
  "borderTopColor",
  "borderLeftWidth",
  "borderLeftColor",
  "borderTopLeftRadius",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "gap",
  "opacity",
];

const SELECTORS = [
  ["appbar", ".appbar"],
  ["appbar-inner", ".appbar-inner"],
  ["intro", ".intro"],
  ["legend-strip", ".legend-strip"],
  ["pm-question", ".pmq .q"],
  ["tabbar", ".tabbar"],
  ["tab", ".tabs > .tab"],
  ["main-wrap", "main.wrap"],
  ["footer", "footer"],
  ["section-title", ".sec-title h2"],
  ["section-standfirst", "p.sec-sub"],
  ["zone", ".zone"],
  ["panel", ".panel"],
  ["panel-heading", ".panel > .panel-h > h3"],
  ["read-rail", ".read"],
  ["provenance", ".prov"],
  ["tag-real", ".tag.real"],
  ["tag-computed", ".tag.comp"],
  ["tag-planned", ".tag.plan"],
  ["tag-question", ".tag.q"],
  ["state-pill", ".state"],
  ["grid-2up", ".grid.g2"],
  ["grid-3up", ".grid.g3"],
  ["table", "table"],
  ["table-header", "th"],
  ["table-cell", "td"],
  ["numeric-cell", "td.num"],
  ["big-number", ".big"],
  ["refusal", ".note-refuse"],
  ["arith-term", ".arith .term"],
  ["arith-result", ".arith .res"],
  ["chain-node", ".node"],
  ["confidence", ".conf"],
  ["meter", ".meter"],
  ["contradiction", ".contra"],
  ["chart", ".chart"],
  ["caption", ".cap"],
  ["legend", ".lgd"],
  ["ghost", ".ghost"],
  ["chip", ".chip"],
  ["meeting", ".meet"],
  ["probability-bar", ".pbar"],
  ["direction", ".dir"],
  ["tight-list-item", "ul.tight li"],
];

async function capture(page, rootSelector) {
  return page.evaluate(
    ({ rootSelector, selectors, props }) => {
      const root = document.querySelector(rootSelector);
      if (!root) throw new Error(`missing comparison root ${rootSelector}`);
      const rootRect = root.getBoundingClientRect();
      const normalizeColor = (value) => {
        const m = value.match(
          /^color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)$/,
        );
        if (!m) return value;
        const channel = (x) => Math.round(Number(x) * 255);
        const alpha = m[4] === undefined ? 1 : Number(m[4]);
        return alpha === 1
          ? `rgb(${channel(m[1])}, ${channel(m[2])}, ${channel(m[3])})`
          : `rgba(${channel(m[1])}, ${channel(m[2])}, ${channel(m[3])}, ${Math.round(alpha * 100) / 100})`;
      };
      const result = {};
      for (const [name, selector] of selectors) {
        const nodes = [...root.querySelectorAll(selector)].filter(
          (node) => node.getClientRects().length > 0,
        );
        result[name] = nodes.map((node) => {
          const rect = node.getBoundingClientRect();
          const style = getComputedStyle(node);
          const computed = {};
          for (const prop of props) computed[prop] = normalizeColor(style[prop]);
          computed.fontFamily = (computed.fontFamily ?? "")
            .split(",")[0]
            .trim()
            .replace(/^"|"$/g, "");
          return {
            text: (node.textContent ?? "").replace(/\s+/g, " ").trim(),
            rect: {
              x: Math.round((rect.left - rootRect.left) * 100) / 100,
              y: Math.round((rect.top - rootRect.top) * 100) / 100,
              width: Math.round(rect.width * 100) / 100,
              height: Math.round(rect.height * 100) / 100,
            },
            computed,
          };
        });
      }
      return {
        root: {
          x: rootRect.left,
          y: rootRect.top,
          width: rootRect.width,
          height: rootRect.height,
        },
        selectors: result,
      };
    },
    { rootSelector, selectors: SELECTORS, props: PROPS },
  );
}

function compare(board, live, tab) {
  const differences = [];
  const isMeaningfulStyle = (property, item) => {
    if (property === "gap" && !["flex", "inline-flex", "grid", "inline-grid"].includes(item.computed.display)) {
      return false;
    }
    if (property === "borderTopColor" && item.computed.borderTopWidth === "0px") {
      return false;
    }
    if (property === "borderLeftColor" && item.computed.borderLeftWidth === "0px") {
      return false;
    }
    return true;
  };
  for (const [name] of SELECTORS) {
    const expected = board.selectors[name] ?? [];
    const actual = live.selectors[name] ?? [];
    if (expected.length !== actual.length) {
      differences.push({ tab, selector: name, kind: "count", expected: expected.length, actual: actual.length });
    }
    for (let index = 0; index < Math.min(expected.length, actual.length); index += 1) {
      for (const prop of PROPS) {
        if (!isMeaningfulStyle(prop, expected[index]) && !isMeaningfulStyle(prop, actual[index])) continue;
        if (expected[index].computed[prop] !== actual[index].computed[prop]) {
          differences.push({
            tab,
            selector: name,
            index,
            kind: "style",
            property: prop,
            expected: expected[index].computed[prop],
            actual: actual[index].computed[prop],
          });
        }
      }
      for (const prop of ["x", "y", "width", "height"]) {
        if (Math.abs(expected[index].rect[prop] - actual[index].rect[prop]) > 0.5) {
          differences.push({
            tab,
            selector: name,
            index,
            kind: "geometry",
            property: prop,
            expected: expected[index].rect[prop],
            actual: actual[index].rect[prop],
          });
        }
      }
    }
  }
  return differences;
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const boardContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
    colorScheme: "dark",
  });
  const liveContext = await browser.newContext({
    viewport: { width: 1660, height: 1000 },
    deviceScaleFactor: 1,
    colorScheme: "dark",
  });
  const boardPage = await boardContext.newPage();
  const livePage = await liveContext.newPage();
  await boardPage.goto(`file://${BOARD}`);
  // Product override approved after the artifact was signed off: retain the
  // 1440px canvas, but use the Regime page's 32px gutters instead of centering a
  // 1240px wrap. Apply the same transform to the immutable reference at compare
  // time so component geometry remains a real gate rather than 4,000 known-noise
  // width deltas.
  await boardPage.addStyleTag({
    content: ".wrap{width:100%!important;max-width:none!important;margin:0!important;padding-left:32px!important;padding-right:32px!important}",
  });

  const report = { reference: BOARD, live: LIVE, viewport: { board: [1440, 1000], app: [1660, 1000], sidebar: 220, gutterOverride: 32 }, tabs: {}, differences: [] };
  for (const [tabId, slug] of TABS) {
    await boardPage.evaluate((id) => {
      const target = document.querySelector(`.tab[data-t="${id}"]`);
      if (!(target instanceof HTMLElement)) throw new Error(`missing reference tab ${id}`);
      target.click();
    }, tabId);
    const boardCapture = await capture(boardPage, "body");
    await boardPage.screenshot({ path: `${OUT}/board-${tabId}-${slug}.png`, fullPage: true });

    const response = await livePage.goto(`${LIVE}/macro/${slug}`, { waitUntil: "networkidle" });
    if (!response?.ok()) throw new Error(`/macro/${slug} returned ${response?.status()}`);
    const liveCapture = await capture(livePage, ".macro-desk-shell");
    const canvasHeight = Math.min(12000, Math.ceil(liveCapture.root.height));
    await livePage.setViewportSize({ width: 1660, height: canvasHeight });
    await livePage.screenshot({
      path: `${OUT}/live-${tabId}-${slug}.png`,
      clip: { x: 220, y: 0, width: 1440, height: canvasHeight },
    });
    await livePage.setViewportSize({ width: 1660, height: 1000 });

    const differences = compare(boardCapture, liveCapture, `${tabId}/${slug}`);
    report.tabs[tabId] = { slug, board: boardCapture, live: liveCapture, differenceCount: differences.length };
    report.differences.push(...differences);
  }

  await browser.close();
  writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 2));
  const counts = report.differences.reduce((acc, item) => {
    acc[item.kind] = (acc[item.kind] ?? 0) + 1;
    return acc;
  }, {});
  console.log(JSON.stringify({ tabs: TABS.length, differences: report.differences.length, byKind: counts, output: OUT }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
