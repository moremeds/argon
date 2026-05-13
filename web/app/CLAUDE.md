# web/app — Next.js App Router

## Routes

```
app/
├── layout.tsx            # RootLayout: Sidebar + <main>; loads fonts + globals.css
├── page.tsx              # / — Dashboard / watchlist landing (RSC, force-dynamic)
├── stock/[ticker]/       # Per-ticker detail page
│   ├── layout.tsx        # Header + TabBar
│   └── page.tsx          # Tab router (Tables | Vol | Flow | TradePlan | Market Structure)
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
