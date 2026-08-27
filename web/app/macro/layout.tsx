import { MacroTabBar } from "@/components/macro/MacroTabBar";

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
 */
export default function MacroLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div style={{ minHeight: "100%", background: "var(--bg-base)" }}>
      <MacroTabBar />
      {children}
    </div>
  );
}
