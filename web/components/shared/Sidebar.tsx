"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Radar, ScanLine } from "lucide-react";
import { HealthPanel } from "./HealthPanel";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/scanner", label: "Scanner", icon: ScanLine },
  { href: "/cockpit/SPY", label: "Cockpit", icon: Radar },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside
      style={{
        width: 220,
        flexShrink: 0,
        background: "var(--bg-panel)",
        borderRight: "1px solid var(--border-dim)",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflowY: "auto",
      }}
    >
      <div
        style={{
          padding: "20px 16px",
          borderBottom: "1px solid var(--border-dim)",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <span
          style={{
            width: 14,
            height: 14,
            background: "var(--text-primary)",
            display: "inline-block",
          }}
        />
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontWeight: 700,
            letterSpacing: 2,
            fontSize: 14,
            color: "var(--text-primary)",
          }}
        >
          ARGON
        </span>
      </div>

      <nav style={{ padding: "8px 0", flex: 1 }}>
        {NAV.map(({ href, label, icon: Icon }) => {
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "10px 16px",
                fontFamily: "var(--font-mono)",
                fontSize: 13,
                color: active ? "var(--text-primary)" : "var(--text-muted)",
                background: active
                  ? "var(--bg-active, rgba(255,255,255,0.04))"
                  : "transparent",
                borderLeft: active
                  ? "2px solid var(--text-primary)"
                  : "2px solid transparent",
                textDecoration: "none",
              }}
            >
              <Icon size={16} strokeWidth={1.5} />
              {label}
            </Link>
          );
        })}
      </nav>

      <HealthPanel />
    </aside>
  );
}
