# Defer Dashboard Sparkline OHLCs to Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the 102 server-side sparkline OHLC fetches from the dashboard RSC into a per-card client-side `useEffect` so SSR drops from ~800 ms to ~250 ms and sparklines stream in progressively.

**Architecture:** `TickerCard` is already a Client Component (`"use client"`). Lift the OHLC fetch into it. The existing `sparkline` prop becomes the initial state seed (used by unit tests; production passes `[]` so the effect fetches). Add an `AbortController` cleanup so navigating away kills in-flight requests.

**Tech Stack:** Next.js 16 App Router, React 19 `useState`/`useEffect`/`AbortController`, browser-native `fetch` with the existing `/api/ohlc/:ticker?days=30` rewrite, Vitest + jsdom for unit tests.

---

## Architectural choice (why this approach)

Three alternatives were considered:

| Option | Verdict |
|---|---|
| **A. Lift fetch into `TickerCard` (already client)** | ✅ chosen — smallest diff, no new components, browser HTTP/2 pool handles concurrency naturally |
| B. Centralize in CardGrid (would require making it client) | ❌ CardGrid does server-side sector grouping + size sort; hydrating churns more than it saves |
| C. Intersection Observer (visible-only) | ❌ marginal benefit — users scroll within seconds; complexity not worth it |
| D. SWR / React Query | ❌ overkill for one-shot mount fetch |

## File structure

- **Modify:** `web/components/watchlist/TickerCard.tsx` — add useEffect that fetches OHLC when `sparkline` prop is empty AND ticker is ready. Use `AbortController` for cleanup.
- **Modify:** `web/lib/dashboardData.ts` — drop the `mapWithConcurrency` OHLC fanout. Drop `sparklineConcurrency` param. Return type loses `sparklines` field.
- **Modify:** `web/components/watchlist/CardGrid.tsx` — drop `sparklines` prop. Stop forwarding it to `TickerCard`.
- **Modify:** `web/app/page.tsx` — drop `sparklines` destructure.
- **Modify:** `web/tests/unit/dashboardData.test.ts` — drop sparkline assertions; drop the "limits concurrent sparkline requests" test entirely.
- **Modify:** `web/tests/unit/cardGrid.test.tsx` — drop `sparklines={{}}` from all `<CardGrid>` renders.
- **Keep unchanged:** `web/components/watchlist/Sparkline.tsx`, `SparklineRow.tsx` (already handle `closes=[]` → empty SVG).
- **Keep unchanged:** `web/tests/unit/watchlistUi.test.tsx` — tests pass `sparkline=[…]` non-empty or `scanned_at: null`, both of which short-circuit the new fetch.

---

## Task 1: Lift OHLC fetch into TickerCard

**Files:**
- Modify: `web/components/watchlist/TickerCard.tsx:1-35` (add imports, state, effect)
- Modify: `web/components/watchlist/TickerCard.tsx:104` (pass `closes` to `SparklineRow` instead of `sparkline`)

- [ ] **Step 1: Add `useEffect` import**

```typescript
import { useEffect, useState } from "react";
```

- [ ] **Step 2: Replace the function signature with hooks**

Change:
```typescript
export function TickerCard({ card, sparkline }: Props) {
  const [showNotReady, setShowNotReady] = useState(false);
```

To:
```typescript
export function TickerCard({ card, sparkline = [] }: Props) {
  const [showNotReady, setShowNotReady] = useState(false);
  const [closes, setCloses] = useState<number[]>(sparkline);

  useEffect(() => {
    // Skip when (a) we already have data (tests pre-seed via prop), or
    // (b) the ticker isn't ready (no scan → no point fetching).
    if (closes.length > 0 || !card.scanned_at) return;
    const ac = new AbortController();
    fetch(`/api/ohlc/${card.ticker}?days=30`, {
      cache: "no-store",
      signal: ac.signal,
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`status ${r.status}`))))
      .then((bars: Array<{ close: string | number | null }>) => {
        if (ac.signal.aborted) return;
        setCloses(bars.map((b) => Number(b.close)).reverse());
      })
      .catch(() => {
        // Silent failure — the empty sparkline is an acceptable degraded state.
      });
    return () => ac.abort();
  }, [card.ticker, card.scanned_at, closes.length]);
```

- [ ] **Step 3: Make the Props type tolerate the empty default**

Change `web/components/watchlist/TickerCard.tsx:23`:
```typescript
type Props = { card: Card; sparkline?: number[] };
```

- [ ] **Step 4: Pass `closes` to SparklineRow instead of `sparkline`**

Change `web/components/watchlist/TickerCard.tsx:104-109`:
```typescript
<SparklineRow
  closes={closes}
  ret_1d={toNum(card.returns?.d1)}
  ret_1w={toNum(card.returns?.w1)}
  ret_30d={toNum(card.returns?.d30)}
/>
```

- [ ] **Step 5: Type-check the component**

Run: `cd web && npm run typecheck`
Expected: clean, no errors.

---

## Task 2: Drop the server-side OHLC fanout

**Files:**
- Modify: `web/lib/dashboardData.ts` (drop `mapWithConcurrency`, drop OHLC loop, drop `SparklineMap`)
- Modify: `web/app/page.tsx:22` (drop `sparklines` from destructure)

- [ ] **Step 1: Simplify `loadDashboardData`**

Replace the entire body of `web/lib/dashboardData.ts` with:

```typescript
import { api, type WatchlistResponse } from "./api";

const emptyWatchlist: WatchlistResponse = {
  scanned_at_min: null,
  scanned_at_max: null,
  scheduler_lag_seconds: null,
  queue: {
    total: 0,
    queued: 0,
    running: 0,
    oldest_requested_at: null,
  },
  tickers: [],
};

export async function loadDashboardData(
  qs: URLSearchParams,
): Promise<{ data: WatchlistResponse; apiUnavailable: boolean }> {
  try {
    const data = await api.watchlist(qs);
    return { data, apiUnavailable: false };
  } catch {
    return { data: emptyWatchlist, apiUnavailable: true };
  }
}
```

- [ ] **Step 2: Update the page destructure**

Change `web/app/page.tsx:22`:
```typescript
const { data, apiUnavailable } = await loadDashboardData(qs);
```

- [ ] **Step 3: Update the CardGrid call site**

Change `web/app/page.tsx:65`:
```typescript
<CardGrid data={data} />
```

- [ ] **Step 4: Type-check the page**

Run: `cd web && npm run typecheck`
Expected: clean.

---

## Task 3: Drop the `sparklines` prop from CardGrid

**Files:**
- Modify: `web/components/watchlist/CardGrid.tsx:62-67` (drop prop), `:113` (drop forwarding)

- [ ] **Step 1: Drop the prop from the type and the destructure**

Change `web/components/watchlist/CardGrid.tsx:62-68`:
```typescript
export function CardGrid({ data }: { data: WatchlistResponse }) {
```

- [ ] **Step 2: Drop the forwarding to TickerCard**

Change `web/components/watchlist/CardGrid.tsx:109-115`:
```typescript
{tickers.map((t) => (
  <TickerCard key={t.ticker} card={t} />
))}
```

- [ ] **Step 3: Type-check**

Run: `cd web && npm run typecheck`
Expected: clean.

---

## Task 4: Fix `dashboardData.test.ts`

**Files:**
- Modify: `web/tests/unit/dashboardData.test.ts`

- [ ] **Step 1: Drop the OHLC mock and the second test**

Replace the whole file with:

```typescript
import { describe, expect, it, vi } from "vitest";

import { loadDashboardData } from "@/lib/dashboardData";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  api: {
    watchlist: vi.fn(),
  },
}));

describe("loadDashboardData", () => {
  it("returns an empty dashboard when the API is still starting", async () => {
    vi.mocked(api.watchlist).mockRejectedValueOnce(new Error("ECONNREFUSED"));

    const result = await loadDashboardData(new URLSearchParams());

    expect(result.apiUnavailable).toBe(true);
    expect(result.data.tickers).toEqual([]);
  });

  it("returns the watchlist payload when the API succeeds", async () => {
    const payload = {
      scanned_at_min: null,
      scanned_at_max: null,
      scheduler_lag_seconds: null,
      queue: { total: 0, queued: 0, running: 0, oldest_requested_at: null },
      tickers: [],
    };
    vi.mocked(api.watchlist).mockResolvedValueOnce(payload);

    const result = await loadDashboardData(new URLSearchParams());

    expect(result.apiUnavailable).toBe(false);
    expect(result.data).toEqual(payload);
  });
});
```

- [ ] **Step 2: Run unit tests**

Run: `cd web && npm run test -- tests/unit/dashboardData.test.ts`
Expected: 2 passed.

---

## Task 5: Fix `cardGrid.test.tsx`

**Files:**
- Modify: `web/tests/unit/cardGrid.test.tsx` — 4 call sites that pass `sparklines={{}}`

- [ ] **Step 1: Drop every `sparklines={{}}` prop**

Find every line containing `sparklines={{}}` in `cardGrid.test.tsx` and delete that line.

- [ ] **Step 2: Run unit tests**

Run: `cd web && npm run test -- tests/unit/cardGrid.test.tsx`
Expected: 4 passed (current count).

---

## Task 6: Verify watchlistUi tests still pass

**Files:** none modified

- [ ] **Step 1: Sanity-check the test inputs**

Confirm `web/tests/unit/watchlistUi.test.tsx` always passes EITHER non-empty `sparkline=[...]` (effect short-circuits on `closes.length > 0`) OR `scanned_at: null` (effect short-circuits on `!card.scanned_at`). No fetch stub needed.

- [ ] **Step 2: Run unit tests**

Run: `cd web && npm run test -- tests/unit/watchlistUi.test.tsx`
Expected: all green.

---

## Task 7: Full vitest run

- [ ] **Step 1: Run the full suite**

Run: `cd web && npm run test`
Expected: all green.

- [ ] **Step 2: Lint + typecheck**

Run: `cd web && npm run lint && npm run typecheck`
Expected: clean.

---

## Task 8: Smoke test the bundle locally (against mini API)

- [ ] **Step 1: Build the Next.js bundle**

Run: `cd web && NEXT_PUBLIC_API_BASE_URL=http://100.66.147.98:8400 npm run build`
Expected: build succeeds, `/` appears under "ƒ (Dynamic)" or "○ (Static)".

- [ ] **Step 2: Confirm the deferred fetch wiring**

Run: `grep -A2 "api/ohlc/" web/components/watchlist/TickerCard.tsx`
Expected: shows the new `fetch(\`/api/ohlc/...\`)` call in the useEffect.

---

## Acceptance criteria

- `cd web && npm run test` — all green
- `cd web && npm run typecheck` — clean
- `cd web && npm run lint` — clean
- Dashboard SSR end-to-end ≤ 400 ms in mini smoke test (post-deploy) — was 800 ms
- All 102 sparklines progressively populate within ~1.5 s of hydration in browser
- `/api/ohlc/*` traffic shape moves from server-side burst (RSC) to client-side burst (browser), same total qps
