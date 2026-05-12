"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

const SECTORS = [
  "All",
  "Technology",
  "Financials",
  "Healthcare",
  "Consumer Discretionary",
  "Communication Services",
  "Energy",
  "Industrials",
  "Consumer Staples",
  "ETF",
];

const SETUPS = ["All", "C-bull", "C-bear", "F-MULTI", "NEUTRAL"];

export function FilterBar({
  current,
}: {
  current: Record<string, string | undefined>;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const setParam = (key: string, value: string | null) => {
    const q = new URLSearchParams(params.toString());
    if (value === null || value === "All") q.delete(key);
    else q.set(key, value);
    router.push(`${pathname}?${q.toString()}`);
  };

  const chip = (label: string, active: boolean, onClick: () => void) => (
    <button
      key={label}
      onClick={onClick}
      style={{
        padding: "4px 10px",
        fontSize: 11,
        fontFamily: "var(--font-mono)",
        background: active ? "var(--accent-bg)" : "transparent",
        color: active ? "var(--accent-text)" : "var(--text-secondary)",
        border: `1px solid ${active ? "var(--accent-bg)" : "var(--border-dim)"}`,
        borderRadius: 3,
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );

  return (
    <div
      style={{
        display: "flex",
        gap: 16,
        marginBottom: 16,
        flexWrap: "wrap",
      }}
    >
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        {SECTORS.map((s) =>
          chip(s, (current.sector ?? "All") === s, () =>
            setParam("sector", s === "All" ? null : s),
          ),
        )}
      </div>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        {SETUPS.map((s) =>
          chip(s, (current.setup ?? "All") === s, () =>
            setParam("setup", s === "All" ? null : s),
          ),
        )}
      </div>
    </div>
  );
}
