// MCP parity check (agent-mcp acceptance 2): technicals_scan vs the rendered
// Technicals page, for real tickers on a running stack.
//
// Parity is structural: the chart and the tool call the same technicalsOverlays
// (lib/technicals/overlays.ts). This script checks the other half, empirically:
//   1. same inputs: the page's own /technicals + /technicals/live response
//      bodies equal the tool's fetched payloads, byte for byte after JSON parse;
//   2. DOM spot check: the VP stats panel (the only DOM-readable VP surface;
//      EMA/chanlun are canvas) shows exactly the tool's vp_* values.
//
// Reproduce (API on API_BASE, `next start` of this checkout on WEB_BASE):
//   npx esbuild scripts/mcp-parity.ts --bundle --platform=node --format=esm \
//     --alias:@=$PWD --external:playwright --external:@playwright/test \
//     --external:pg --outfile=.mcp-dist/mcp-parity.mjs
//   API_BASE=http://127.0.0.1:8499 WEB_BASE=http://127.0.0.1:3091 \
//     node .mcp-dist/mcp-parity.mjs AAPL NVDA SPY
// Writes ../output/mcp-parity/<YYYY-MM-DD>.json and exits 1 on any mismatch.
import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "@playwright/test";
import { tool } from "@/mcp/tools/technicals_scan";
import type { Columnar, ToolCtx } from "@/mcp/types";

const API = process.env.API_BASE ?? "http://127.0.0.1:8499";
const WEB = process.env.WEB_BASE ?? "http://127.0.0.1:3091";
const tickers = process.argv.slice(2).length
  ? process.argv.slice(2)
  : ["AAPL", "NVDA", "SPY"];
const FIELDS = [
  "eod_as_of",
  "live_captured_at",
  "ema20",
  "chanlun_points_n",
  "chanlun_last_point",
  "vp_poc",
  "vp_vah",
  "vp_val",
  "vp_nearest_s",
  "vp_nearest_r",
  "vp_bias",
];

const fetched = new Map<string, unknown>();
const ctx = {
  apiGet: async (path: string) => {
    const r = await fetch(`${API}/api${path}`);
    if (!r.ok) throw new Error(`${path} -> ${r.status}`);
    const body = await r.json();
    fetched.set(path, body);
    return body;
  },
  // ponytail: one call per run, so the cache key never matters here.
  db: { query: async () => ({ rows: [{ k: "parity" }] }) },
  tokenLabel: "parity",
} as unknown as ToolCtx;

const out = (await tool.handler({ tickers, fields: FIELDS }, ctx)) as Columnar;
const toolRows = new Map(
  out.rows.map((r) => [
    r[0] as string,
    Object.fromEntries(out.columns.map((c, i) => [c, r[i]])),
  ]),
);

// The page's own display rule: v == null ? "–" : v.toFixed(2) (VolumeProfileStatsPanel).
const f = (v: unknown) => (v == null ? "–" : (v as number).toFixed(2));
const browser = await chromium.launch();
const report: Record<string, unknown> = {};
let ok = true;
for (const t of tickers) {
  const page = await browser.newPage();
  await page.addInitScript(() => {
    localStorage.setItem("technicals:volumeProfile", "1");
    localStorage.setItem("technicals:chanlun", "1");
    localStorage.setItem("technicals:view", "chart");
  });
  const bodies = new Map<string, unknown>();
  page.on("response", async (res) => {
    const m = res.url().match(/\/api(\/stock\/[^/]+\/technicals(?:\/live)?)$/);
    if (m && res.ok()) bodies.set(m[1], await res.json().catch(() => null));
  });
  await page.goto(`${WEB}/stock/${t}/technicals`);
  const panel = page.getByTestId("volume-profile-stats");
  await panel.waitFor({ timeout: 30_000 });
  const text = await panel.innerText();
  const read = (label: string) =>
    text.match(new RegExp(`${label}\\s*\\n\\s*([^\\n]+)`, "i"))?.[1]?.trim() ??
    null;
  const ui = {
    poc: read("POC"),
    vah: read("VAH"),
    val: read("VAL"),
    nearest_r: read("Nearest R"),
    nearest_s: read("Nearest S"),
    bias: read("Bias"),
  };
  const row = toolRows.get(t)!;
  const toolShown = {
    poc: f(row.vp_poc),
    vah: f(row.vp_vah),
    val: f(row.vp_val),
    nearest_r: f(row.vp_nearest_r),
    nearest_s: f(row.vp_nearest_s),
    bias: row.vp_bias as string,
  };
  const eodPath = `/stock/${t}/technicals`;
  const livePath = `/stock/${t}/technicals/live`;
  const sameEod =
    JSON.stringify(bodies.get(eodPath)) ===
    JSON.stringify(fetched.get(eodPath));
  // The page polls /live every 25 s; any captured body suffices — the same row is served until the next capture.
  const sameLive =
    JSON.stringify(bodies.get(livePath)) ===
    JSON.stringify(fetched.get(livePath));
  const vpMatch = JSON.stringify(ui) === JSON.stringify(toolShown);
  ok &&= sameEod && sameLive && vpMatch;
  report[t] = {
    sameEodPayload: sameEod,
    sameLivePayload: sameLive,
    vpMatch,
    ui,
    tool: toolShown,
    toolRow: row,
  };
  await page.close();
}
await browser.close();
const day = new Date().toISOString().slice(0, 10);
mkdirSync("../output/mcp-parity", { recursive: true });
writeFileSync(
  `../output/mcp-parity/${day}.json`,
  JSON.stringify({ api: API, web: WEB, as_of: out.as_of, ok, report }, null, 2),
);
console.log(
  JSON.stringify(
    {
      ok,
      summary: Object.fromEntries(
        Object.entries(report).map(([k, v]) => [
          k,
          { ...(v as object), toolRow: undefined },
        ]),
      ),
    },
    null,
    1,
  ),
);
process.exit(ok ? 0 : 1);
