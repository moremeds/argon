import { GoldCompassLayout } from "@/components/gold/GoldCompassLayout";
import { GoldMetaChips } from "@/components/gold/GoldMetaChips";
import { GoldPostureNotice } from "@/components/gold/GoldPostureNotice";
import {
  BoardSecTitle,
  BoardStatePill,
} from "@/components/macro/domain/BoardPanel";
import {
  GoldAttributionSection,
  GoldBreakdownSection,
  GoldResearchConclusion,
} from "@/components/macro/goldFactor/GoldFactorBand";
import {
  LABEL_TEXT,
  type GoldFactor,
  type GoldFlows,
} from "@/components/macro/goldFactor/shared";
import { Zone } from "@/components/macro/overview/Zone";
import { ReplayStatus } from "@/components/macro/ReplayStatus";
import { humanizeIdentifier } from "@/components/macro/presentation";
import {
  replayVerdictForObsDate,
  replayWithholdsContent,
} from "@/components/macro/replay";
import type { MacroTabProps } from "@/components/macro/tabs";
import { settle } from "@/components/rates/deskShared";
import { api } from "@/lib/api";
import type { components } from "@/lib/types";

/**
 * Tab 05 — Gold. The one tab on this desk whose date control asks a different question.
 *
 * It lives beside `page.tsx` rather than inside it for two reasons. The three-state
 * settle below is the defect §4.6 of the port plan records `/gold`'s raw fetch shipping
 * for months, and a behaviour with that history should be unit-testable directly rather
 * than only through a browser. And it may not live in `components/macro/` at all: it
 * renders `components/gold/*`, and §7 forbids `components/macro/*` importing from the
 * domain subtrees. A co-located route file is the one home that satisfies both.
 *
 * Replay reads `/api/gold/replay`, which takes a REQUIRED `as_of` and matches `obs_date`
 * exactly.
 *
 * That exactness is the whole of §3.1's third clock. An `obs_date` names the market day a
 * reading is ABOUT; a day with no row has no answer and does not fall back to the day
 * before. The registry entry says `replayClock: "obs_date"` and both halves of the chrome
 * read it — `ReplayControl` above states the question in those terms, `ReplayStatus`
 * states the answer in them — so nothing on this tab claims to be a point-in-time replay
 * of what the desk knew.
 *
 * `showReplayPicker={false}`: `GoldCompassHeader` carries its own date input that pushes
 * to `/gold/replay/<date>`. Left on, this tab would show two pickers, and the second would
 * navigate off the desk.
 *
 * Live, the tab is the gold factor model (design v3) and reads `/api/gold/factor` and
 * `/api/gold/flows`; the posture/gauge reads and the GLD-based cockpit remain only for a
 * replayed market day, whose date those routes can answer.
 */
const GOLD_PUBLISHER = "gold posture";

type GoldPosture = components["schemas"]["GoldStateResponse"];
type GoldDomainState = components["schemas"]["MacroDomainStateResponse"];

/**
 * The board's t5 heading: `Gold`, the question strip, the domain-state pill, a standfirst.
 *
 * ### Why the standfirst is derived and not copied
 *
 * The board's own reads `…the gate is SUSPENDED while gold is +13.45% in 3 months … this
 * week the anchor kept letting go (corr_60d −0.79 → −0.17)`. Every one of those figures
 * was true at the board's capture instant and none of them is true by virtue of being
 * printed there. What binds is the FRAMING — the state is a gate, not a price view; the
 * three lenses never composite — so that is quoted, and the one live fact in the sentence
 * is read off the gauge this tab already renders.
 *
 * ### Why the question strip is not the board's either
 *
 * The board advertises `Q1 Q3 Q4 Q5 Q7` for this tab. What this tab's bands actually
 * carry is `Q1 Q2 Q4 Q5 Q7`: it has an expression-cost panel the board files elsewhere
 * (Q2), and it has nothing answering Q3. Printing the board's strip over these bands
 * would advertise a question no panel on the tab answers — the exact failure the
 * acceptance test exists to catch — so the strip is the measured union and this note is
 * the record of the difference.
 */
function GoldHeading({
  posture,
  domain,
  domainNote,
}: {
  posture: GoldPosture;
  domain: GoldDomainState | null;
  /** Why there is no pill, when there is no pill. Never blank. */
  domainNote: string;
}) {
  const gate = humanizeIdentifier(posture.gauge.state);
  return (
    <BoardSecTitle
      title="Gold"
      questions={["Q1", "Q2", "Q4", "Q5", "Q7"]}
      aside={
        <>
          <BoardStatePill
            facts={domain}
            testId="macro-domain-gold"
            absent={domainNote}
          />
          {/* Spot and feed health, as the board's masthead chips. They were two of the
              five tiles in the KPI strip this tab no longer has; the other three are
              stated with more context by the gauge and three-lens panels. */}
          <GoldMetaChips state={posture} />
        </>
      }
    >
      Real-yield transmission, structural and cyclical flows, valuation and
      expression cost. Gate: <b>{gate}</b>
      {posture.gauge.state === "suspended" ? (
        <>
          ; the cyclical lens is dimmed while transmission is suspended.
        </>
      ) : (
        "."
      )}
    </BoardSecTitle>
  );
}

/**
 * Live tab 05, laid out as design v3: the question is how much of gold's daily move the
 * three factors (10-year real yield, dollar, safe haven) explain, on spot gold (XAUUSD),
 * with the dollar inside the answer and no hard-coded break year. The pill is the factor
 * model's published label; the domain-state pill beside it is the stored gold state.
 *
 * Three states for the model, never two: answered, not computed yet (404), request failed.
 * The posture endpoint is not read live any more — its panels were the GLD / 60-day
 * correlation framing v3 replaces — so an outage there cannot hide the research.
 */
async function GoldLive() {
  const [domain, factor, flows] = await Promise.all([
    settle(() => api.macroDomainState("gold"), "gold state API"),
    settle(() => api.goldFactor(), "gold factor API"),
    settle(() => api.goldFlows(), "gold flows API"),
  ]);
  const data: GoldFactor | null = factor.value;
  const label = data?.points.at(-1)?.published_label;
  return (
    <div className="board">
      <BoardSecTitle
        title="Gold"
        questions={["Q4", "Q5"]}
        aside={
          <>
            {label ? (
              <span className="state neust" data-testid="gold-factor-label">
                3 factors {LABEL_TEXT[label]}
              </span>
            ) : null}
            <BoardStatePill
              facts={domain.value}
              testId="macro-domain-gold"
              absent={
                domain.error ??
                "no state — the engine has not run for this instant"
              }
            />
          </>
        }
      >
        How much of gold&rsquo;s daily move three factors explain: the 10-year
        real yield, the dollar and a safe-haven spread. Gold is spot XAUUSD.
        This describes the past; it is not a forecast.
      </BoardSecTitle>
      {data ? (
        <>
          <Zone
            first
            kicker="Result"
            label="Research result"
            scope={`through ${data.last_date}`}
            testKey="gold-result"
          />
          <GoldResearchConclusion data={data} />
          <GoldBreakdownSection
            data={data}
            flows={(flows.value as GoldFlows | null) ?? null}
            scope="real yield · dollar · haven · drift · unexplained"
          />
          <GoldAttributionSection data={data} />
        </>
      ) : factor.error ? (
        <GoldPostureNotice
          tone="failed"
          headline="Gold factor model · request failed"
          detail={factor.error}
          body="The API could not be read, so we do not know whether the model has run. This is a read failure, not a finding about the data."
        />
      ) : (
        <GoldPostureNotice
          tone="pending"
          headline="Gold factor model · not computed yet"
          body="The API answered, but there is no model result yet: the nightly job has not completed a run."
        />
      )}
    </div>
  );
}

export async function GoldTab({ replay }: MacroTabProps) {
  if (replay.kind !== "replay") return GoldLive();
  const asOf = replay.asOf;
  // Replay names a market day (`obs_date`, matched exactly). The factor model's routes
  // take no date, so a replayed tab shows the stored posture of that day, as before.
  const [posture] = await Promise.all([
    settle(() => api.goldReplay(asOf), "gold posture API"),
  ]);
  const verdict = replayVerdictForObsDate(replay, {
    obsDate: posture.value?.obs_date,
    computedAt: posture.value?.computed_at,
    failed: Boolean(posture.error),
  });
  const status = (
    <ReplayStatus
      verdict={verdict}
      publisher={GOLD_PUBLISHER}
      clock="obs_date"
    />
  );
  if (replayWithholdsContent(verdict)) return status;

  // The three states §4.6 records `/gold`'s raw fetch collapsing into one for months,
  // carried here rather than re-derived: `allow404` makes "no posture row" a null VALUE,
  // and anything else — including an unreachable API — arrives as an error string.
  if (posture.error) {
    return (
      <>
        {status}
        <GoldPostureNotice
          tone="failed"
          headline="Gold Compass · posture request failed"
          detail={posture.error}
          body="The API could not be read, so whether a posture has been computed is unknown. This is a failure to reach the data, not a statement about it."
        />
      </>
    );
  }
  if (!posture.value) {
    return (
      <>
        {status}
        <GoldPostureNotice
          tone="pending"
          headline="Gold Compass · posture not yet computed"
          body="The API answered, and there is no posture row yet — the engine has not run, which is not the same as the request failing. The first scheduled run lands at the next worker tick."
        />
      </>
    );
  }

  return (
    <>
      {status}
      <div className="board">
        <GoldCompassLayout
          state={posture.value}
          replayDate={asOf}
          showReplayPicker={false}
          deskHeading={
            <GoldHeading
              posture={posture.value}
              domain={null}
              domainNote="domain state not shown for a replayed observation date — this tab's date names a market day, and the state endpoint answers an instant"
            />
          }
        />
      </div>
    </>
  );
}
