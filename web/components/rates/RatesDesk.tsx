import type { components } from "@/lib/types";
import { RatesCurveChart } from "./RatesCurveChart";
import styles from "./RatesDesk.module.css";
import { RatesScorecard } from "./RatesScorecard";
import { RatesSection } from "./RatesSection";
import { fmtSigned, fmtValue, statusLabel } from "./format";

type Snapshot = components["schemas"]["RatesSnapshotResponse"];
type SummaryTile = components["schemas"]["RatesSummaryTile"];

const NAV = [
  ["summary", "Summary"],
  ["curve", "Curve"],
  ["decomp", "Decomp"],
  ["scorecard", "Scorecard"],
  ["policy", "Policy"],
  ["supply", "Supply"],
  ["positioning", "Positioning"],
  ["cross", "Cross"],
  ["events", "Events"],
  ["sources", "Sources"],
  ["synthesis", "Synthesis"],
] as const;

function Tile({ tile }: { tile: SummaryTile }) {
  return (
    <article className={styles.kpiTile}>
      <span>{tile.label}</span>
      <strong>{fmtValue(tile.value, tile.unit, tile.unit === "bps" ? 1 : 2)}</strong>
      <small>{fmtSigned(tile.delta_1d, tile.unit === "bps" ? "bps 1D" : "1D")}</small>
    </article>
  );
}

export function RatesDesk({ snapshot }: { snapshot: Snapshot | null }) {
  if (!snapshot) {
    return (
      <div className={styles.page}>
        <div className={styles.emptyState}>
          <p className={styles.eyebrow}>US Rates Factor Desk</p>
          <h1>Rates snapshot not computed</h1>
          <p>Run the live FRED backfill or wait for the scheduled worker refresh.</p>
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

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>US Treasury Bonds Monitor</p>
          <h1>US Rates Factor Desk</h1>
          <p className={styles.subhead}>
            Snapshot {snapshot.as_of} · computed {new Date(snapshot.computed_at).toLocaleString()}
          </p>
        </div>
        <nav className={styles.nav} aria-label="Rates sections">
          {NAV.map(([id, label]) => (
            <a key={id} href={`#${id}`}>
              {label}
            </a>
          ))}
        </nav>
      </header>

      <RatesSection id="summary" title="Summary" eyebrow="Live FRED curve">
        <div className={styles.kpiGrid}>
          {summary.map((tile) => (
            <Tile key={tile.label} tile={tile} />
          ))}
        </div>
      </RatesSection>

      <RatesSection id="curve" title="Yield Curve" eyebrow="Nominal Treasury curve">
        <RatesCurveChart points={curve.points ?? []} />
        <div className={styles.metricStrip}>
          {(curve.slopes ?? []).map((slope) => (
            <span key={slope.label}>
              {slope.label} <strong>{fmtValue(slope.value_bps, "bps", 1)}</strong>
            </span>
          ))}
        </div>
      </RatesSection>

      <RatesSection id="decomp" title="Decomposition" eyebrow="10Y nominal / real / inflation">
        <div className={styles.compactGrid}>
          <Tile tile={{ label: "Nominal 10Y", value: snapshot.decomposition?.nominal_10y, unit: "%", status: "ok" }} />
          <Tile tile={{ label: "Real 10Y", value: snapshot.decomposition?.real_10y, unit: "%", status: "ok" }} />
          <Tile tile={{ label: "Breakeven", value: snapshot.decomposition?.breakeven_10y, unit: "%", status: "ok" }} />
          <Tile tile={{ label: "5Y5Y", value: snapshot.decomposition?.forward_inflation_5y5y, unit: "%", status: "partial" }} />
        </div>
      </RatesSection>

      <RatesSection id="scorecard" title="Scorecard" eyebrow="Editable weights">
        <RatesScorecard
          scorecard={
            snapshot.scorecard ?? {
              duration_stance: "NEUTRAL",
              curve_stance: "NEUTRAL",
              groups: [],
            }
          }
        />
      </RatesSection>

      <RatesSection id="policy" title="Policy" status={statusLabel(policy?.status)}>
        <div className={styles.compactGrid}>
          <Tile tile={{ label: "EFFR", value: policy?.effr, unit: "%", status: policy?.status ?? "partial" }} />
          <Tile tile={{ label: "SOFR", value: policy?.sofr, unit: "%", status: policy?.status ?? "partial" }} />
          {(policy?.plumbing ?? []).map((tile) => (
            <Tile key={tile.label} tile={tile} />
          ))}
        </div>
      </RatesSection>

      <RatesSection id="supply" title="Supply" status={statusLabel(supply?.status)}>
        <div className={styles.notePanel}>
          <strong>{statusLabel(supply?.status)}</strong>
          {(supply?.notes?.length ? supply.notes : ["Treasury auction feed not wired in Phase 1."]).map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      </RatesSection>

      <RatesSection id="positioning" title="Positioning" status={statusLabel(positioning?.status)}>
        <div className={styles.notePanel}>
          <strong>{statusLabel(positioning?.status)}</strong>
          <p>CFTC/TIC feeds not wired in Phase 1.</p>
        </div>
      </RatesSection>

      <RatesSection id="cross" title="Cross-Market" status={statusLabel(cross?.status)}>
        <div className={styles.compactGrid}>
          {(cross?.rows ?? []).map((tile) => (
            <Tile key={tile.label} tile={tile} />
          ))}
        </div>
      </RatesSection>

      <RatesSection id="events" title="Events" status={snapshot.events?.length ? "Live" : "Unavailable"}>
        <div className={styles.notePanel}>
          {snapshot.events?.length ? (
            snapshot.events.map((event) => <p key={event.label}>{event.label}</p>)
          ) : (
            <p>Official events/news source not wired in Phase 1.</p>
          )}
        </div>
      </RatesSection>

      <RatesSection id="sources" title="Source Freshness" eyebrow="FRED observations">
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
