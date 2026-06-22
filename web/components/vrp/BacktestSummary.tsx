import type { components } from "@/lib/types";
import { fmtDecimal, fmtPct, toNum } from "@/lib/formatters";

type VrpBacktestRow = components["schemas"]["VrpBacktestRow"];

const TH: React.CSSProperties = {
  textAlign: "right",
  padding: "6px 10px",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  borderBottom: "1px solid var(--border)",
};
const TD: React.CSSProperties = {
  textAlign: "right",
  padding: "6px 10px",
  fontFamily: "var(--font-mono)",
  fontSize: 13,
  borderBottom: "1px solid var(--border)",
};

// Pair full + holdout per unit so the honest headline (holdout) sits beside the
// full-history characterization.
function pair(rows: VrpBacktestRow[]) {
  const byUnit = new Map<
    string,
    { full?: VrpBacktestRow; holdout?: VrpBacktestRow }
  >();
  for (const r of rows) {
    const key = `${r.unit_type}:${r.unit_key}`;
    const e = byUnit.get(key) ?? {};
    if (r.scope === "holdout") e.holdout = r;
    else e.full = r;
    byUnit.set(key, e);
  }
  return [...byUnit.values()].filter((e) => e.full);
}

function pnl(v: number | null): React.CSSProperties {
  return {
    ...TD,
    color:
      v == null
        ? "var(--text-muted)"
        : v > 0
          ? "var(--positive)"
          : v < 0
            ? "var(--negative)"
            : "var(--text-muted)",
  };
}

export function BacktestSummary({ results }: { results: VrpBacktestRow[] }) {
  const tickers = pair(results.filter((r) => r.unit_type === "ticker"));
  const buckets = pair(results.filter((r) => r.unit_type === "bucket"));
  const all = [...buckets, ...tickers];
  if (all.length === 0) {
    return (
      <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
        No backtest results yet (weekly job has not run).
      </p>
    );
  }
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr>
          <th style={{ ...TH, textAlign: "left" }}>Unit</th>
          <th style={TH}>Trades</th>
          <th style={TH}>Win %</th>
          <th style={TH}>Mean $</th>
          <th style={TH}>Total $</th>
          <th style={TH}>Breach %</th>
          <th style={TH} title="Honest latest-40% holdout total P&L">
            Holdout $
          </th>
        </tr>
      </thead>
      <tbody>
        {all.map((e) => {
          const f = e.full!;
          const h = e.holdout;
          return (
            <tr key={`${f.unit_type}:${f.unit_key}`}>
              <td style={{ ...TD, textAlign: "left", fontWeight: 700 }}>
                {f.unit_key}
                <span style={{ color: "var(--text-muted)", marginLeft: 6 }}>
                  {f.unit_type}
                </span>
              </td>
              <td style={TD}>{f.n_trades}</td>
              <td style={TD}>{fmtPct(toNum(f.win_rate) ?? null, 0)}</td>
              <td style={pnl(toNum(f.mean_net))}>
                {fmtDecimal(toNum(f.mean_net), 0)}
              </td>
              <td style={pnl(toNum(f.total_net))}>
                {fmtDecimal(toNum(f.total_net), 0)}
              </td>
              <td style={TD}>{fmtPct(toNum(f.breach_rate) ?? null, 0)}</td>
              <td style={pnl(h ? toNum(h.total_net) : null)}>
                {h ? fmtDecimal(toNum(h.total_net), 0) : "—"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
