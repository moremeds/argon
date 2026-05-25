"use client";

import type { components } from "@/lib/types";

type VcgValidationResponse = components["schemas"]["VcgValidationResponse"];

export default function VcgValidationPanel({
  data,
}: {
  data: VcgValidationResponse;
}) {
  return (
    <div data-testid="vcg-validation-panel">
      <div className="regime-panel-title">
        VCG BACKTEST ({data.credit_proxy})
      </div>
      <pre
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "12px",
          whiteSpace: "pre-wrap",
          color: "var(--text-primary)",
        }}
      >
        {data.backtest_md}
      </pre>

      <div className="regime-panel-title" style={{ marginTop: 16 }}>
        INTERPRETATION DISTRIBUTION
      </div>
      <table className="gex-history-table">
        <thead>
          <tr>
            <th className="text-left">Interpretation</th>
            <th className="text-right">N</th>
            <th className="text-right">%</th>
          </tr>
        </thead>
        <tbody>
          {data.interpretation_distribution.map((row) => (
            <tr key={row.interpretation}>
              <td>{row.interpretation}</td>
              <td className="text-right">{row.n}</td>
              <td className="text-right">{row.pct.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="regime-panel-title" style={{ marginTop: 16 }}>
        NAMED-CRASH ±5d WINDOW
      </div>
      {data.named_crash_window.length === 0 ? (
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
          No named-crash window data persisted with this run.
        </p>
      ) : (
        data.named_crash_window.map((ev) => (
          <div key={ev.date} style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>
              {ev.date} — {ev.label}
            </div>
            <table className="gex-history-table">
              <thead>
                <tr>
                  <th className="text-right">offset</th>
                  <th className="text-right">vcg</th>
                  <th className="text-right">vcg_adj</th>
                  <th className="text-left">interp</th>
                </tr>
              </thead>
              <tbody>
                {ev.offsets.map((o) => (
                  <tr key={o.offset_days}>
                    <td className="text-right">
                      {o.offset_days >= 0 ? `+${o.offset_days}` : o.offset_days}
                    </td>
                    <td className="text-right">
                      {o.vcg != null ? o.vcg.toFixed(2) : "—"}
                    </td>
                    <td className="text-right">
                      {o.vcg_adj != null ? o.vcg_adj.toFixed(2) : "—"}
                    </td>
                    <td>{o.interpretation ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))
      )}
    </div>
  );
}
