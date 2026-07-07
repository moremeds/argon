"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Coins,
  Crosshair,
  LayoutDashboard,
  Radar,
  ScanLine,
  TrendingUp,
  Wallet,
} from "lucide-react";
import { HealthPanel } from "./HealthPanel";
import styles from "./AppShell.module.css";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/scanner", label: "Scanner", icon: ScanLine },
  { href: "/positioning", label: "Positioning", icon: Crosshair },
  { href: "/cockpit/SPY", label: "Cockpit", icon: Radar },
  { href: "/regime", label: "Regime", icon: Activity },
  { href: "/positions", label: "Positions", icon: Wallet },
  { href: "/gold", label: "Gold", icon: Coins },
  { href: "/rates", label: "Rates", icon: TrendingUp },
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
