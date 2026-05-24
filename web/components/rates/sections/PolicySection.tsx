import styles from "../RatesDesk.module.css";
import { fmtValue, toFiniteNumber } from "../format";
import type { Policy, PolicyPathPoint } from "../types";

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

export function PolicySection({ policy }: { policy: Policy }) {
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
