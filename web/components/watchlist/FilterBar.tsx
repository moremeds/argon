"use client";
import { useState, type CSSProperties } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { SECTOR_ROWS } from "./sectorGroups";

const SETUPS = ["All", "C-bull", "C-bear", "F-MULTI", "NEUTRAL"];

const rowLabelStyle: CSSProperties = {
  fontSize: 10,
  fontFamily: "var(--font-mono)",
  color: "var(--text-muted)",
  letterSpacing: 1,
  textTransform: "uppercase",
  alignSelf: "center",
  minWidth: 56,
};

function SetupFormulaPopover() {
  const [open, setOpen] = useState(false);

  return (
    <span
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      style={{ position: "relative", display: "inline-flex" }}
    >
      <button
        type="button"
        aria-label="Setup formula explanation"
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        style={{
          cursor: "help",
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--text-muted)",
          border: "1px solid var(--border-dim)",
          borderRadius: "50%",
          width: 14,
          height: 14,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          background: "transparent",
          padding: 0,
        }}
      >
        i
      </button>
      {open && (
        <div
          role="tooltip"
          style={{
            position: "absolute",
            top: 20,
            left: 0,
            zIndex: 20,
            width: 520,
            background: "var(--bg-panel)",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            padding: 10,
            fontSize: 11,
            lineHeight: 1.45,
            color: "var(--text-primary)",
            boxShadow: "0 12px 30px rgba(0, 0, 0, 0.35)",
          }}
        >
          <p style={{ margin: 0 }}>
            Flow direction = sign(net call premium - net put premium).
          </p>
          <p style={{ margin: "6px 0 0 0" }}>
            net premium = net call premium - net put premium.
          </p>
          <p style={{ margin: "6px 0 0 0" }}>
            Type C requires abs(net premium) &gt;= $5M and flow imbalance &gt;=
            20%, where flow imbalance = abs(net premium) / (call premium + put
            premium).
          </p>
          <p style={{ margin: "6px 0 0 0" }}>
            F-MULTI = Type C base plus at least 2 of: GEX/OI shift, VRP anomaly,
            relative volume &gt; 1.5, or flow polarization &gt; $50M.
          </p>
          <p style={{ margin: "6px 0 0 0", color: "var(--text-secondary)" }}>
            IV rank is context for structure, not a directional veto.
          </p>
        </div>
      )}
    </span>
  );
}

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
        <span
          style={{
            ...rowLabelStyle,
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
          }}
        >
          <span>Setup</span>
          <SetupFormulaPopover />
        </span>
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
