import type { components } from "@/lib/types";
import type { ReactNode } from "react";
import { RatesCurveChart } from "./RatesCurveChart";
import styles from "./RatesDesk.module.css";
import { RatesScorecard } from "./RatesScorecard";
import { RatesSection } from "./RatesSection";
import { fmtSigned, fmtValue, statusLabel, toFiniteNumber } from "./format";

type Snapshot = components["schemas"]["RatesSnapshotResponse"];
type SummaryTile = components["schemas"]["RatesSummaryTile"];
type SlopeMetric = components["schemas"]["RatesSlopeMetric"];
type Scorecard = components["schemas"]["RatesScorecard"];
type Decomposition = NonNullable<Snapshot["decomposition"]>;
type DecompositionAttribution =
  components["schemas"]["RatesDecompositionAttribution"];
type Policy = NonNullable<Snapshot["policy"]>;
type PolicyPathPoint = components["schemas"]["RatesPolicyPathPoint"];

const NAV = [
  ["summary", "Summary"],
  ["curve", "Curve"],
  ["decomp", "Decomp"],
  ["scorecard", "Scorecard"],
  ["policy", "Policy"],
  ["supply", "Supply"],
  ["positioning", "Positioning"],
  ["cross", "Cross-Market"],
  ["events", "Events"],
  ["synthesis", "View"],
] as const;

const FED_BOARD_SERIES = new Set([
  "DGS1MO",
  "DGS3MO",
  "DGS6MO",
  "DGS1",
  "DGS2",
  "DGS3",
  "DGS5",
  "DGS7",
  "DGS10",
  "DGS20",
  "DGS30",
  "DFII5",
  "DFII7",
  "DFII10",
  "DFII20",
  "DFII30",
  "WALCL",
  "WRESBAL",
  "WTREGEN",
]);

const ST_LOUIS_FED_SERIES = new Set(["T5YIE", "T10YIE", "T5YIFR"]);

function isClevelandFedSeries(seriesId: string): boolean {
  return seriesId.startsWith("CLEVE_");
}

function formatComputedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "computed time unavailable";
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .format(date)
    .replace(",", "");
}

function sourcePublisher(seriesId: string): string {
  if (isClevelandFedSeries(seriesId)) {
    return "Cleveland Fed Inflation Expectations";
  }
  if (FED_BOARD_SERIES.has(seriesId)) return "FRED / Board of Governors";
  if (ST_LOUIS_FED_SERIES.has(seriesId)) return "FRED / St. Louis Fed";
  if (seriesId === "EFFR" || seriesId === "SOFR" || seriesId === "RRPONTSYD") {
    return "FRED / New York Fed";
  }
  return "FRED";
}

function fredSeriesUrl(seriesId: string): string {
  if (isClevelandFedSeries(seriesId)) {
    return "https://www.clevelandfed.org/indicators-and-data/inflation-expectations";
  }
  return `https://fred.stlouisfed.org/series/${encodeURIComponent(seriesId)}`;
}

function sourceLinkLabel(seriesId: string): string {
  if (isClevelandFedSeries(seriesId)) return `Cleveland Fed ${seriesId}`;
  return `FRED ${seriesId}`;
}

function snapshotMeta(snapshot: Snapshot): string {
  return `Snapshot update · ${formatComputedAt(
    snapshot.computed_at,
  )} HKT · FRED as of ${snapshot.as_of}`;
}

function deltaClass(value: unknown): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n) || n === 0) return styles.deltaNeutral;
  return n > 0 ? styles.deltaPositive : styles.deltaNegative;
}

function deltaUnit(tile: SummaryTile): string {
  if (tile.unit === "%" || tile.unit === "bps") return "bps 1D";
  return tile.unit ? `${tile.unit} 1D` : "1D";
}

function Tile({ tile }: { tile: SummaryTile }) {
  return (
    <article className={styles.kpiTile}>
      <span>{tile.label}</span>
      <strong>
        {fmtValue(tile.value, tile.unit, tile.unit === "bps" ? 1 : 2)}
      </strong>
      <small className={deltaClass(tile.delta_1d)}>
        {fmtSigned(tile.delta_1d, deltaUnit(tile))}
      </small>
    </article>
  );
}

function policyToneClass(stance: string | undefined): string {
  if (stance === "HIKE") return styles.deltaPositive;
  if (stance === "CUT") return styles.deltaNegative;
  return styles.deltaNeutral;
}

function latestPolicyRows(policy: Policy) {
  return [
    ["Target range", policy.target_range ?? "n/a"],
    ["EFFR", fmtValue(policy.effr, "%", 2)],
    ["SOFR", fmtValue(policy.sofr, "%", 2)],
    [
      "Last meeting",
      policy.last_meeting?.label
        ? `${policy.last_meeting.label} · ${policy.last_meeting.action ?? "n/a"}`
        : "n/a",
    ],
    ["Vote split", policy.last_meeting?.vote_split ?? "n/a"],
  ];
}

function fmtPolicyMetric(value: unknown, unit: string | undefined): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  if (unit === "$T") return `$${n.toFixed(Math.abs(n) < 0.1 ? 3 : 2)}T`;
  if (unit === "$bn") return `$${n.toFixed(1)}bn`;
  return fmtValue(value, unit, unit === "bps" ? 1 : 2);
}

function PolicySection({ policy }: { policy: Policy }) {
  const path = policy.implied_path ?? [];
  return (
    <div className={styles.policyGrid}>
      <article className={styles.policyCard}>
        <div className={styles.policyCardTop}>
          <h3>Policy Rate</h3>
          <span>FRED + Fed</span>
        </div>
        <dl className={styles.policyRows}>
          {latestPolicyRows(policy).map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        <p>{policy.policy_read ?? "Official policy metadata unavailable."}</p>
      </article>

      <article className={styles.policyCard}>
        <div className={styles.policyCardTop}>
          <h3>Market-Implied Path</h3>
          <span>Fed funds futures</span>
        </div>
        {path.length ? (
          <div className={styles.policyPathGrid}>
            {path.slice(0, 5).map((point: PolicyPathPoint) => (
              <div className={styles.pathPill} key={point.meeting_date}>
                <span>{point.label}</span>
                <strong className={policyToneClass(point.stance)}>
                  {fmtValue(point.probability, "%", 0)}
                </strong>
                <small>{point.stance.toLowerCase()}</small>
                <i>
                  <b
                    style={{
                      width: `${Math.max(0, Math.min(100, toFiniteNumber(point.probability, 0)))}%`,
                    }}
                  />
                </i>
              </div>
            ))}
          </div>
        ) : (
          <div className={styles.policyMissing}>Futures path unavailable</div>
        )}
        <p>{policy.path_read ?? "No implied-path source is persisted yet."}</p>
      </article>

      <article className={styles.policyCard}>
        <div className={styles.policyCardTop}>
          <h3>Plumbing</h3>
          <span>FRED</span>
        </div>
        <dl className={styles.policyRows}>
          {(policy.plumbing ?? []).map((row) => (
            <div key={row.label}>
              <dt>{row.label}</dt>
              <dd>
                {fmtPolicyMetric(row.value, row.unit)}
                {row.qualifier ? <small>{row.qualifier}</small> : null}
              </dd>
            </div>
          ))}
        </dl>
        <p>{policy.plumbing_read ?? "Fed plumbing series unavailable."}</p>
      </article>
    </div>
  );
}

function stanceToneClass(kind: "duration" | "curve", stance: string): string {
  if (kind === "duration") {
    if (stance === "BUY") return styles.stancePositive;
    if (stance === "SELL") return styles.stanceNegative;
    return styles.stanceNeutral;
  }
  if (stance === "STEEP") return styles.stanceNegative;
  if (stance === "FLAT") return styles.stancePositive;
  return styles.stanceNeutral;
}

function stanceDescription(
  kind: "duration" | "curve",
  stance: string,
  fallback: string | undefined,
): string {
  if (fallback) return fallback;
  if (kind === "duration") {
    if (stance === "BUY") return "Rule score favors owning duration.";
    if (stance === "SELL") return "Rule score favors underweighting duration.";
    return "Rule score is balanced; duration signal is neutral.";
  }
  if (stance === "STEEP") return "Rule score favors a steeper curve.";
  if (stance === "FLAT") return "Rule score favors a flatter curve.";
  return "Rule score is balanced; curve signal is neutral.";
}

function StanceCard({
  label,
  kind,
  stance,
  description,
}: {
  label: string;
  kind: "duration" | "curve";
  stance: string;
  description: string;
}) {
  return (
    <article
      className={[styles.stanceCard, stanceToneClass(kind, stance)].join(" ")}
      data-watermark={stance}
    >
      <span className={styles.stanceLabel}>{label}</span>
      <strong>{stance}</strong>
      <p>{description}</p>
      <span className={styles.stanceWatermark} aria-hidden="true">
        {stance}
      </span>
    </article>
  );
}

function SummaryStances({
  scorecard,
  synthesis,
}: {
  scorecard: Scorecard;
  synthesis: Snapshot["synthesis"];
}) {
  return (
    <div className={styles.stanceGrid}>
      <StanceCard
        label="Duration stance"
        kind="duration"
        stance={scorecard.duration_stance}
        description={stanceDescription(
          "duration",
          scorecard.duration_stance,
          synthesis?.duration_view,
        )}
      />
      <StanceCard
        label="Curve stance"
        kind="curve"
        stance={scorecard.curve_stance}
        description={stanceDescription(
          "curve",
          scorecard.curve_stance,
          synthesis?.curve_view,
        )}
      />
    </div>
  );
}

function slopeInterpretation(slope: SlopeMetric): string {
  const value = Number(slope.value_bps);
  if (!Number.isFinite(value))
    return "Signal unavailable until all required tenors are live.";
  if (slope.label.includes("butterfly")) {
    if (value <= -15)
      return "Belly is rich versus wings; curve is locally concave around 5Y.";
    if (value >= 15)
      return "Belly is cheap versus wings; curve is locally convex around 5Y.";
    return "Belly is close to fair versus 2Y and 10Y wings.";
  }
  if (slope.label === "3m10y") {
    if (value < 0)
      return "Front-end inversion warns policy is restrictive versus long growth pricing.";
    if (value < 50)
      return "Term premium is modest; curve is only lightly positive from bills to 10Y.";
    return "Long end is clearly above bills; easing or term premium pressure is visible.";
  }
  if (value < 0)
    return "Inverted spread; front end is leading and duration risk is defensive.";
  if (value < 35)
    return "Flat positive spread; curve has limited carry cushion.";
  if (value < 90)
    return "Normal positive slope; long-end yield pickup is meaningful.";
  return "Steep spread; long-end supply, inflation, or term premium is dominating.";
}

function pctMinus(...values: Array<number | null | undefined>): number | null {
  const [first, ...rest] = values;
  if (first == null || rest.some((value) => value == null)) return null;
  let total = Number(first);
  for (const value of rest) total -= Number(value);
  return Number(total.toFixed(2));
}

function attributionByWindow(
  rows: DecompositionAttribution[] | undefined,
  window: string,
): DecompositionAttribution | undefined {
  return rows?.find((row) => row.window === window);
}

function bpsText(value: unknown): string {
  return fmtSigned(value, "bps", 1);
}

function bpsNumber(value: unknown): number {
  return toFiniteNumber(value, 0);
}

function movementVerb(value: unknown): string {
  const n = bpsNumber(value);
  if (n > 0) return "rose";
  if (n < 0) return "fell";
  return "was flat";
}

function contributionLabel(label: string): string {
  if (label === "Expected real") return "short real-rate expectations";
  if (label === "Expected inflation") return "short inflation expectations";
  if (label === "Real term") return "real term premium";
  if (label === "Inflation risk") return "inflation risk premium";
  return "FRED residual";
}

function componentNarrative(label: string, value: unknown): string {
  const n = bpsNumber(value);
  const direction = n >= 0 ? "added" : "removed";
  return `${contributionLabel(label)} ${direction} ${Math.abs(n).toFixed(1)} bps`;
}

function modelDriver(row: DecompositionAttribution | undefined): {
  label: string;
  value: number;
} {
  const components = [
    ["Expected real", bpsNumber(row?.expected_short_real_bps)],
    ["Expected inflation", bpsNumber(row?.expected_short_inflation_bps)],
    ["Real term", bpsNumber(row?.real_term_premium_bps)],
    ["Inflation risk", bpsNumber(row?.inflation_risk_premium_bps)],
  ] as const;
  return components.reduce(
    (best, [label, value]) =>
      Math.abs(value) > Math.abs(best.value) ? { label, value } : best,
    { label: "Expected real", value: 0 },
  );
}

function ratesAttributionRead(row: DecompositionAttribution | undefined): {
  headline: string;
  model: string;
  market: string;
} {
  if (!row) {
    return {
      headline: "1M rates read is unavailable until the attribution window is populated.",
      model: "Cleveland model components are missing for this window.",
      market: "Live FRED curve data still renders, but no model attribution can be made.",
    };
  }

  const fredMove = bpsNumber(row.nominal_10y_bps);
  const modelMove = bpsNumber(row.model_nominal_10y_bps);
  const residual = bpsNumber(row.fred_model_residual_bps);
  const driver = modelDriver(row);
  const premiumMove =
    bpsNumber(row.real_term_premium_bps) +
    bpsNumber(row.inflation_risk_premium_bps);
  const expectedMove =
    bpsNumber(row.expected_short_real_bps) +
    bpsNumber(row.expected_short_inflation_bps);

  const headline =
    `Over ${row.window}, FRED 10Y ${movementVerb(fredMove)} ${bpsText(
      fredMove,
    )}; Cleveland's monthly model explains ${bpsText(
      modelMove,
    )}, while the live FRED residual accounts for ${bpsText(residual)}.`;

  let model: string;
  if (Math.abs(modelMove) < 0.5) {
    model =
      "The Cleveland monthly model is broadly unchanged, so the displayed move is mostly a daily-market residual rather than a fresh model signal.";
  } else if (Math.abs(premiumMove) > Math.abs(expectedMove)) {
    model =
      `Inside the model, ${componentNarrative(
        driver.label,
        driver.value,
      )}. Premium components are doing more work than expected short-rate components, so read this as risk-premium/supply compensation rather than a clean policy path shift.`;
  } else {
    model =
      `Inside the model, ${componentNarrative(
        driver.label,
        driver.value,
      )}. Expected short-rate components dominate, so read this as policy/inflation-expectation repricing before term-premium pressure.`;
  }

  let market: string;
  if (Math.abs(residual) > Math.abs(modelMove)) {
    market =
      "Because the residual is larger than the model move, daily FRED pricing has moved faster than the monthly Cleveland release; treat the model read as authoritative for decomposition, but not as a same-day tape explanation.";
  } else if (fredMove > 0 && premiumMove > 0) {
    market =
      "For rates, higher long-end yields with positive premium contribution is bearish duration and keeps steepening risk alive if the front end stays anchored.";
  } else if (fredMove < 0 && premiumMove < 0) {
    market =
      "For rates, falling long-end yields with lower premium compensation is constructive duration and reduces steepening pressure.";
  } else {
    market =
      "For rates, the signal is mixed: use the curve table for the daily tape and the Cleveland row for slower decomposition context.";
  }

  return { headline, model, market };
}

function DecompositionCard({
  label,
  sublabel,
  value,
  footnote,
  tone,
}: {
  label: string;
  sublabel: string;
  value: unknown;
  footnote: string;
  tone?: "primary" | "accent";
}) {
  return (
    <article
      className={[
        styles.decompTile,
        tone === "primary" ? styles.decompTilePrimary : "",
        tone === "accent" ? styles.decompTileAccent : "",
      ].join(" ")}
    >
      <span>{label}</span>
      <small>{sublabel}</small>
      <strong>{fmtValue(value, "%", 2)}</strong>
      <p>{footnote}</p>
    </article>
  );
}

function DecompositionTerm({
  operator,
  children,
}: {
  operator: "=" | "+";
  children: ReactNode;
}) {
  return (
    <div className={styles.decompTerm}>
      <span className={styles.decompOperator}>{operator}</span>
      {children}
    </div>
  );
}

function DecompositionFormula({ decomp }: { decomp: Decomposition }) {
  const oneMonth = attributionByWindow(decomp.attribution, "1M");
  return (
    <div className={styles.decompFormula}>
      <div className={styles.decompFormulaTop}>
        <h3>
          Live 10Y nominal = E[short real] + E[short inflation] + real term
          premium + inflation risk premium + Cleveland/FRED gap
        </h3>
        <span>
          Cleveland Fed model + FRED DGS10 ·{" "}
          {decomp.clarida_model_date ?? "model date n/a"}
        </span>
      </div>
      <div className={styles.decompEquation}>
        <DecompositionCard
          label="Live 10Y nominal"
          sublabel="FRED DGS10"
          value={decomp.nominal_10y}
          footnote={`${bpsText(oneMonth?.nominal_10y_bps)} over 1M`}
          tone="primary"
        />
        <DecompositionTerm operator="=">
          <DecompositionCard
            label="Expected short real"
            sublabel="Model real yield - real premium"
            value={decomp.expected_short_real_rate_10y}
            footnote={`${bpsText(oneMonth?.expected_short_real_bps)} model 1M`}
            tone="accent"
          />
        </DecompositionTerm>
        <DecompositionTerm operator="+">
          <DecompositionCard
            label="Expected short inflation"
            sublabel="Cleveland 10Y expected inflation"
            value={decomp.expected_short_inflation_10y}
            footnote={`${bpsText(oneMonth?.expected_short_inflation_bps)} model 1M`}
          />
        </DecompositionTerm>
        <DecompositionTerm operator="+">
          <DecompositionCard
            label="Real term premium"
            sublabel="Cleveland real risk premium"
            value={decomp.real_term_premium_10y}
            footnote={`${bpsText(oneMonth?.real_term_premium_bps)} model 1M`}
          />
        </DecompositionTerm>
        <DecompositionTerm operator="+">
          <DecompositionCard
            label="Inflation risk premium"
            sublabel="Cleveland inflation risk premium"
            value={decomp.inflation_risk_premium_10y}
            footnote={`${bpsText(oneMonth?.inflation_risk_premium_bps)} model 1M`}
          />
        </DecompositionTerm>
        <DecompositionTerm operator="+">
          <DecompositionCard
            label="Cleveland/FRED gap"
            sublabel="DGS10 - model-implied nominal"
            value={decomp.fred_model_residual_10y}
            footnote={`${bpsText(oneMonth?.fred_model_residual_bps)} over 1M`}
          />
        </DecompositionTerm>
      </div>
      <p className={styles.decompRead}>
        Rule read: the first four terms are the Cleveland monthly decomposition.
        The Cleveland/FRED gap is the reconciliation term that bridges the
        model-implied nominal rate to the live daily DGS10 rate.
      </p>
    </div>
  );
}

function DecompositionViewCards({
  decomp,
  policy,
  slopes,
}: {
  decomp: Decomposition;
  policy: Snapshot["policy"];
  slopes: SlopeMetric[];
}) {
  const tenTwo = slopes.find((slope) => slope.label === "2s10s");
  const termComp = pctMinus(decomp.nominal_10y, policy?.effr);
  return (
    <div className={styles.decompDetailGrid}>
      <article className={styles.decompDetailCard}>
        <div className={styles.decompDetailTop}>
          <h3>Fundamental view</h3>
          <span>Real / inflation</span>
        </div>
        <div className={styles.decompIdentity}>
          {fmtValue(decomp.nominal_10y, "%", 2)} ={" "}
          {fmtValue(decomp.expected_short_real_rate_10y, "%", 2)} +{" "}
          {fmtValue(decomp.expected_short_inflation_10y, "%", 2)} +{" "}
          {fmtValue(decomp.real_term_premium_10y, "%", 2)} +{" "}
          {fmtValue(decomp.inflation_risk_premium_10y, "%", 2)}
        </div>
        <dl className={styles.decompRows}>
          <div>
            <dt>Expected short real component</dt>
            <dd>{fmtValue(decomp.expected_short_real_rate_10y, "%", 2)}</dd>
          </div>
          <div>
            <dt>Expected short inflation</dt>
            <dd>{fmtValue(decomp.expected_short_inflation_10y, "%", 2)}</dd>
          </div>
          <div>
            <dt>Real term premium</dt>
            <dd>{fmtValue(decomp.real_term_premium_10y, "%", 2)}</dd>
          </div>
          <div>
            <dt>Inflation risk premium</dt>
            <dd>{fmtValue(decomp.inflation_risk_premium_10y, "%", 2)}</dd>
          </div>
          <div>
            <dt>FRED residual</dt>
            <dd>{fmtValue(decomp.fred_model_residual_10y, "%", 2)}</dd>
          </div>
        </dl>
        <p>
          Rule: a larger expected-real component points to policy/real-rate
          repricing; larger inflation or risk-premium components point to
          inflation uncertainty or supply/risk-premium repricing.
        </p>
      </article>

      <article className={styles.decompDetailCard}>
        <div className={styles.decompDetailTop}>
          <h3>Policy view</h3>
          <span>Short anchor</span>
        </div>
        <div className={styles.decompIdentity}>
          {fmtValue(decomp.nominal_10y, "%", 2)} ={" "}
          {fmtValue(policy?.effr, "%", 2)} + {fmtValue(termComp, "%", 2)}
        </div>
        <dl className={styles.decompRows}>
          <div>
            <dt>Short nominal anchor</dt>
            <dd>{fmtValue(policy?.effr, "%", 2)}</dd>
          </div>
          <div>
            <dt>10Y less EFFR compensation</dt>
            <dd>{fmtValue(termComp, "%", 2)}</dd>
          </div>
          <div>
            <dt>Policy overnight rate</dt>
            <dd>{fmtValue(policy?.sofr, "%", 2)}</dd>
          </div>
          <div>
            <dt>10Y-2Y spread</dt>
            <dd>{fmtValue(tenTwo?.value_bps, "bps", 1)}</dd>
          </div>
        </dl>
        <p>
          Rule: a rising long end while the short anchor is stable indicates
          more required term compensation; a flatter spread keeps policy
          pressure dominant.
        </p>
      </article>
    </div>
  );
}

function DecompositionAttributionTable({
  rows,
}: {
  rows: DecompositionAttribution[];
}) {
  const oneMonth = attributionByWindow(rows, "1M");
  const read = ratesAttributionRead(oneMonth);
  const maxContribution = Math.max(
    1,
    ...rows.flatMap((row) => [
      Math.abs(toFiniteNumber(row.expected_short_real_bps, 0)),
      Math.abs(toFiniteNumber(row.expected_short_inflation_bps, 0)),
      Math.abs(toFiniteNumber(row.real_term_premium_bps, 0)),
      Math.abs(toFiniteNumber(row.inflation_risk_premium_bps, 0)),
      Math.abs(toFiniteNumber(row.fred_model_residual_bps, 0)),
    ]),
  );
  return (
    <div className={styles.decompAttribution}>
      <div className={styles.decompFormulaTop}>
        <h3>Move attribution · bps</h3>
        <span>Cleveland monthly model + FRED daily curve</span>
      </div>
      <div className={styles.decompTableWrap}>
        <table className={styles.decompMoveTable}>
          <thead>
            <tr>
              <th>Window</th>
              <th>FRED 10Y</th>
              <th>Model nominal</th>
              <th>E[real]</th>
              <th>E[inflation]</th>
              <th>Real term</th>
              <th>Inflation risk</th>
              <th>FRED gap</th>
              <th>Driver</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.window}>
                <th>{row.window}</th>
                <td className={deltaClass(row.nominal_10y_bps)}>
                  {fmtSigned(row.nominal_10y_bps, "", 1)}
                </td>
                <td className={deltaClass(row.model_nominal_10y_bps)}>
                  {fmtSigned(row.model_nominal_10y_bps, "", 1)}
                </td>
                <td className={deltaClass(row.expected_short_real_bps)}>
                  {fmtSigned(row.expected_short_real_bps, "", 1)}
                </td>
                <td className={deltaClass(row.expected_short_inflation_bps)}>
                  {fmtSigned(row.expected_short_inflation_bps, "", 1)}
                </td>
                <td className={deltaClass(row.real_term_premium_bps)}>
                  {fmtSigned(row.real_term_premium_bps, "", 1)}
                </td>
                <td className={deltaClass(row.inflation_risk_premium_bps)}>
                  {fmtSigned(row.inflation_risk_premium_bps, "", 1)}
                </td>
                <td className={deltaClass(row.fred_model_residual_bps)}>
                  {fmtSigned(row.fred_model_residual_bps, "", 1)}
                </td>
                <td>{row.driver ?? "n/a"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={styles.decompBars}>
        {[
          ["Expected real", oneMonth?.expected_short_real_bps],
          ["Expected inflation", oneMonth?.expected_short_inflation_bps],
          ["Real term", oneMonth?.real_term_premium_bps],
          ["Inflation risk", oneMonth?.inflation_risk_premium_bps],
          ["FRED residual", oneMonth?.fred_model_residual_bps],
        ].map(([label, value]) => {
          const numeric = toFiniteNumber(value, 0);
          return (
            <div key={label} className={styles.decompBarRow}>
              <span>{label}</span>
              <i>
                <b
                  className={numeric >= 0 ? styles.barPositive : styles.barNegative}
                  style={{
                    width: `${Math.max(
                      2,
                      (Math.abs(numeric) / maxContribution) * 100,
                    )}%`,
                  }}
                />
              </i>
              <strong className={deltaClass(value)}>
                {value == null ? "n/a" : fmtSigned(value, "", 1)}
              </strong>
            </div>
          );
        })}
      </div>
      <p className={styles.decompRead}>
        Conclusion: over the model 1M window, expected real contributes{" "}
        {fmtValue(oneMonth?.expected_short_real_bps, "bps", 1)}, expected
        inflation contributes{" "}
        {fmtValue(oneMonth?.expected_short_inflation_bps, "bps", 1)}, and
        premium components explain the remaining Cleveland model move.
      </p>
      <div className={styles.ratesReadGrid} aria-label="Rates interpretation">
        <article>
          <span>Rates read</span>
          <p>{read.headline}</p>
        </article>
        <article>
          <span>Model driver</span>
          <p>{read.model}</p>
        </article>
        <article>
          <span>Trading implication</span>
          <p>{read.market}</p>
        </article>
      </div>
    </div>
  );
}

function DecompositionSourceCards({
  decomp,
  policy,
}: {
  decomp: Decomposition;
  policy: Snapshot["policy"];
}) {
  return (
    <div className={styles.decompSources}>
      <div className={styles.decompFormulaTop}>
        <h3>Expectations sources</h3>
        <span>Live coverage</span>
      </div>
      <div className={styles.decompSourceGrid}>
        <article>
          <span>Policy anchor</span>
          <strong>EFFR {fmtValue(policy?.effr, "%", 2)}</strong>
          <p>Live FRED effective fed funds rate for the short-rate anchor.</p>
        </article>
        <article>
          <span>Cleveland model</span>
          <strong>
            {fmtValue(decomp.model_nominal_10y, "%", 2)} implied nominal
          </strong>
          <p>Monthly model split for expected inflation and risk premia.</p>
        </article>
        <article>
          <span>Market proxy</span>
          <strong>5Y5Y {fmtValue(decomp.forward_inflation_5y5y, "%", 2)}</strong>
          <p>FRED forward inflation compensation remains an impulse check.</p>
        </article>
      </div>
    </div>
  );
}

export function RatesDesk({ snapshot }: { snapshot: Snapshot | null }) {
  if (!snapshot) {
    return (
      <div className={styles.page}>
        <div className={styles.emptyState}>
          <p className={styles.eyebrow}>US Rates Factor Desk</p>
          <h1>Rates snapshot not computed</h1>
          <p>
            Run the live FRED backfill or wait for the scheduled worker refresh.
          </p>
        </div>
      </div>
    );
  }

  const summary = snapshot.summary ?? [];
  const curve = snapshot.curve ?? { points: [], slopes: [] };
  const policy: Policy = snapshot.policy ?? {
    status: "partial",
    plumbing: [],
    implied_path: [],
  };
  const supply = snapshot.supply;
  const positioning = snapshot.positioning;
  const cross = snapshot.cross_market;
  const scorecard = snapshot.scorecard ?? {
    duration_stance: "NEUTRAL",
    curve_stance: "NEUTRAL",
    groups: [],
  };
  const decomposition: Decomposition = snapshot.decomposition ?? {
    status: "missing",
    attribution: [],
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerTop}>
          <div className={styles.titleLockup}>
            <h1>
              US Rates Factor Desk<span>.</span>
            </h1>
            <p>Treasury Factor Board</p>
          </div>
          <p className={styles.headerMeta}>
            {snapshotMeta(snapshot)}
          </p>
        </div>
        <nav className={styles.nav} aria-label="Rates sections">
          {NAV.map(([id, label]) => (
            <a
              key={id}
              href={`#${id}`}
              className={id === "summary" ? styles.navActive : undefined}
            >
              {label}
            </a>
          ))}
        </nav>
      </header>

      <RatesSection id="summary" title="Summary" eyebrow="Live FRED curve">
        <div className={styles.summaryStack}>
          <div className={styles.kpiGrid}>
            {summary.map((tile) => (
              <Tile key={tile.label} tile={tile} />
            ))}
          </div>
          <SummaryStances
            scorecard={scorecard}
            synthesis={snapshot.synthesis}
          />
        </div>
      </RatesSection>

      <RatesSection
        id="curve"
        title="Yield Curve"
        eyebrow="Nominal Treasury curve"
      >
        <RatesCurveChart points={curve.points ?? []} />
        <div className={styles.slopeCards}>
          {(curve.slopes ?? []).map((slope) => (
            <article key={slope.label} className={styles.slopeCard}>
              <span>{slope.label}</span>
              <strong>{fmtValue(slope.value_bps, "bps", 1)}</strong>
              <p>{slopeInterpretation(slope)}</p>
            </article>
          ))}
        </div>
      </RatesSection>

      <RatesSection
        id="decomp"
        title="Decomposition"
        eyebrow="10Y nominal / real / inflation"
      >
        <div className={styles.decompStack}>
          <DecompositionFormula decomp={decomposition} />
          <DecompositionViewCards
            decomp={decomposition}
            policy={policy}
            slopes={curve.slopes ?? []}
          />
          <DecompositionAttributionTable
            rows={decomposition.attribution ?? []}
          />
          <DecompositionSourceCards
            decomp={decomposition}
            policy={policy}
          />
        </div>
      </RatesSection>

      <RatesSection id="scorecard" title="Scorecard" eyebrow="Rule weights">
        <RatesScorecard scorecard={scorecard} />
      </RatesSection>

      <RatesSection
        id="policy"
        title="Policy"
        status={statusLabel(policy?.status)}
      >
        <PolicySection policy={policy} />
      </RatesSection>

      <RatesSection
        id="supply"
        title="Supply"
        status={statusLabel(supply?.status)}
      >
        <div className={styles.notePanel}>
          <strong>{statusLabel(supply?.status)}</strong>
          {(supply?.notes?.length
            ? supply.notes
            : ["Treasury auction feed not wired in Phase 1."]
          ).map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      </RatesSection>

      <RatesSection
        id="positioning"
        title="Positioning"
        status={statusLabel(positioning?.status)}
      >
        <div className={styles.notePanel}>
          <strong>{statusLabel(positioning?.status)}</strong>
          <p>CFTC/TIC feeds not wired in Phase 1.</p>
        </div>
      </RatesSection>

      <RatesSection
        id="cross"
        title="Cross-Market"
        status={statusLabel(cross?.status)}
      >
        <div className={styles.compactGrid}>
          {(cross?.rows ?? []).map((tile) => (
            <Tile key={tile.label} tile={tile} />
          ))}
        </div>
      </RatesSection>

      <RatesSection
        id="events"
        title="Events"
        status={snapshot.events?.length ? "Live" : "Unavailable"}
      >
        <div className={styles.notePanel}>
          {snapshot.events?.length ? (
            snapshot.events.map((event) => (
              <p key={event.label}>{event.label}</p>
            ))
          ) : (
            <p>Official events/news source not wired in Phase 1.</p>
          )}
        </div>
      </RatesSection>

      <RatesSection
        id="sources"
        title="Source Freshness"
        eyebrow="FRED observations"
      >
        <div className={styles.sourceGrid}>
          {(snapshot.source_freshness ?? []).map((source) => (
            <div key={source.id} className={styles.sourceRow}>
              <strong>{source.label || source.id}</strong>
              <span>{sourcePublisher(source.id)}</span>
              <span>Latest obs {source.latest_obs_date ?? "n/a"}</span>
              <span>{statusLabel(source.status)}</span>
              <a
                href={fredSeriesUrl(source.id)}
                target="_blank"
                rel="noreferrer"
              >
                {sourceLinkLabel(source.id)}
              </a>
            </div>
          ))}
        </div>
      </RatesSection>

      <RatesSection id="synthesis" title="Synthesis">
        <div className={styles.synthesis}>
          <p>{snapshot.synthesis.duration_view}</p>
          <p>{snapshot.synthesis.curve_view}</p>
          {(snapshot.synthesis.risks ?? []).map((risk) => (
            <span key={risk}>{risk}</span>
          ))}
        </div>
      </RatesSection>
    </div>
  );
}
