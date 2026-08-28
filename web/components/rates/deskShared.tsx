import styles from "./RatesDesk.module.css";
import { RatesSection } from "./RatesSection";
import { fmtSigned, fmtValue, statusLabel } from "./format";
import { toFiniteNumber } from "./format";
import type { Snapshot, SummaryTile } from "./types";

/**
 * What `FedDesk` (macro tab 01) and `CurveDesk` (macro tab 02) both need.
 *
 * The old `/rates` page was one component, `RatesDesk.tsx`, that WAS the page shell.
 * Splitting it across two routes duplicated four things -- the page header, the empty
 * state, the KPI tile, and source freshness -- so they live here rather than in two
 * copies that drift.
 *
 * These stay under `components/rates/` on purpose: both desks render
 * `components/rates/sections/*`, and `components/macro/*` must never import from
 * `components/rates/*` (plan 2026-08-27 §7). A primitive that a third macro tab needs
 * gets LIFTED into `components/macro/`, taking its CSS with it -- it is not
 * cross-imported from here.
 */

/**
 * Settle one publisher's fetch instead of letting it throw.
 *
 * Carried verbatim from `app/rates/page.tsx`, where the comment beside the two calls
 * explained why they settle independently: the snapshot and the policy comparison come
 * from different jobs, so if the policy release ingest is down the curve is still a
 * fact and the tab should say which half is missing rather than blanking both. The
 * same holds now that the two halves are two routes -- tab 01 makes both calls, and one
 * dead publisher there must still cost one panel, not the tab.
 */
export async function settle<T>(
  load: () => Promise<T | null>,
  label: string,
): Promise<{ value: T | null; error?: string }> {
  try {
    return { value: await load() };
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown API error";
    return { value: null, error: `The ${label} request failed: ${detail}` };
  }
}

/** One tier of a desk's in-page nav. Each desk owns its own array: `NAV` drives the
 *  anchors, so a desk may only advertise the sections it actually renders. */
export type NavGroup = {
  id: string;
  tier: string;
  lede: string;
  items: readonly (readonly [string, string])[];
};

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

export function sourcePublisher(seriesId: string): string {
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

export function fredSeriesUrl(seriesId: string): string {
  if (isClevelandFedSeries(seriesId)) {
    return "https://www.clevelandfed.org/indicators-and-data/inflation-expectations";
  }
  return `https://fred.stlouisfed.org/series/${encodeURIComponent(seriesId)}`;
}

export function sourceLinkLabel(seriesId: string): string {
  if (isClevelandFedSeries(seriesId)) return `Cleveland Fed ${seriesId}`;
  return `FRED ${seriesId}`;
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

export function Tile({ tile }: { tile: SummaryTile }) {
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

/**
 * The desk header: title lockup, snapshot provenance line, and the tier nav.
 *
 * The nav is built from the caller's `NAV` rather than a shared list, so each tab
 * anchors only into its own sections.
 */
export function DeskHeader({
  title,
  subtitle,
  snapshot,
  nav,
  navLabel,
}: {
  title: string;
  subtitle: string;
  snapshot: Snapshot;
  nav: readonly NavGroup[];
  navLabel: string;
}) {
  return (
    <header className={styles.header}>
      <div className={styles.headerTop}>
        <div className={styles.titleLockup}>
          <h1>
            {title}
            <span>.</span>
          </h1>
          <p>{subtitle}</p>
        </div>
        <p className={styles.headerMeta}>{snapshotMeta(snapshot)}</p>
      </div>
      <nav className={styles.nav} aria-label={navLabel}>
        {nav.map((group) => (
          <span key={group.id} className={styles.navGroup}>
            <a href={`#${group.id}`} className={styles.navGroupLabel}>
              {group.tier}
            </a>
            {group.items.map(([id, label]) => (
              <a key={id} href={`#${id}`}>
                {label}
              </a>
            ))}
          </span>
        ))}
      </nav>
    </header>
  );
}

/**
 * No snapshot. The two failures stay distinct: the API answering with an error is not
 * the same fact as the worker never having computed a snapshot, and the headings differ
 * so a browser test can tell which one it is looking at.
 */
export function DeskEmptyState({
  eyebrow,
  errorMessage,
}: {
  eyebrow: string;
  errorMessage?: string;
}) {
  const hasError = Boolean(errorMessage);
  return (
    <div className={styles.page}>
      <div className={styles.emptyState}>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h1>
          {hasError ? "Rates API unavailable" : "Rates snapshot not computed"}
        </h1>
        <p>
          {hasError
            ? errorMessage
            : "Run the live FRED backfill or wait for the scheduled worker refresh."}
        </p>
      </div>
    </div>
  );
}

/**
 * Source freshness, rendered on BOTH desks deliberately.
 *
 * It is provenance for the one `RatesSnapshotResponse` that each tab already fetched,
 * so showing it twice costs nothing — no extra request, no second clock. Hiding it from
 * tab 01 would be the expensive choice: the policy and supply panels there read the
 * same FRED feed, so a stale publisher would go invisible on the tab that depends on
 * it. Two anchors named `sources` never collide because these are two documents.
 */
export function SourceFreshnessSection({ snapshot }: { snapshot: Snapshot }) {
  return (
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
            <a href={fredSeriesUrl(source.id)} target="_blank" rel="noreferrer">
              {sourceLinkLabel(source.id)}
            </a>
          </div>
        ))}
      </div>
    </RatesSection>
  );
}
