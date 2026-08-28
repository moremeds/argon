import { Suspense } from "react";

import { MacroTabBar } from "@/components/macro/MacroTabBar";

import "./board.css";

/**
 * The macro desk shell.
 *
 * The tab bar lives here rather than inside each tab so that switching tabs does not
 * re-render it, matching `app/stock/[ticker]/layout.tsx:42`. No padding is added around
 * `children`: each tab (and today's `app/macro/page.tsx`, which this layout now wraps)
 * owns its own gutter, which is how every other page under `AppShell` works.
 *
 * A throw from THIS file is caught by `app/macro/error.tsx`, one level up — a segment's
 * own `error.tsx` does not catch throws from that segment's layout.
 *
 * `board.css` is imported here because it is the desk's shared grammar, ported class for
 * class from the binding spec (`docs/superpowers/specs/2026-08-27-macro-desk-board.html`).
 * Everything in it is scoped under `.board`, so importing it desk-wide cannot restyle the
 * gold and rates tabs that also live under this layout and carry their own table chrome.
 *
 * The `<Suspense>` is not decoration. `MacroTabBar` reads `useSearchParams()` so it can
 * carry `?as_of=` across tab switches, and a client component that reads the search params
 * must sit under a boundary or it opts its whole route out of static rendering. Every
 * route on this desk is already `force-dynamic`, so the boundary changes nothing today —
 * it is here so that a future statically-rendered route added under `/macro` fails on its
 * own merits rather than being silently downgraded by the shell.
 */
export default function MacroLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div style={{ minHeight: "100%", background: "var(--bg-base)" }}>
      <Suspense fallback={null}>
        <MacroTabBar />
      </Suspense>
      {children}
    </div>
  );
}
