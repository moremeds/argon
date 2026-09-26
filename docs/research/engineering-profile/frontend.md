# Frontend current-code reproduction

Base `9f094d0cb5b8d20f6103bae1bab2cea25c69c358`, branch `chore/profile-review`. No application refactor, production traffic, database access, provider calls, commit, push or deployment. These harnesses exercise the unchanged components and a production-mode Next build against an explicitly mocked local service. Requested Astra medium; actual serving model/effort not independently observable.

## Verdict

| Check | Observed result | Boundary |
|---|---|---|
| ScanAll deadline | After **602,000 ms simulated** and 301 running-job reads, button still says `scanning 0/1…` | Fake timers, not ten minutes of actual runtime |
| ScanAll failed status read | One rejected GET produces `✓ scanned 1` and a router refresh | Mock transport rejection; no job actually ran |
| LiveSpots overlap | At **5,000 ms simulated**, 3 requests remain unresolved simultaneously | Deferred mocked requests; demonstrates missing in-flight guard |
| Stock prefetch | **7 distinct unvisited stock tabs** emit `next-router-prefetch: 1` RSC requests without a navigation click | Real Chromium + production Next 16.2.6 webpack build, mocked backend |
| Backend requests during fixture visit | **16** local requests, including **5 full stock-report GETs**, plus 1 each for skew, volatility series, history, positioning and trade insights | Not actual production traffic, bytes, latency or provider demand |

The first three checks deliberately assert existing defects. Their passing result means the bug was reproduced, not fixed. Existing `web/tests/unit/watchlistUi.test.tsx` only covers scan-all confirmation/enqueue; this harness adds lifecycle evidence without changing those tests or app code.

Current component mechanisms: `ScanAllButton.tsx` recreates its deadline when the `pendingIds` effect dependency changes; a newly allocated pending array changes on every successful poll. Null results from failed reads are filtered out as though completed. `LiveSpotsProvider.tsx` schedules a new read every 2.5 seconds before previous reads settle. Stock `TabBar.tsx` explicitly sets `prefetch` on all links; installed `next/dist/client/app-dir/link.d.ts:95-106` documents that `true` prefetches the full route/data in production.

## Evidence

- `output/profile-review/frontend/component-tests.log`: all 3 baseline proof tests pass under installed Vitest 4.1.6.
- `output/profile-review/frontend/build.log`: first build failed because Turbopack rejected external symlinked node_modules. No dependencies were copied or installed.
- `output/profile-review/frontend/build-webpack.log`: supported `next build --webpack` fallback succeeded, including TypeScript; same application sources/config. This proves webpack production behavior, not successful default Turbopack build in this worktree layout.
- `output/profile-review/frontend/browser-events.json`: complete browser request headers, 8 stock links, `noNavigationClicks: true`.
- `output/profile-review/frontend/browser-summary.json`: RSC requests and prefetch markers. Also contains sidebar prefetch traffic; do not attribute those paths to the stock tab bar.
- `output/profile-review/frontend/stub-counts.json`: last capture's 16 requests only. `stub-requests.jsonl` is append-only and contains **two captures**; do not sum it as one visit.
- `output/playwright/profile-review/mock-stock-prefetch.png`: reviewed rendered MOCKPROF page with null price/IV and all eight tabs visible.
- `output/profile-review/frontend/processes.txt`, `cleanup.txt`: owned backend PID 13704 / Next PID 14166 were stopped; no listeners remained on 8417/3317.

The fixture returns a minimal stock report for synthetic `MOCKPROF`, null market values, and empty live spots. Every optional endpoint returns clearly labeled 503 mock unavailability. This is enough to render the trade-plan page and prove unsolicited fetch paths; it does not establish full-panel behavior or successful backend work. No clicks trigger analysis, jobs or orders. Both browser captures independently yielded 5 stock-report reads and the same 16-request total; that is fixture repeatability, not a performance benchmark. There is no before/after implementation comparison.

## Reproduce

Run from this worktree's project root with its existing dependency symlink:

```sh
rtk proxy ./web/node_modules/.bin/vitest run --config scripts/profile_review/frontend.config.mts --reporter=verbose
```

The external Vitest config aliases only installed dependencies and the worktree web directory; cache output goes to `output/profile-review/frontend/vite-cache`. Initial harness setup needed an explicit `next/navigation` alias so the mock and component resolve the same module from outside `web/`; no product code change was needed.

For browser reproduction, use separate terminals. First build (serialize with other CPU measurements):

```sh
cd web
NEXT_TELEMETRY_DISABLED=1 NEXT_INTERNAL_API_BASE=http://127.0.0.1:8417 ./node_modules/.bin/next build --webpack
```

From project root start the mock:

```sh
rtk proxy node scripts/profile_review/frontend-stub.mjs
```

From `web/` start the isolated Next instance:

```sh
NEXT_TELEMETRY_DISABLED=1 NEXT_INTERNAL_API_BASE=http://127.0.0.1:8417 ./node_modules/.bin/next start --hostname 127.0.0.1 --port 3317
```

From project root run the browser assertion:

```sh
rtk proxy node scripts/profile_review/frontend-browser.mjs
```

The script asserts exactly seven distinct unvisited stock tab prefetch paths and always closes Chromium. Stop only these two owned server processes afterward. Their listeners bind localhost, and existing stacks are not restarted. The mock uses no database or network clients. The build generated only ignored Next artifacts; `git diff --name-only` remained empty after execution.

## Still unmeasured

Production payload sizes, report serialization/copy CPU, actual response latency, real concurrent users, impact of setting `prefetch={false}`, and any backend pressure from real job counts. No claimed speedup. The narrow next implementation candidates remain the confirmed scan polling corrections and stock prefetch setting, subject to the lead's Task 2 review gate.

Commit: none. Task complete; awaiting lead gate.
