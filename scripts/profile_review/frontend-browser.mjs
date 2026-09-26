import assert from "node:assert/strict";
import { chromium } from "../../web/node_modules/playwright/index.mjs";
import fs from "node:fs";
const output = new URL("../../output/profile-review/frontend/", import.meta.url);
const screenshots = new URL("../../output/playwright/profile-review/", import.meta.url);
fs.mkdirSync(screenshots, { recursive: true });
const logFile = new URL("stub-requests.jsonl", output);
const before = fs.existsSync(logFile) ? fs.readFileSync(logFile, "utf8").length : 0;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const events = [];
  page.on("request", r => events.push({ kind: "request", url: r.url(), method: r.method(), headers: r.headers(), fixture: true }));
  page.on("pageerror", e => events.push({ kind: "pageerror", message: e.message, fixture: true }));
  await page.goto("http://127.0.0.1:3317/stock/MOCKPROF/trade-plan", { waitUntil: "networkidle" });
  await page.waitForTimeout(5000);
  const links = await page.locator('a[href^="/stock/MOCKPROF/"]').evaluateAll(nodes => nodes.map(n => ({ href: n.getAttribute("href"), text: n.textContent })));
  await page.screenshot({ path: new URL("mock-stock-prefetch.png", screenshots).pathname, fullPage: true });
  fs.writeFileSync(new URL("browser-events.json", output), JSON.stringify({ fixture: true, noNavigationClicks: true, links, events }, null, 2));
  const prefetched = new Set(events.filter(e => e.kind === "request" && e.headers["next-router-prefetch"] === "1" && new URL(e.url).pathname.startsWith("/stock/MOCKPROF/")).map(e => new URL(e.url).pathname));
  assert.equal(prefetched.size, 7, "all seven unvisited stock tabs must be prefetched");
  const rows = fs.readFileSync(logFile, "utf8").slice(before).trim().split("\n").filter(Boolean).map(JSON.parse);
  const counts = {};
  for (const r of rows) counts[r.url] = (counts[r.url] ?? 0) + 1;
  fs.writeFileSync(new URL("stub-counts.json", output), JSON.stringify({fixture:true, requests:rows.length, counts}, null, 2));
  console.log(JSON.stringify({ fixture: true, noNavigationClicks: true, visibleStockLinks: links.length, rscRequests: events.filter(e => e.kind === "request" && e.headers.rsc === "1").map(e => ({ url: e.url, prefetch: e.headers["next-router-prefetch"] })) }, null, 2));
} finally { await browser.close(); }
