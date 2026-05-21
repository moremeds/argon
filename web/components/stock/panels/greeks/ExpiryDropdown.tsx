"use client";

import { useEffect, useRef } from "react";

type Option = { value: string; label: string };

type Props = {
  options: Option[];
  value: string;
  onChange: (next: string) => void;
};

const CONTROL_LABEL: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: 1.5,
  color: "var(--text-muted)",
  textTransform: "uppercase",
};

const TRIGGER: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  background: "var(--bg-panel)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-dim)",
  padding: "2px 8px",
  listStyle: "none",
  cursor: "pointer",
  minWidth: 140,
  display: "inline-flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 8,
};

// Native <details> dropdown styled to match FlowTab's StrikeRangeSelect —
// avoids macOS native <select> chrome (white pill, blue selection) that
// fights the Argon dark theme.
export function ExpiryDropdown({ options, value, onChange }: Props) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onDown = (e: MouseEvent) => {
      if (el.open && !el.contains(e.target as Node)) {
        el.open = false;
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const current = options.find((o) => o.value === value)?.label ?? "—";

  return (
    <label
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      <span style={CONTROL_LABEL}>Expiry:</span>
      <details ref={ref} style={{ position: "relative" }}>
        <summary style={TRIGGER}>
          <span>{current}</span>
          <span style={{ color: "var(--text-muted)" }}>▾</span>
        </summary>
        <div
          role="listbox"
          style={{
            position: "absolute",
            zIndex: 20,
            marginTop: 4,
            minWidth: 160,
            maxHeight: 320,
            overflowY: "auto",
            background: "var(--bg-panel)",
            border: "1px solid var(--border-dim)",
            padding: 4,
          }}
        >
          {options.map((o) => {
            const active = o.value === value;
            return (
              <button
                key={o.value}
                type="button"
                role="option"
                aria-selected={active}
                onClick={(e) => {
                  onChange(o.value);
                  (
                    e.currentTarget.closest("details") as HTMLDetailsElement
                  ).open = false;
                }}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: "4px 8px",
                  fontFamily: "var(--font-mono)",
                  fontSize: 11,
                  background: active ? "var(--accent-bg)" : "transparent",
                  color: active ? "var(--bg-panel)" : "var(--text-primary)",
                  border: "none",
                  cursor: "pointer",
                }}
              >
                {o.label}
              </button>
            );
          })}
        </div>
      </details>
    </label>
  );
}
