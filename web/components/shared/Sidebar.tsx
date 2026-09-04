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
  Zap,
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
//
// Flash is second, immediately under Dashboard, because that is where the
// operator put it: the daily brief is read before anything is scanned. No
// entry carries a `sub` any more — the nav lists rooms, and a room that has to
// explain itself in the nav is a nav that has stopped being scannable. The
// field and its rendering branch stay for the day one earns a subtitle.
type NavEntry = {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  /** Optional second line under the label. No entry uses one today. */
  sub?: string;
};

export const NAV: NavEntry[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/flash", label: "Flash", icon: Zap },
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
        {NAV.map((entry) => {
          const { href, label, icon: Icon, sub } = entry;
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={[styles.link, active ? styles.linkActive : ""].join(
                " ",
              )}
            >
              <Icon size={16} strokeWidth={1.5} />
              {sub ? (
                <span className={styles.linkStack}>
                  {label}
                  <span className={styles.linkSub}>{sub}</span>
                </span>
              ) : (
                label
              )}
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
