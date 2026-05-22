import type { components } from "@/lib/types";
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

function DecompositionFormula({ decomp }: { decomp: Decomposition }) {
  const residual = pctMinus(
    decomp.nominal_10y,
    decomp.real_10y,
    decomp.breakeven_10y,
  );
  const oneMonth = attributionByWindow(decomp.attribution, "1M");
  return (
    <div className={styles.decompFormula}>
      <div className={styles.decompFormulaTop}>
        <h3>10Y nominal = real yield + inflation compensation</h3>
        <span>FRED live proxy · DFII10 / T10YIE</span>
      </div>
      <div className={styles.decompEquation}>
        <DecompositionCard
          label="Nominal 10Y"
          sublabel="DGS10"
          value={decomp.nominal_10y}
          footnote={`${bpsText(oneMonth?.nominal_10y_bps)} over 1M`}
          tone="primary"
        />
        <span className={styles.decompOperator}>=</span>
        <DecompositionCard
          label="Real 10Y"
          sublabel="DFII10"
          value={decomp.real_10y}
          footnote={`${bpsText(oneMonth?.real_10y_bps)} over 1M`}
          tone="accent"
        />
        <span className={styles.decompOperator}>+</span>
        <DecompositionCard
          label="Breakeven"
          sublabel="T10YIE"
          value={decomp.breakeven_10y}
          footnote={`${bpsText(oneMonth?.breakeven_10y_bps)} over 1M`}
        />
        <span className={styles.decompOperator}>+</span>
        <DecompositionCard
          label="Live residual"
          sublabel="Nominal - real - BEI"
          value={residual}
          footnote={`${bpsText(oneMonth?.residual_bps)} over 1M`}
        />
      </div>
      <p className={styles.decompRead}>
        Rule read: moves are attributed to actual FRED history. The residual is
        shown explicitly instead of filling unsourced term-premium or risk-premium
        estimates.
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
  const realMonth = attributionByWindow(decomp.attribution, "1M")?.real_10y_bps;
  const beiMonth = attributionByWindow(decomp.attribution, "1M")
    ?.breakeven_10y_bps;
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
          {fmtValue(decomp.real_10y, "%", 2)} +{" "}
          {fmtValue(decomp.breakeven_10y, "%", 2)}
        </div>
        <dl className={styles.decompRows}>
          <div>
            <dt>10Y TIPS real yield</dt>
            <dd>{fmtValue(decomp.real_10y, "%", 2)}</dd>
          </div>
          <div>
            <dt>10Y breakeven inflation</dt>
            <dd>{fmtValue(decomp.breakeven_10y, "%", 2)}</dd>
          </div>
          <div>
            <dt>Real yield 1M move</dt>
            <dd className={deltaClass(realMonth)}>{bpsText(realMonth)}</dd>
          </div>
          <div>
            <dt>BEI 1M move</dt>
            <dd className={deltaClass(beiMonth)}>{bpsText(beiMonth)}</dd>
          </div>
          <div>
            <dt>5Y5Y forward inflation</dt>
            <dd>{fmtValue(decomp.forward_inflation_5y5y, "%", 2)}</dd>
          </div>
        </dl>
        <p>
          Rule: if real yield contribution exceeds breakeven contribution, the
          bond move is led by real-rate repricing. If breakeven dominates,
          inflation compensation is the primary driver.
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
  const maxContribution = Math.max(
    1,
    ...rows.flatMap((row) => [
      Math.abs(toFiniteNumber(row.real_10y_bps, 0)),
      Math.abs(toFiniteNumber(row.breakeven_10y_bps, 0)),
      Math.abs(toFiniteNumber(row.residual_bps, 0)),
    ]),
  );
  return (
    <div className={styles.decompAttribution}>
      <div className={styles.decompFormulaTop}>
        <h3>Move attribution · bps</h3>
        <span>Actual FRED history</span>
      </div>
      <div className={styles.decompTableWrap}>
        <table className={styles.decompMoveTable}>
          <thead>
            <tr>
              <th>Window</th>
              <th>10Y total</th>
              <th>Real 10Y</th>
              <th>Breakeven</th>
              <th>Residual</th>
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
                <td className={deltaClass(row.real_10y_bps)}>
                  {fmtSigned(row.real_10y_bps, "", 1)}
                </td>
                <td className={deltaClass(row.breakeven_10y_bps)}>
                  {fmtSigned(row.breakeven_10y_bps, "", 1)}
                </td>
                <td className={deltaClass(row.residual_bps)}>
                  {fmtSigned(row.residual_bps, "", 1)}
                </td>
                <td>{row.driver ?? "n/a"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={styles.decompBars}>
        {[
          ["Real yield", oneMonth?.real_10y_bps],
          ["Breakeven", oneMonth?.breakeven_10y_bps],
          ["Residual", oneMonth?.residual_bps],
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
        Conclusion: over 1M, Real yield explains{" "}
        {fmtValue(oneMonth?.real_10y_bps, "bps", 1)} and breakeven explains{" "}
        {fmtValue(oneMonth?.breakeven_10y_bps, "bps", 1)} of the 10Y move.
      </p>
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
          <span>Market inflation</span>
          <strong>5Y5Y {fmtValue(decomp.forward_inflation_5y5y, "%", 2)}</strong>
          <p>FRED forward inflation compensation; useful for impulse checks.</p>
        </article>
        <article>
          <span>Survey source</span>
          <strong>Unavailable</strong>
          <p>SEP / survey feeds are not wired, so the page does not fill them.</p>
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
  const policy = snapshot.policy;
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

      <RatesSection id="scorecard" title="Scorecard" eyebrow="Editable weights">
        <RatesScorecard scorecard={scorecard} />
      </RatesSection>

      <RatesSection
        id="policy"
        title="Policy"
        status={statusLabel(policy?.status)}
      >
        <div className={styles.compactGrid}>
          <Tile
            tile={{
              label: "EFFR",
              value: policy?.effr,
              unit: "%",
              status: policy?.status ?? "partial",
            }}
          />
          <Tile
            tile={{
              label: "SOFR",
              value: policy?.sofr,
              unit: "%",
              status: policy?.status ?? "partial",
            }}
          />
          {(policy?.plumbing ?? []).map((tile) => (
            <Tile key={tile.label} tile={tile} />
          ))}
        </div>
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
              <strong>{source.label}</strong>
              <span>{source.latest_obs_date ?? "n/a"}</span>
              <span>{statusLabel(source.status)}</span>
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
