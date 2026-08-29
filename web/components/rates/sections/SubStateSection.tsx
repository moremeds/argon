import type { components } from "@/lib/types";
import type { BoardQuestions } from "@/components/macro/domain/BoardPanel";

import styles from "../RatesDesk.module.css";
import { RatesSection } from "../RatesSection";

type SubState = components["schemas"]["MacroSubStateItem"];
type VelocityItem = NonNullable<SubState["velocity"]>[number];

/**
 * The board's three SUB-STATE panels on tab 02.
 *
 * ### Where the data comes from, and why it is a second publisher
 *
 * `/api/rates/snapshot` carries supply, positioning and plumbing as READINGS — auction
 * rows, percentile tiles, a spread. The engine's own verdict on each of those — whether
 * it is in range, which way it is moving, and how confident it is — lives on
 * `/api/macro/rates` as `sub_states`, and tab 02 never asked for it. The board prints
 * both, and it is right to: "0 of 7 tenors at 4-quarter issuance highs" is a fact about
 * the tape, and `IN_RANGE · FLAT` is the desk's reading of it. Showing the readings alone
 * makes the reader do the engine's job; showing the verdict alone hides what it stands on.
 *
 * ### Why `role` maps to a title here rather than being printed
 *
 * The engine's third role is `plumbing` and the board's third panel is `Funding`. Those
 * are the same thing under two vocabularies — the engine names the mechanism, the board
 * names the question an operator is asking — and the desk answers to the operator. The
 * mapping is explicit so a new role arriving from the engine fails loudly here rather
 * than rendering a raw enum as a heading.
 */
const ROLE_TITLES: Record<string, { title: string; eyebrow: string }> = {
  supply: {
    title: "Supply SUB-STATE",
    eyebrow: "Coupon issuance across the curve",
  },
  positioning: {
    title: "Positioning SUB-STATE · 10Y futures",
    eyebrow: "CFTC TFF · net % open interest by participant",
  },
  plumbing: {
    title: "Funding SUB-STATE",
    eyebrow: "SOFR − EFFR, and the balances behind it",
  },
};

function fmtVelocity(v: VelocityItem): string {
  if (v.unavailable_reason) return "n/a";
  const n = Number(v.value);
  if (!Number.isFinite(n)) return "n/a";
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  const abs = Math.abs(n);
  const unit =
    v.unit === "basis_points"
      ? "bp"
      : v.unit === "pct_open_interest"
        ? "pp"
        : "";
  const digits = v.unit === "basis_points" ? 0 : 2;
  return `${sign}${abs.toFixed(digits)}${unit}`;
}

/** `10-Year|Note` and `043602|asset_mgr_net_pct_oi` both carry a pipe. Only the second
 *  half is meaningful to a reader in the second case, and only the first in the first —
 *  so the whole id is shown and the pipe is spaced, rather than guessing which side to
 *  drop and being wrong on one of the two families. */
function readableSeries(id: string): string {
  return id.replace("|", " · ");
}

function stateTone(state: string): string {
  const normalized = state.toUpperCase();
  if (normalized === "UNKNOWN") return "state neust";
  if (normalized.includes("STRESS") || normalized.includes("OUT"))
    return "state critst";
  if (normalized.includes("WARN") || normalized.includes("TIGHT"))
    return "state warnst";
  return "state okst";
}

export function SubStateSection({
  subState,
  children,
}: {
  subState: SubState;
  /** The readings the verdict stands on — the auction/fiscal tiles, the positioning
   *  percentile rows. Passed in rather than fetched here so this component stays a
   *  renderer of one engine verdict and the snapshot half keeps its own shape. */
  children?: React.ReactNode;
}) {
  const meta = ROLE_TITLES[subState.role];
  const title = meta?.title ?? `${subState.role} SUB-STATE`;
  const velocity = subState.velocity ?? [];
  const series = subState.series_ids ?? [];
  const questions: BoardQuestions =
    subState.role === "supply"
      ? ["Q4", "Q5"]
      : subState.role === "positioning"
        ? ["Q5"]
        : ["Q4"];

  return (
    <RatesSection
      id={`substate-${subState.role}`}
      title={title}
      eyebrow={meta?.eyebrow}
      questions={questions}
      basis="COMPUTED"
      source={`/api/macro/rates.sub_states[role=${subState.role}]`}
      showQuestions={false}
    >
      <span className={stateTone(subState.state)}>
        {subState.state} · {subState.direction}
      </span>
      {subState.unavailable_reason ? (
        // A sub-state that could not be computed says why. UNKNOWN is not NEUTRAL, and
        // an empty panel is not a calm one.
        <div className={styles.notePanel}>
          <p>{subState.unavailable_reason}</p>
        </div>
      ) : (
        <>
          <div className={styles.compactGrid}>
            {velocity.map((v) => (
              <article className={styles.kpiTile} key={v.metric}>
                <span>{readableSeries(v.metric)}</span>
                <strong>{fmtVelocity(v)}</strong>
                <small>
                  {v.window_months === 0
                    ? "latest"
                    : `${v.window_months}m window`}
                </small>
              </article>
            ))}
          </div>
          <p className="cap">
            {series.length} load-bearing{" "}
            {series.length === 1 ? "series" : "series"} —{" "}
            {series.map(readableSeries).join(", ")}. Latest observation{" "}
            {subState.latest_period_end ?? "n/a"}; engine confidence{" "}
            {subState.confidence ?? "n/a"}.
          </p>
          {children}
        </>
      )}
    </RatesSection>
  );
}
