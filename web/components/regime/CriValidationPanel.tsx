"use client";

import type { components } from "@/lib/types";

type ValidationResponse = components["schemas"]["ValidationResponse"];

export default function CriValidationPanel({
  data,
}: {
  data: ValidationResponse;
}) {
  return (
    <div data-testid="cri-validation-panel">
      <div className="regime-panel-title">WARM-STORE BACKTEST</div>
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
        OUT-OF-SAMPLE VALIDATION
      </div>
      {data.oos ? (
        <div data-testid="oos-block">
          <p style={{ fontSize: 13 }}>
            <strong>Method:</strong> {data.oos.method}
          </p>
          <p style={{ fontSize: 13 }}>
            <strong>As of:</strong> {data.oos.as_of}
          </p>
          <table className="gex-history-table" style={{ marginTop: 8 }}>
            <thead>
              <tr>
                <th className="text-left">Model</th>
                <th className="text-right">AUC (dd5)</th>
                <th className="text-right">AUC (vix30)</th>
                <th className="text-right">AUC (dd10)</th>
              </tr>
            </thead>
            <tbody>
              {data.oos.scores.map((s) => (
                <tr key={s.model}>
                  <td>{s.model}</td>
                  <td className="text-right">
                    {s.auc_dd5 != null ? s.auc_dd5.toFixed(3) : "—"}
                  </td>
                  <td className="text-right">
                    {s.auc_vix30 != null ? s.auc_vix30.toFixed(3) : "—"}
                  </td>
                  <td className="text-right">
                    {s.auc_dd10 != null ? s.auc_dd10.toFixed(3) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p
            style={{
              fontSize: 13,
              marginTop: 12,
              padding: 8,
              borderLeft: "2px solid var(--text-muted)",
              color: "var(--text-secondary)",
            }}
          >
            {data.oos.interpretation}
          </p>
        </div>
      ) : (
        <p>OOS summary not available.</p>
      )}
    </div>
  );
}
