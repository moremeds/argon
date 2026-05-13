import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];

const panelStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 16,
  fontFamily: "var(--font-mono)",
  minWidth: 0,
};

const labelStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

function fmtNum(v: number | null, digits = 2): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/**
 * Horizontal range bar:
 *  - leftmost = MAX_ACCEL strike
 *  - rightmost = MAX_MAGNET strike
 *  - markers: GEX FLIP, current SPOT (close), MAX_MAGNET
 */
export function ExpectedRangeBar({ report }: { report: Report }) {
  const m = report.market_structure;
  const lv = report.market_structure_levels;
  const spot = toNum(m.spot);
  const flip = lv?.gex_flip ? toNum(lv.gex_flip.strike) : null;
  const lo = lv?.max_accel ? toNum(lv.max_accel.strike) : null;
  const hi = lv?.max_magnet ? toNum(lv.max_magnet.strike) : null;

  const haveRange = lo != null && hi != null && hi > lo;
  const xOf = (v: number | null) => {
    if (v == null || !haveRange) return null;
    return ((v - lo!) / (hi! - lo!)) * 100;
  };

  return (
    <div style={panelStyle}>
      <div style={{ ...labelStyle, marginBottom: 16 }}>
        Expected Range —{" "}
        {new Date(report.generated_at).toISOString().slice(0, 10)}
      </div>

      <div style={{ position: "relative", height: 36, marginBottom: 28 }}>
        {/* Range bar */}
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 16,
            height: 4,
            background: "var(--positive)",
            opacity: 0.35,
            borderRadius: 2,
          }}
        />
        {/* Markers */}
        {flip != null && xOf(flip) != null && (
          <Marker x={xOf(flip)!} color="var(--warning)" label="GEX FLIP" />
        )}
        {spot != null && xOf(spot) != null && (
          <Marker x={xOf(spot)!} color="var(--text-primary)" label="CLOSE" />
        )}
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 11,
          color: "var(--text-secondary)",
        }}
      >
        <div>
          <div style={{ color: "var(--text-primary)", fontWeight: 700 }}>
            {fmtNum(lo, 2)}
          </div>
          <div style={labelStyle}>Max Accel</div>
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ color: "var(--warning)", fontWeight: 700 }}>
            {fmtNum(flip, 2)}
          </div>
          <div style={labelStyle}>GEX Flip</div>
        </div>
        <div style={{ textAlign: "center" }}>
          <div style={{ color: "var(--text-primary)", fontWeight: 700 }}>
            {fmtNum(spot, 2)}
          </div>
          <div style={labelStyle}>Close</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ color: "var(--positive)", fontWeight: 700 }}>
            {fmtNum(hi, 2)}
          </div>
          <div style={labelStyle}>Max Magnet</div>
        </div>
      </div>
    </div>
  );
}

function Marker({
  x,
  color,
  label,
}: {
  x: number;
  color: string;
  label: string;
}) {
  return (
    <div
      style={{
        position: "absolute",
        left: `${Math.max(0, Math.min(100, x))}%`,
        top: 6,
        transform: "translateX(-50%)",
        textAlign: "center",
      }}
    >
      <div
        style={{
          width: 2,
          height: 24,
          background: color,
          margin: "0 auto",
        }}
      />
      <div
        style={{
          fontSize: 9,
          color,
          letterSpacing: 1,
          textTransform: "uppercase",
          marginTop: 2,
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </div>
    </div>
  );
}
