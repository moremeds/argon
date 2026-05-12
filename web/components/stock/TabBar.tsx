"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  ["market-structure", "Market Structure"],
  ["volatility", "Volatility"],
  ["flow", "Flow"],
  ["vrp", "VRP"],
  ["trade-plan", "Trade Plan"],
  ["tables", "Tables"],
] as const;

export function TabBar({ ticker }: { ticker: string }) {
  const path = usePathname();
  return (
    <nav
      style={{
        display: "flex",
        gap: 0,
        borderBottom: "1px solid var(--border-dim)",
        padding: "0 16px",
      }}
    >
      {TABS.map(([slug, label]) => {
        const href = `/stock/${ticker}/${slug}`;
        const active = path === href;
        return (
          <Link
            key={slug}
            href={href}
            prefetch
            style={{
              padding: "10px 16px",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              color: active ? "var(--accent-bg)" : "var(--text-secondary)",
              borderBottom: active
                ? "2px solid var(--accent-bg)"
                : "2px solid transparent",
              textDecoration: "none",
            }}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
