import { BoardRead, BoardRefusal } from "@/components/macro/domain/BoardPanel";

import { fmtSigned, fmtValue, toFiniteNumber } from "../format";
import { RatesSection } from "../RatesSection";
import type {
  Decomposition,
  DecompositionAttribution,
  Policy,
  SlopeMetric,
} from "../types";

function attributionByWindow(
  rows: DecompositionAttribution[] | undefined,
  window: string,
) {
  return rows?.find((row) => row.window === window);
}

function Term({
  value,
  label,
  tone,
}: {
  value: unknown;
  label: string;
  tone?: "warn" | "bad";
}) {
  return (
    <span className={`term${tone ? ` ${tone}` : ""}`}>
      {fmtValue(value, "%", 2)}
      <small>{label}</small>
    </span>
  );
}

function Result({ value, label }: { value: unknown; label: string }) {
  return (
    <span className="res">
      {fmtValue(value, "%", 2)} · {label}
    </span>
  );
}

function signClass(value: unknown): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n) || n === 0) return "delta-flat";
  return n > 0 ? "delta-up" : "delta-dn";
}

export function NominalDecompositionSection({
  decomposition,
}: {
  decomposition: Decomposition;
  policy: Policy;
  slopes: SlopeMetric[];
}) {
  const reconciles =
    Math.abs(
      toFiniteNumber(decomposition.real_10y, 0) +
        toFiniteNumber(decomposition.breakeven_10y, 0) -
        toFiniteNumber(decomposition.nominal_10y, 0),
    ) < 0.02;
  return (
    <RatesSection
      id="decomp"
      title="10Y decomposition"
      questions={["Q2"]}
      basis="COMPUTED"
      source="/api/rates/snapshot.decomposition · DGS10 = DFII10 + T10YIE"
    >
      <div className="arith">
        <Term value={decomposition.real_10y} label="real · DFII10" />
        <span className="op">+</span>
        <Term value={decomposition.breakeven_10y} label="breakeven · T10YIE" />
        <span className="op">=</span>
        <Result value={decomposition.nominal_10y} label="nominal 10Y" />
      </div>
      <BoardRead bad={!reconciles}>
        Real yield plus breakeven {reconciles ? "reconciles" : "does not reconcile"}
        {" "}to the stored nominal 10Y. This arithmetic says what is inside the
        level; it is not an inflation-expectations forecast.
      </BoardRead>
    </RatesSection>
  );
}

export function ClevelandDecompositionSection({
  decomposition,
}: {
  decomposition: Decomposition;
}) {
  return (
    <RatesSection
      id="decomp-cleveland"
      title="Model decomposition"
      questions={["Q2", "Q4"]}
      basis="COMPUTED"
      source="/api/rates/snapshot.decomposition · Cleveland model plus FRED gap"
    >
      <div className="arith">
        <Term
          value={decomposition.expected_short_real_rate_10y}
          label="E[short real]"
        />
        <span className="op">+</span>
        <Term
          value={decomposition.expected_short_inflation_10y}
          label="E[short inflation]"
        />
        <span className="op">+</span>
        <Term value={decomposition.real_term_premium_10y} label="real term" />
        <span className="op">+</span>
        <Term
          value={decomposition.inflation_risk_premium_10y}
          label="inflation risk"
        />
        <span className="op">=</span>
        <Result value={decomposition.model_nominal_10y} label="model nominal" />
      </div>
      <div className="arith">
        <Term value={decomposition.model_nominal_10y} label="model nominal" />
        <span className="op">+</span>
        <Term
          value={decomposition.fred_model_residual_10y}
          label="FRED gap"
          tone={decomposition.status === "stale" ? "warn" : undefined}
        />
        <span className="op">=</span>
        <Result value={decomposition.nominal_10y} label="live FRED 10Y" />
      </div>
      <BoardRead>
        Cleveland model terms plus the gap to the live daily 10Y yield.
      </BoardRead>
      <BoardRefusal kind="HONEST BOUNDARY">
        Monthly model, daily market. Model status is {decomposition.status};
        its vintage is {decomposition.clarida_model_date ?? "unavailable"},
        so its terms cannot be treated as a same-day tape explanation.
      </BoardRefusal>
    </RatesSection>
  );
}

export function MoveAttributionSection({
  decomposition,
}: {
  decomposition: Decomposition;
}) {
  const rows = decomposition.attribution ?? [];
  const oneMonth = attributionByWindow(rows, "1M");
  return (
    <RatesSection
      id="decomp-attribution"
      title="Move drivers"
      questions={["Q1", "Q4"]}
      basis="COMPUTED"
      source="/api/rates/snapshot.decomposition.attribution"
    >
      <BoardRefusal>
        Read the model components only on windows its monthly vintage can resolve;
        daily rows remain visible as tape, not fabricated model attribution.
      </BoardRefusal>
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Window</th>
              <th className="num">10Y</th>
              <th className="num">Model</th>
              <th className="num">E[real]</th>
              <th className="num">E[infl]</th>
              <th className="num">Real term</th>
              <th className="num">Infl risk</th>
              <th className="num">Residual</th>
              <th>Driver</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.window}>
                <td>{row.window}</td>
                {[
                  row.nominal_10y_bps,
                  row.model_nominal_10y_bps,
                  row.expected_short_real_bps,
                  row.expected_short_inflation_bps,
                  row.real_term_premium_bps,
                  row.inflation_risk_premium_bps,
                  row.fred_model_residual_bps,
                ].map((value, index) => (
                  <td className={`num ${signClass(value)}`} key={index}>
                    {fmtSigned(value, "", 1)}
                  </td>
                ))}
                <td>{row.driver ?? "n/a"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid g2">
        <BoardRead>
          Over 1M, the traded 10Y moved{" "}
          <b>{fmtSigned(oneMonth?.nominal_10y_bps, "bps", 1)}</b>; the
          Cleveland model accounts for{" "}
          <b>{fmtSigned(oneMonth?.model_nominal_10y_bps, "bps", 1)}</b>.
        </BoardRead>
        <BoardRead>
          The residual is{" "}
          <b>{fmtSigned(oneMonth?.fred_model_residual_bps, "bps", 1)}</b>.
          When it dominates, daily market pricing has moved faster than the
          monthly model and must be read separately.
        </BoardRead>
      </div>
    </RatesSection>
  );
}
