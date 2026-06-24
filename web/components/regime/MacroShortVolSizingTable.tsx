"use client";

/**
 * Static sizing guidance for the macro short-vol signal — the SPX-direct
 * capital-utilisation backtest (2006–2026), $50k cash account, integer
 * contracts, idle cash at rf 4%. `base_risk_pct` is the only real lever:
 * it trades CAGR for drawdown + skip-rate.
 *
 * Fixed research result, NOT live data. Source: docs/research/vrp/README.md §2.2;
 * reproduce: scripts/_vrp_macro_param_sweep.py + reports/vrp_capital_account.py.
 */
const ROWS = [
  {
    brp: "0.20",
    sharpe: "1.43",
    cagr: "14.2%",
    util: "0.31",
    skip: "0.4%",
    win: "91%",
    breach: "11%",
    entries: "17.9",
    rec: true,
  },
  {
    brp: "0.32",
    sharpe: "1.98 †",
    cagr: "16.6%",
    util: "0.49",
    skip: "14%",
    win: "93%",
    breach: "9%",
    entries: "18.9",
    rec: true,
  },
  {
    brp: "0.50",
    sharpe: "1.87",
    cagr: "17.7%",
    util: "0.61",
    skip: "31%",
    win: "93%",
    breach: "9%",
    entries: "17.1",
    rec: false,
  },
];

const COLS = [
  "base_risk_pct",
  "Sharpe",
  "CAGR gross",
  "util mean",
  "skip%",
  "win%",
  "breach%",
  "entries/yr",
] as const;

const note: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  color: "var(--text-muted)",
  lineHeight: 1.5,
};

export default function MacroShortVolSizingTable() {
  return (
    <div className="gex-range-container">
      <div className="gex-range-title">
        MACRO SHORT-VOL — SIZING GUIDANCE · SPX DIRECT (2006–2026 BACKTEST)
      </div>
      <div style={{ ...note, marginBottom: 8 }}>
        $50k cash account · one spread ≈ $15.7k margin ≈ 31% of $50k ·
        base_risk_pct = fraction of $50k a full-size rung risks
      </div>
      <div className="gex-history-table-wrap">
        <table className="gex-history-table">
          <thead>
            <tr>
              {COLS.map((c) => (
                <th key={c} style={{ textAlign: "right" }}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r) => {
              const cells = [
                r.brp,
                r.sharpe,
                r.cagr,
                r.util,
                r.skip,
                r.win,
                r.breach,
                r.entries,
              ];
              return (
                <tr key={r.brp}>
                  {cells.map((v, i) => (
                    <td
                      key={i}
                      style={{
                        textAlign: "right",
                        color: r.rec ? "var(--positive)" : undefined,
                        fontWeight: r.rec && i === 0 ? 700 : undefined,
                      }}
                    >
                      {v}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div style={{ ...note, marginTop: 8 }}>
        † SPX 0.32&apos;s 1.98 is partly a capital-cap-as-quality-filter
        artifact (in-sample fragile); the robust read is 0.20 → 1.43.
        Recommended deploy: base_risk_pct ≈ 0.20–0.32 (green). util_mean caps
        ~0.7 — the ramp+ gate idles cash in cheap vol. Worst drawdown ≈ −50% of
        capital (2009 GFC).
      </div>
    </div>
  );
}
