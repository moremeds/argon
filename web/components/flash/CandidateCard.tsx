import { PayoffChart } from "./PayoffChart";
import type { CandidateView, Invalidation } from "./view";
import styles from "./flash.module.css";

/** U+2212, never a hyphen: a minus that reads as punctuation is a wrong number. */
function usd(n: number): string {
  return (
    (n < 0 ? "−" : "+") +
    "$" +
    Math.abs(n).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
}

/**
 * A level, a pair of levels, or — from a v1 document — the sentence the run
 * wrote instead of a level. A sentence is printed as it arrived: it is the
 * only thing that document has, and an em dash over the top of it was the bug.
 */
function level(x?: Invalidation | Invalidation[] | string): string {
  if (!x) return "—";
  if (typeof x === "string") return x;
  const list = Array.isArray(x) ? x : [x];
  if (list.length === 0) return "—";
  return list.map((i) => `${i.level} ${i.side}`).join(" / ");
}

/**
 * One structure, per contract.
 *
 * Only DERIVED economics appear — net, max gain, max loss, breakeven — and
 * only from the tenant's own gated arithmetic. When the structure is unpriced
 * the whole pricing row is replaced by the recorded reason and no chart is
 * drawn: a payoff curve over a price nobody could get is a picture of nothing.
 */
export function CandidateCard({ candidate }: { candidate: CandidateView }) {
  const c = candidate;
  const priced = c.pricing.kind === "priced" ? c.pricing : null;
  const head: string[] = [];
  if (c.expiry) head.push(`Exp ${c.expiry}`);
  if (c.dte != null) head.push(`${c.dte} DTE`);
  if (c.spot != null) head.push(`Spot ${c.spot.toFixed(2)}`);
  if (c.width != null) head.push(`Width ${c.width.toFixed(2)}`);

  return (
    <article className={styles.cand} data-testid={`flash-candidate-${c.id}`}>
      <div className={styles.candhead}>
        <span className={styles.tkr}>{c.ticker}</span>
        <span className={styles.chip}>{c.strategy.replace(/_/g, " ")}</span>
        {head.length > 0 ? (
          <span
            className={styles.mono}
            style={{ fontSize: 11, color: "var(--text-muted)" }}
          >
            {head.join(" · ")}
          </span>
        ) : null}
        <div className={styles.lvls}>
          <Level label="Entry" value={level(c.entry)} />
          <Level label="Target" value={level(c.target)} tone="secondary" />
          <Level
            label="Invalidation"
            value={level(c.invalidation)}
            tone="negative"
          />
        </div>
      </div>

      <div className={styles.candbody}>
        <div className={styles.legwrap}>
          <table>
            <thead>
              <tr>
                <th>Action</th>
                <th>Right</th>
                <th className="n">Strike</th>
                <th>Expiry</th>
                <th className="n">Mid</th>
              </tr>
            </thead>
            <tbody>
              {c.legs.map((leg, i) => (
                <tr key={`${leg.right}-${leg.strike}-${i}`}>
                  <td
                    className={styles.mono}
                    style={{
                      color:
                        leg.action === "buy"
                          ? "var(--positive)"
                          : "var(--negative)",
                    }}
                  >
                    {leg.action}
                  </td>
                  <td
                    className={styles.mono}
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {leg.right}
                  </td>
                  <td className="n">{leg.strike.toFixed(2)}</td>
                  <td
                    className={styles.mono}
                    style={{ color: "var(--text-muted)" }}
                  >
                    {leg.expiry}
                  </td>
                  <td className="n">
                    {leg.mid == null ? "—" : leg.mid.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {priced ? (
            <div className={styles.pricing}>
              <Money
                label={priced.net >= 0 ? "Net debit" : "Net credit"}
                value={`$${Math.abs(priced.net).toFixed(2)}`}
                sub="per share"
              />
              <Money
                label="Max gain"
                value={priced.maxGain == null ? "unbounded" : usd(priced.maxGain)}
                sub="per contract"
                tone="positive"
              />
              <Money
                label="Max loss"
                value={
                  priced.maxLoss == null ? "unbounded" : usd(-priced.maxLoss)
                }
                sub="per contract"
                tone="negative"
              />
            </div>
          ) : (
            <p className={styles.note} style={{ padding: "9px 0 0" }}>
              Not priced — {c.pricing.kind === "priced" ? "" : c.pricing.reason}
            </p>
          )}
          {c.unchecked ? (
            <p className={styles.note} style={{ padding: "9px 0 0" }}>
              Unchecked: {c.unchecked}
            </p>
          ) : null}
        </div>

        <div className={styles.pnlwrap}>
          {priced ? (
            <>
              <span
                className={styles.lbl}
                style={{ display: "block", marginBottom: 2 }}
              >
                Payoff at expiry vs spot · $ per contract
              </span>
              <PayoffChart candidate={c} />
            </>
          ) : null}
        </div>
      </div>

      {c.rationale || c.id ? (
        <div className={styles.rationale}>
          {c.rationale ? <p>{c.rationale}</p> : null}
          <span className={styles.cid}>{c.id}</span>
        </div>
      ) : null}
    </article>
  );
}

function Level({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "secondary" | "negative";
}) {
  const color =
    tone === "negative"
      ? "var(--negative)"
      : tone === "secondary"
        ? "var(--text-secondary)"
        : undefined;
  return (
    <div>
      <span className={styles.lbl}>{label}</span>
      <span
        className={styles.mono}
        style={{ fontSize: 13, fontWeight: 700, color }}
      >
        {value}
      </span>
    </div>
  );
}

function Money({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  tone?: "positive" | "negative";
}) {
  const color =
    tone === "positive"
      ? "var(--positive)"
      : tone === "negative"
        ? "var(--negative)"
        : undefined;
  return (
    <div>
      <span className={styles.lbl}>{label}</span>
      <span
        className={styles.mono}
        style={{ fontSize: 16, fontWeight: 700, color }}
      >
        {value}
      </span>
      <span
        className={styles.mono}
        style={{ fontSize: 9.5, color: "var(--text-muted)" }}
      >
        {sub}
      </span>
    </div>
  );
}
