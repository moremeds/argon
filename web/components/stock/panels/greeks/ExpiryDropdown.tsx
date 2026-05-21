"use client";

type Props = {
  options: { value: string; label: string }[];
  value: string;
  onChange: (next: string) => void;
};

export function ExpiryDropdown({ options, value, onChange }: Props) {
  return (
    <label
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        color: "var(--text-secondary)",
      }}
    >
      <span
        style={{
          fontSize: 10,
          letterSpacing: 1.5,
          color: "var(--text-muted)",
          textTransform: "uppercase",
        }}
      >
        Expiry:
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          background: "var(--bg-panel)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
          padding: "4px 8px",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
