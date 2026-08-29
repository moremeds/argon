import type { components } from "@/lib/types";
import { BoardRead } from "@/components/macro/domain/BoardPanel";

import { RatesCurveChart } from "./RatesCurveChart";
import styles from "./RatesDesk.module.css";
import { RatesScorecard } from "./RatesScorecard";
import { RatesSection } from "./RatesSection";
import { DeskEmptyState, DeskHeader } from "./deskShared";
import { fmtValue } from "./format";
import {
  ClevelandDecompositionSection,
  MoveAttributionSection,
  NominalDecompositionSection,
} from "./sections/DecompositionSection";
import { PositioningSection } from "./sections/PositioningSection";
import { SubStateSection } from "./sections/SubStateSection";
import {
  AuctionDemandSection,
  SupplyFiscalSection,
} from "./sections/SupplySection";
import type {
  Decomposition,
  Policy,
  Positioning,
  SlopeMetric,
  Snapshot,
  Supply,
} from "./types";

/**
 * Macro desk tab 02 — Rates · Curve.
 *
 * The market's half of the old `/rates` page: what the traded curve prices, what moved
 * it, and the positioning and cross-market plumbing that stands beside it. The Fed's own
 * state and the four published policy paths live on tab 01, `FedDesk`.
 *
 * `/rates` 308s here rather than to tab 01 (`next.config.mjs`). That used to be the reason
 * this tab kept the old page's "US Rates Factor Desk" lockup — an inbound link should land
 * somewhere that still says its name. The board settled it the other way on 2026-08-28:
 * its t2 opens with `Rates · Curve` and nothing above it, and the tab bar one line up
 * already says the same words, so the lockup was the page announcing itself twice. The
 * old name survives where it is still load-bearing: `DeskEmptyState`'s eyebrow, which is
 * what an inbound link reaches when there is no snapshot to show.
 */
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
    if (value < 50) return "Curve is only lightly positive from bills to 10Y.";
    return "Long end is clearly above bills; the bills-to-10Y spread is wide.";
  }
  if (value < 0)
    return "Inverted spread; front end is leading and duration risk is defensive.";
  if (value < 35)
    return "Flat positive spread; curve has limited carry cushion.";
  if (value < 90)
    return "Normal positive slope; long-end yield pickup is meaningful.";
  return "Steep spread; the long end is well above the front end.";
}

function FundingReadings({ policy }: { policy: Policy }) {
  const spread =
    policy.sofr == null || policy.effr == null
      ? null
      : (Number(policy.sofr) - Number(policy.effr)) * 100;
  return (
    <>
      <div className="big">
        {spread == null ? "n/a" : fmtValue(spread, "bps", 0)}
        <small> SOFR − EFFR</small>
      </div>
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Aggregate</th>
              <th className="num">Level</th>
              <th>Qualifier</th>
            </tr>
          </thead>
          <tbody>
            {(policy.plumbing ?? []).map((row) => (
              <tr key={row.label}>
                <td>{row.label}</td>
                <td className="num">{fmtValue(row.value, row.unit, 2)}</td>
                <td>{row.qualifier ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <BoardRead>
        {policy.plumbing_read ??
          "Funding transmission cannot be interpreted until the plumbing series are available."}
      </BoardRead>
    </>
  );
}

// A slope is the difference between two traded yields and nothing else.  Naming it a
// term premium promotes a shape into an estimate of compensation for duration risk,
// which only a model can produce -- here, the Cleveland Fed's, whose figure appears in
// the decomposition section with its own vintage and its own uncertainty.

export function CurveDesk({
  snapshot,
  errorMessage,
  subStates,
}: {
  snapshot: Snapshot | null;
  errorMessage?: string;
  /**
   * `sub_states` from `/api/macro/rates`, CITED beside the snapshot.
   *
   * A second publisher on a tab whose comment used to say "one publisher", and settled
   * separately for the same reason tab 03 cites the rates domain: an outage in the state
   * engine must cost three verdicts, not the whole curve. Empty when that request failed
   * or the engine has not run — the sub-state panels then show their readings alone.
   */
  subStates?: components["schemas"]["MacroSubStateItem"][] | null;
}) {
  if (!snapshot) {
    return (
      <DeskEmptyState
        eyebrow="US Rates Factor Desk"
        errorMessage={errorMessage}
      />
    );
  }

  const curve = snapshot.curve ?? { points: [], slopes: [] };
  const policy: Policy = snapshot.policy ?? {
    status: "partial",
    plumbing: [],
    implied_path: [],
  };
  const positioning: Positioning = (snapshot.positioning ?? {
    rows: [],
    details: [],
    status: "missing",
  }) as Positioning;
  const supply = snapshot.supply as Supply | undefined;
  // UNKNOWN, not NEUTRAL: an absent scorecard is the absence of a view, and
  // "NEUTRAL" is a view.
  const scorecard = snapshot.scorecard ?? {
    duration_stance: "UNKNOWN",
    curve_stance: "NEUTRAL",
    groups: [],
  };
  const decomposition: Decomposition = snapshot.decomposition ?? {
    status: "missing",
    attribution: [],
  };
  const subStateFor = (role: string) =>
    (subStates ?? []).find((s) => s.role === role);
  const twoYear = (curve.points ?? []).find((point) => point.tenor === "2Y");
  const tenYear = (curve.points ?? []).find((point) => point.tenor === "10Y");

  return (
    <div className={styles.page}>
      <div className="board">
        {/* Board t2. No state pill here, and that is the board's call rather than an
          omission: this tab is the market's side, and the policy/rates state it would
          show belongs to — and is already shown on — tab 01. */}
        <DeskHeader
          title="Rates"
          questions={["Q2", "Q4", "Q5"]}
          standfirst={
            <>
              Yield-curve levels, their drivers, positioning, funding and
              auction demand.
            </>
          }
          snapshot={snapshot}
        />

        <RatesSection
          id="curve"
          title="Yield curve"
          eyebrow="Nominal Treasury curve"
          questions={["Q2", "Q4"]}
          basis="COMPUTED"
          source="/api/rates/snapshot · curve and stored slope deltas"
        >
          <RatesCurveChart points={curve.points ?? []} />
          <div className={styles.slopeCards}>
            {(curve.slopes ?? []).map((slope) => (
              <article
                key={slope.label}
                className={`${styles.slopeCard} chart`}
                data-testid="slope-card"
              >
                <span>{slope.label}</span>
                <strong className="big">
                  {fmtValue(slope.value_bps, "bps", 1)}
                </strong>
                <p>{slopeInterpretation(slope)}</p>
              </article>
            ))}
          </div>
          <div className="grid g2">
            <BoardRead>
              The curve is a set of stored Treasury yields. Its level and shape
              are facts about the tape; the decomposition panels below state
              separately what is inside the 10Y point.
            </BoardRead>
            <div>
              {[
                [tenYear?.delta_1w_bps, twoYear?.delta_1w_bps, "1W"],
                [tenYear?.delta_1m_bps, twoYear?.delta_1m_bps, "1M"],
              ].map(([longEnd, frontEnd, window]) => (
                <div className="arith" key={window}>
                  <span className="arith-factor">
                    <span className="term">
                      {fmtValue(longEnd, "bps", 1)}
                      <small>Δ10Y {window}</small>
                    </span>
                  </span>
                  <span className="arith-factor">
                    <span className="op">−</span>
                    <span className="term">
                      {fmtValue(frontEnd, "bps", 1)}
                      <small>Δ2Y {window}</small>
                    </span>
                  </span>
                  <span className="arith-result">
                    <span className="op">=</span>
                    <span className="res">
                      2s10s{" "}
                      {fmtValue(
                        Number(longEnd ?? 0) - Number(frontEnd ?? 0),
                        "bps",
                        1,
                      )}
                    </span>
                  </span>
                </div>
              ))}
              <BoardRead>
                Every spread shown here is a difference of two stored deltas.
                Reconstruction cancels the level and exposes the move; a slope
                is never relabelled as a term premium.
              </BoardRead>
            </div>
          </div>
        </RatesSection>

        {/* The board's three decomposition panels. They were one section until
          2026-08-29, which let a monthly model's output inherit the authority of
          arithmetic on traded yields. */}
        {/* The board groups the three decompositions rather than stacking them, and the
          grouping is the claim: they are three different cuts of ONE move, so a
          column of three reads as a sequence where a row of three reads as
          alternatives. */}
        <div className="grid g2">
          <NominalDecompositionSection
            decomposition={decomposition}
            policy={policy}
            slopes={curve.slopes ?? []}
          />
          <ClevelandDecompositionSection decomposition={decomposition} />
        </div>
        <MoveAttributionSection decomposition={decomposition} />

        <div className="grid g3">
          {/* The board's three SUB-STATE panels, in its order. Each pairs the engine's
            verdict (from `/api/macro/rates`) with the readings it was computed from (from
            the snapshot) -- see `SubStateSection` for why both belong on screen.

            A sub-state the engine did not publish renders its snapshot readings alone
            rather than vanishing: the readings are facts about the tape and do not stop
            being true because the verdict is missing. */}
          {subStateFor("supply") ? (
            <SubStateSection subState={subStateFor("supply")!}>
              <SupplyFiscalSection supply={supply} />
            </SubStateSection>
          ) : (
            <RatesSection
              id="substate-supply"
              title="Supply"
              questions={["Q4", "Q5"]}
              basis="REAL"
              source="/api/rates/snapshot.supply"
              showQuestions={false}
            >
              <SupplyFiscalSection supply={supply} />
            </RatesSection>
          )}

          {subStateFor("positioning") ? (
            <SubStateSection subState={subStateFor("positioning")!}>
              <PositioningSection positioning={positioning} />
            </SubStateSection>
          ) : (
            <RatesSection
              id="substate-positioning"
              title="10Y futures positioning"
              questions={["Q5"]}
              basis="REAL"
              source="/api/rates/snapshot.positioning"
              showQuestions={false}
            >
              <PositioningSection positioning={positioning} />
            </RatesSection>
          )}

          {/* Funding is the board's name for what the engine calls `plumbing`. Tab 01
            carries a `Plumbing` panel too and they are NOT duplicates: that one is the
            balance sheet behind the policy rate, this one is whether funding markets are
            transmitting it. */}
          {subStateFor("plumbing") ? (
            <SubStateSection subState={subStateFor("plumbing")!}>
              <FundingReadings policy={policy} />
            </SubStateSection>
          ) : (
            // Rendered unconditionally, like its two siblings. `NAV` links to this anchor
            // on every render, so a section that appeared only when the state engine had
            // published would make the nav link to nowhere exactly when the engine is down.
            <RatesSection
              id="substate-plumbing"
              title="Funding"
              questions={["Q4"]}
              basis="REAL"
              source="/api/rates/snapshot.policy.plumbing"
              showQuestions={false}
            >
              <FundingReadings policy={policy} />
            </RatesSection>
          )}
        </div>

        <RatesSection
          id="auctions"
          title="Auction demand"
          eyebrow="TreasuryDirect · recent results"
          questions={["Q4", "Q5"]}
          basis="REAL"
          source="/api/rates/snapshot.supply.recent_auctions"
        >
          <AuctionDemandSection supply={supply} />
        </RatesSection>

        {/* The quarantine. The rule score is not deleted -- it is the only thing an
          operator can hold the policy/rates state up against -- but it is stated as a
          refusal before it is shown, so nobody reads a number this desk does not answer
          with as the answer. */}
        <RatesSection
          id="refuses"
          title="Limits"
          questions={["Q7"]}
          basis="REFERENCE"
          source="code invariants and executable tests"
        >
          <p className="read">
            A slope is not a term premium. Daily market data stays separate from
            the monthly model; missing attribution remains missing, never zero.
          </p>
          <details>
            <summary>Experimental legacy scorecard</summary>
            <RatesScorecard scorecard={scorecard} />
          </details>
        </RatesSection>
      </div>
    </div>
  );
}
