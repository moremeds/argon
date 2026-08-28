"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Crosshair,
  LayoutDashboard,
  Radar,
  ScanLine,
  Wallet,
  Globe,
  Telescope,
  FileText,
} from "lucide-react";
import { HealthPanel } from "./HealthPanel";
import styles from "./AppShell.module.css";

// Exported so the route tree can be asserted in a test: a nav that keeps a second door to
// the same room, labelled as a different room, is how a folded-in surface stays
// half-folded. Two foldings are asserted that way — `/radar` + `/chains` into
// `/fundamentals` (`tests/unit/fundamentalsIndex.test.tsx`), and `/gold` + `/rates` into
// `/macro` below.
//
// Gold, Rates and Macro were three peers until the macro desk had somewhere to put the
// first two. They collapse here — the last step of the port plan's P6, and deliberately
// the LAST one: §8 forbids shipping a link to a route that does not exist, and the mirror
// of that rule is that a peer entry may only be removed once its destination tab is
// registered. `/gold` and `/rates` both 308 into the desk now, so the two removed entries
// would only have been links to redirects. `startsWith` (below) already lights Macro for
// every `/macro/*` tab.
//
// One consequence, accepted rather than overlooked: `/gold/replay/<date>` is kept and now
// matches no entry, so it highlights nothing. §6 named that as the choice — a deliberately
// unlisted deep surface — and the desk's own gold tab carries the same replay through
// `?as_of=`, so nothing is unreachable, only unlisted.
export const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/scanner", label: "Scanner", icon: ScanLine },
  { href: "/positioning", label: "Positioning", icon: Crosshair },
  { href: "/cockpit/SPY", label: "Cockpit", icon: Radar },
  { href: "/regime", label: "Regime", icon: Activity },
  { href: "/positions", label: "Positions", icon: Wallet },
  { href: "/macro", label: "Macro", icon: Globe },
  { href: "/fundamentals", label: "Fundamentals", icon: Telescope },
  { href: "/reports", label: "Reports", icon: FileText },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className={styles.sidebar}>
      <div className={styles.brand}>
        <span className={styles.brandMark} />
        <span className={styles.brandText}>ARGON</span>
      </div>

      <nav className={styles.nav}>
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={[styles.link, active ? styles.linkActive : ""].join(
                " ",
              )}
            >
              <Icon size={16} strokeWidth={1.5} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className={styles.health}>
        <HealthPanel />
      </div>
    </aside>
  );
}
