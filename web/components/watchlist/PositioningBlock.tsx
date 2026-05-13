import { fmtDecimal, fmtSigned } from "@/lib/formatters";

type Props = {
  call_oi: number | null;
  put_oi: number | null;
  pcr_oi: number | null;
  pcr_vol: number | null;
  pcr_delta_30d: number | null;
};

export function PositioningBlock(p: Props) {
  const total = (p.call_oi ?? 0) + (p.put_oi ?? 0);
  const callPct = total > 0 ? (p.call_oi ?? 0) / total : 0.5;
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
        POSITIONING
      </div>
      <div
        style={{
          display: "flex",
          height: 6,
          marginBottom: 6,
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div style={{ flex: callPct, background: "var(--positive)" }} />
        <div style={{ flex: 1 - callPct, background: "var(--negative)" }} />
      </div>
      <div
        style={{
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          color: "var(--text-muted)",
        }}
      >
        calls {p.call_oi != null ? fmtDecimal(p.call_oi, 0) : "—"}
        {" / "}
        puts {p.put_oi != null ? fmtDecimal(p.put_oi, 0) : "—"}
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          fontFamily: "var(--font-mono)",
          marginTop: 4,
        }}
      >
        <span style={{ color: "var(--text-muted)" }}>PCR (OI)</span>
        <span>{fmtDecimal(p.pcr_oi, 2)}</span>
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          fontFamily: "var(--font-mono)",
        }}
      >
        <span style={{ color: "var(--text-muted)" }}>PCR (Vol)</span>
        <span>{fmtDecimal(p.pcr_vol, 2)}</span>
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          fontFamily: "var(--font-mono)",
        }}
      >
        <span style={{ color: "var(--text-muted)" }}>PCR Δ30d</span>
        <span>{fmtSigned(p.pcr_delta_30d, 2)}</span>
      </div>
    </div>
  );
}
