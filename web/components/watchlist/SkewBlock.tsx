import { fmtSigned } from "@/lib/formatters";

export function SkewBlock({ rr25d_30dte }: { rr25d_30dte: number | null }) {
  return (
    <div>
      <div
        style={{
          fontSize: 9,
          color: "var(--text-secondary)",
          letterSpacing: 1,
          marginBottom: 4,
        }}
      >
        SKEW (30d)
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          fontFamily: "var(--font-mono)",
        }}
      >
        <span style={{ color: "var(--text-muted)" }}>25Δ RR</span>
        <span style={{ color: "var(--text-primary)" }}>
          {fmtSigned(rr25d_30dte, 4)}
        </span>
      </div>
    </div>
  );
}
