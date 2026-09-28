// Isolated mock backend: null market values, no providers or database access.
import http from "node:http";
import fs from "node:fs";
const output = new URL("../../output/profile-review/frontend/", import.meta.url);
fs.mkdirSync(output, { recursive: true });
const server = http.createServer((req, res) => {
  fs.appendFileSync(new URL("stub-requests.jsonl", output), JSON.stringify({ at: new Date().toISOString(), method: req.method, url: req.url, fixture: true }) + "\n");
  res.setHeader("Content-Type", "application/json");
  if (req.url === "/api/stock/MOCKPROF") {
    res.end(JSON.stringify({ ticker: "MOCKPROF", market_structure: { spot: null }, volatility: { iv: null }, flow: { top_alerts: [] }, max_pain_rows: [], generated_at: null, setup: null }));
  } else if (req.url === "/api/watchlist/spots") {
    res.end(JSON.stringify({ spots: [] }));
  } else {
    res.statusCode = 503;
    res.end(JSON.stringify({ detail: "PROFILE MOCK: this optional panel endpoint is deliberately unavailable; no production data" }));
  }
});
server.listen(8417, "127.0.0.1", () => console.log(`PROFILE MOCK backend pid=${process.pid} port=8417`));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.close(() => process.exit(0)));
