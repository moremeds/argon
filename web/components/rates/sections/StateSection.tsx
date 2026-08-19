import styles from "../RatesDesk.module.css";
import { toFiniteNumber } from "../format";
import type { MacroStateSummary } from "../types";

// The state is deliberately not a score. It answers four separate questions -- what
// regime, which way, how fast, and how much of that we actually know -- and each is
// rendered on its own so a reader cannot collapse them back into one number.

function readableState(state: string): string {
  return state.replace(/_/g, " ");
}

function directionArrow(direction: string): string {
  if (direction === "RISING") return "↑";
  if (direction === "FALLING") return "↓";
  if (direction === "FLAT") return "→";
  return "?";
}

function directionToneClass(direction: string): string {
  if (direction === "RISING") return styles.deltaPositive;
  if (direction === "FALLING") return styles.deltaNegative;
  return styles.deltaNeutral;
}

function fmtConfidence(value: unknown): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  return `${(n * 100).toFixed(0)}%`;
}

function fmtVelocity(value: unknown, unit: string): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)} ${unit}`;
}

function fmtInstant(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
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

/** No state exists. Say that, and say nothing else -- there is nothing to lean on. */
function NoState({ reason }: { reason: string }) {
  return (
    <div className={styles.stateMissing} data-testid="rates-state-missing">
      <p className={styles.eyebrow}>Policy / rates state</p>
      <strong>Not computed</strong>
      <p>{reason}</p>
    </div>
  );
}

export function StateSection({
  state,
  errorMessage,
}: {
  state: MacroStateSummary | null | undefined;
  errorMessage?: string;
}) {
  if (!state) {
    return (
      <NoState
        reason={
          errorMessage ??
          "No policy/rates domain state has been stored for this instant. The scorecard below is the legacy rule score and is not a substitute for one."
        }
      />
    );
  }

  const velocity = state.velocity ?? [];
  const reasons = state.confidence_reasons ?? [];
  const contradictions = state.contradictions ?? [];
  const notes = state.notes ?? [];

  return (
    <div className={styles.stateBlock} data-testid="rates-state-block">
      <div className={styles.stateHero}>
        <div className={styles.stateHeadline}>
          <p className={styles.eyebrow}>
            Policy / rates state · {state.engine_version}
          </p>
          <strong data-testid="rates-state-label">
            {readableState(state.state)}
          </strong>
          <span
            className={[
              styles.stateDirection,
              directionToneClass(state.direction),
            ].join(" ")}
            data-testid="rates-state-direction"
          >
            {directionArrow(state.direction)} {state.direction}
          </span>
        </div>
        <dl className={styles.stateMeta}>
          <div>
            <dt>Confidence</dt>
            <dd data-testid="rates-state-confidence">
              {fmtConfidence(state.confidence)}
            </dd>
          </div>
          <div>
            <dt>Freshness</dt>
            <dd data-testid="rates-state-freshness">
              {state.freshness === "stale"
                ? `Stale · ${state.age_hours.toFixed(1)}h since computed`
                : "Fresh"}
            </dd>
          </div>
          <div>
            <dt>Answers for</dt>
            <dd>{fmtInstant(state.as_of)} HKT</dd>
          </div>
        </dl>
      </div>

      <div className={styles.stateColumns}>
        <section className={styles.statePanel}>
          <h3>Velocity</h3>
          {velocity.length ? (
            <dl className={styles.stateRows}>
              {velocity.map((item) => (
                <div key={item.metric}>
                  <dt>
                    {item.metric}
                    <small>{item.window_months}m window</small>
                  </dt>
                  <dd>
                    {item.unavailable_reason
                      ? item.unavailable_reason
                      : fmtVelocity(item.value, item.unit)}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className={styles.stateEmptyNote}>
              No velocity metric was computable from the evidence available at
              this instant.
            </p>
          )}
        </section>

        <section className={styles.statePanel}>
          {/* Confidence is a product of knowledge terms, not of signal size. Printing
              every multiplicand is what lets a reader argue with the number. */}
          <h3>Why this confidence</h3>
          {reasons.length ? (
            <dl className={styles.stateRows}>
              {reasons.map((reason) => (
                <div key={reason.term}>
                  <dt>
                    {reason.term}
                    <small>×{toFiniteNumber(reason.value).toFixed(2)}</small>
                  </dt>
                  <dd>{reason.detail}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className={styles.stateEmptyNote}>
              The engine recorded no confidence terms for this state.
            </p>
          )}
        </section>

        <section className={styles.statePanel}>
          <h3>Contradictions</h3>
          {contradictions.length ? (
            <ul
              className={styles.stateContradictions}
              data-testid="rates-state-contradictions"
            >
              {contradictions.map((item) => (
                <li key={`${item.rule}:${item.detail}`}>
                  <strong>{item.rule}</strong>
                  <span>{item.detail}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.stateEmptyNote}>
              No contradiction rule fired on the evidence in force.
            </p>
          )}
        </section>
      </div>

      {notes.length ? (
        <ul className={styles.stateNotes}>
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}

      <p className={styles.stateFooter}>
        Stood on {state.evidence_count} observation
        {state.evidence_count === 1 ? "" : "s"} ·{" "}
        <a href={state.detail_path} target="_blank" rel="noreferrer">
          inspect the evidence
        </a>
      </p>
    </div>
  );
}
