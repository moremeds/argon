"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

// Sector chips arranged in labeled sub-rows by relevance.
// "All" lives on the Index row as the universal reset.
const SECTOR_ROWS: { label: string; items: string[] }[] = [
  { label: "Index", items: ["All", "ETF"] },
  {
    label: "AI/Tech",
    items: [
      "M7",
      "Semiconductor",
      "Memory",
      "Optical",
      "NeoCloud",
      "Power",
      "SaaS",
      "Networking",
    ],
  },
  { label: "Thematic", items: ["Crypto", "Fintech", "Space", "Defense"] },
  {
    label: "Defensive",
    items: [
      "Healthcare",
      "Energy",
      "Banks",
      "Consumer",
      "Telecom-Media",
      "Airlines",
    ],
  },
];

const SETUPS = ["All", "C-bull", "C-bear", "F-MULTI", "NEUTRAL"];

const rowLabelStyle: React.CSSProperties = {
  fontSize: 10,
  fontFamily: "var(--font-mono)",
  color: "var(--text-muted)",
  letterSpacing: 1,
  textTransform: "uppercase",
  alignSelf: "center",
  minWidth: 56,
};

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
        flexDirection: "column",
        gap: 6,
        marginBottom: 16,
      }}
    >
      {SECTOR_ROWS.map((row) => (
        <div
          key={row.label}
          style={{ display: "flex", gap: 8, alignItems: "flex-start" }}
        >
          <span style={rowLabelStyle}>{row.label}</span>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap", flex: 1 }}>
            {row.items.map((s) =>
              chip(s, (current.sector ?? "All") === s, () =>
                setParam("sector", s === "All" ? null : s),
              ),
            )}
          </div>
        </div>
      ))}
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "flex-start",
          marginTop: 4,
        }}
      >
        <span style={rowLabelStyle}>Regime</span>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap", flex: 1 }}>
          {SETUPS.map((s) =>
            chip(s, (current.setup ?? "All") === s, () =>
              setParam("setup", s === "All" ? null : s),
            ),
          )}
        </div>
      </div>
    </div>
  );
}
