import { rankPhrase } from "@/components/stock/panels/FundamentalAnchorBand";
import type { components } from "@/lib/types";

export const dynamic = "force-dynamic";

type Candidate = components["schemas"]["ValueCandidate"];
type ValueResponse =
  Awaited<ReturnType<typeof import("@/lib/api").api.scannerValue>> | undefined;

function num(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function price(v: string | number | null | undefined): string {
  const n = num(v);
  return n === null ? "na" : n.toFixed(2);
}

/** How far under its own `buy_below` the name sits, as a percentage.
 *
 * Reported per row and NEVER sorted on. Depth is a distance inside ONE name's
 * band, so 8% under BAX's buy_below and 8% under BRO's are not the same
 * quantity — the two bands were built from different histories with different
 * widths. Comparing them is the cross-sectional claim this tab exists to avoid.
 */
function depth(c: Candidate): string {
  const spot = num(c.spot);
  const buy = num(c.buy_below);
  if (spot === null || buy === null || buy === 0) return "na";
  return `${(((buy - spot) / buy) * 100).toFixed(1)}%`;
}

/** Every name whose price sits at or below its OWN `buy_below` level.
 *
 * WHY THIS TAB EXISTS
 * -------------------
 * `valuation_anchors` had exactly one read path — `latest_for_ticker` — so the
 * only fundamental signal in the stack that measured (`sales_to_ev`
 * within-ticker, market-neutral 2q IC +0.0744, t 5.77) could only be seen by a
 * reader who already suspected the name. On 2026-08-17, 98 of 336 banded names
 * were inside their own buy zone and no screen in the product showed that.
 *
 * WHY IT IS A LIST AND NOT A LEADERBOARD
 * --------------------------------------
 * Ranking names against each other on value measured INVERTED in this universe
 * (`book_to_price` 2q IC -0.0365, t -2.32). Every row here is an independent
 * single-name verdict; putting them on one screen does not compare them, and
 * the tab must never grow a sort control over `spot_percentile` or `depth`.
 * The header says so on screen, because a table of numbers reads as a ranking
 * whatever the code intends.
 */
export default function ValueSubTab({ value }: { value: ValueResponse }) {
  if (!value) {
    return (
      <div className="theta-panel">
        <div className="theta-empty">
          Valuation bands unavailable — no active fundamental method version.
        </div>
      </div>
    );
  }

  const { candidates, banded_universe, as_of, engine_version } = value;
  const entrants = candidates.filter((c) => c.entered === true).length;

  return (
    <div className="theta-panel">
      <div className="theta-panel-bar">
        <span className="theta-panel-title">
          In their own buy zone
          <span className="theta-subtle">
            spot at or below `buy_below`, from each name&apos;s OWN valuation
            history
          </span>
        </span>
        <span className="theta-count">
          {candidates.length} / {banded_universe} banded
        </span>
        {entrants > 0 ? (
          <span className="theta-count">{entrants} newly entered</span>
        ) : null}
        <span className="theta-subtle" style={{ marginLeft: "auto" }}>
          as of {as_of ?? "na"} · {engine_version}
        </span>
      </div>

      {/* Not decoration. A dense table of tickers and percentages reads as a
          ranking by default, and the ordering here deliberately carries no
          valuation information at all. */}
      <div
        className="theta-subtle"
        style={{
          padding: "10px 14px",
          borderBottom: "1px solid var(--border-dim)",
          lineHeight: 1.6,
        }}
      >
        Each row compares one company to <strong>its own past</strong>, never to
        the others. The list is <strong>unranked</strong> — newly-entered names
        first, then alphabetical. Ranking names against each other on value
        measured inverted in this universe, so a &ldquo;cheapest first&rdquo;
        ordering would point at the half that then underperforms.
      </div>

      {candidates.length === 0 ? (
        <div className="theta-empty">
          No name is inside its own buy zone at this as_of.
        </div>
      ) : (
        <div className="theta-scroll">
          <table className="theta-table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Method</th>
                <th>Spot</th>
                <th>Buy below</th>
                <th>Under</th>
                <th>vs own history</th>
                <th>Conf</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c) => {
                const pct = num(c.spot_percentile);
                return (
                  <tr key={c.ticker}>
                    <td>
                      <a
                        href={`/stock/${c.ticker}?tab=fundamentals`}
                        style={{ color: "var(--accent-bg)" }}
                      >
                        {c.ticker}
                      </a>
                      {c.entered === true ? (
                        <span className="theta-count" style={{ marginLeft: 8 }}>
                          NEW
                        </span>
                      ) : null}
                      {/* `entered === null` is UNKNOWN, not "not new": the name
                          had no prior band to compare against. Badging it NEW
                          would have flagged 29 names on 2026-08-17 that were
                          there because the panel widened, not because a price
                          moved. */}
                      {c.entered === null ? (
                        <span
                          className="theta-subtle"
                          style={{ marginLeft: 8 }}
                          title="No prior band within 30 days — whether it just entered is unknown"
                        >
                          first band
                        </span>
                      ) : null}
                    </td>
                    <td className="theta-subtle">{c.method}</td>
                    <td>{price(c.spot)}</td>
                    <td>{price(c.buy_below)}</td>
                    <td>{depth(c)}</td>
                    {/* Never the raw percentile: it is a YIELD percentile, so
                        0.80 means CHEAP and prints backwards to anyone reading
                        it as a price rank. `rankPhrase` is the one place that
                        translation lives. */}
                    <td className="theta-subtle" style={{ textAlign: "left" }}>
                      {pct === null
                        ? "na"
                        : rankPhrase(pct, c.history_quarters)}
                    </td>
                    {/* Dimmed rather than colour-coded: `low` is a statement
                        about how much of the band we believe, not a bearish or
                        bullish signal, and a red/green treatment would read as
                        one. The reasons are the tooltip — "medium because the
                        name has no sector on file" is actionable, "medium" is
                        not. */}
                    <td
                      className={
                        c.confidence === "high" ? undefined : "theta-subtle"
                      }
                      title={c.confidence_reasons.join(" · ")}
                    >
                      {c.confidence}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
