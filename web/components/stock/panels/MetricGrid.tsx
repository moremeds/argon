export function MetricGrid({
  children,
  cols = 4,
}: {
  children: React.ReactNode;
  cols?: number;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${cols}, 1fr)`,
        gap: 16,
      }}
    >
      {children}
    </div>
  );
}

export function Metric({
  label,
  value,
}: {
  label: string;
  value: string | number | null;
}) {
  return (
    <div>
      <div
        style={{ fontSize: 10, color: "var(--text-muted)", letterSpacing: 1 }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 18,
          fontFamily: "var(--font-mono)",
          color: "var(--text-primary)",
        }}
      >
        {value == null || value === "" ? "—" : value}
      </div>
    </div>
  );
}
