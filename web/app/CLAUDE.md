# web/app — Next.js App Router

## Routes

```
app/
├── layout.tsx            # RootLayout: Sidebar + <main>; loads fonts + globals.css
├── page.tsx              # / — Dashboard / watchlist landing (RSC, force-dynamic)
├── stock/[ticker]/       # Per-ticker detail page
│   ├── layout.tsx        # Header + TabBar
│   ├── page.tsx          # redirect() → /stock/<T>/market-structure
│   └── [tab]/page.tsx    # Tab router: market-structure | volatility | skew | flow | trade-insights | trade-plan (trade-plan renders the AI FrameworkTab; the deterministic TradePlanTab is retired)
├── scanner/              # /scanner — detector candidates + discovery (force-dynamic)
├── regime/[[...tab]]/    # /regime — CRI, VCG, GEX, Canary, GRG, MarketTide, MacroShortVol subtabs
├── macro/                # /macro — the macro desk (Gold + Rates + Macro, merged)
│   ├── layout.tsx        # <MacroTabBar/>, registry-driven; + error.tsx above it
│   ├── page.tsx          # /macro — the four domain cards (P5 flips this to a redirect)
│   ├── [tab]/page.tsx    # Tab router: fed | rates | inflation | usd | gold | notes
│   └── [tab]/goldTab.tsx # tab 05's server component — co-located, not a route
├── gold/                 # NO page.tsx: /gold 308s to /macro/gold (next.config.mjs)
│   └── replay/[date]/    # /gold/replay/<YYYY-MM-DD> — KEPT, deliberately unlisted in the sidebar
├── vrp/                  # /vrp — VRP research panels
├── cockpit/[ticker]/     # /cockpit/<SPX|SPY|QQQ|IWM> — index dealer state research
├── watchlist/            # /watchlist (currently a thin variant of /)
└── admin/                # /admin — health + scheduler controls
```

## Rules

- **Pages are RSC.** Push `"use client"` to interactive leaves (`VolatilityTabClient`, `RescanButton`, filter chips).
- **`force-dynamic`** is required on any page that varies by `searchParams` — otherwise Next.js caches the unfiltered payload at the route level and filter clicks return stale data.
- **Server-side fetch via `api.*`** (from `lib/api.ts`). Don't import psycopg here — backend traffic only through FastAPI.
- **Tabs receive server-fetched data as props.** If a tab needs to refetch (e.g., after a backfill), it becomes a Client Component that does its own fetch with a polling interval. See `VolatilityTabClient`.
- **Loading UI** via `loading.tsx` next to the page (App Router convention) — see `app/watchlist/loading.tsx`.
- **Single sidebar** mounted in `RootLayout`. Don't add a second one in nested layouts.
- **The macro desk's tab set is a REGISTRY, not a schedule.** `components/macro/tabs.ts` feeds both the route guard (`notFound()` on an unregistered slug) and the tab bar, so a tab becomes reachable in the same commit that makes it real and the bar can never link to a 404. Add the `VALID_TABS` entry and its `TAB_CONTENT` value together — `MacroTabSlug` is derived from the array, so half a registration is a compile error.
- **`replayClock` on a tab entry must name what its endpoint actually keys on.** `/api/macro/*` resolves an instant (selecting on `as_of`), `/api/rates/snapshot` selects on `computed_at`, `/api/gold/replay` matches `obs_date` **exactly** — the first two answer "what did the desk know at T" and are both `instant`; gold is `obs_date` and is not a point-in-time replay at all. The field has no default so it cannot be inherited, but nothing type-checks it against the router: that one is a review item.
- **A redirect ships with its destination.** `/rates` and `/gold` both 308 into the desk; neither redirect could land before the tab it points at was registered, and `source` is the exact path so `/gold/replay/<date>` is not swallowed. Same rule for the sidebar: a peer entry is only removed once its destination tab exists.
