import { GoldCompassLayout } from "@/components/gold/GoldCompassLayout";
import { GoldMetaChips } from "@/components/gold/GoldMetaChips";
import { GoldPostureNotice } from "@/components/gold/GoldPostureNotice";
import {
  BoardSecTitle,
  BoardStatePill,
} from "@/components/macro/domain/BoardPanel";
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
 * TWO endpoints, not one, and which is called depends on the request: `/api/gold/state`
 * returns the newest posture and takes no date at all, while `/api/gold/replay` takes a
 * REQUIRED `as_of` and matches `obs_date` exactly. So live and replay are separate calls
 * here, unlike tabs 01-04 where one endpoint takes an optional parameter.
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
 * It DOES call `/api/gold/gauge`, reversing §4.5 of the port plan. That section declined
 * the route as expensive — "recomputing 262 correlation gauges per request" — and
 * settled for the `correlation_history` that arrives inside the state response.
 * Re-measured 2026-08-29: the route answers in ~50ms against ~29ms for
 * `/api/gold/state`. The cost was real when measured and is not material now.
 *
 * What it buys is depth, not the board's resolution. `history_252d` carries ~261
 * observations where `correlation_history` carries 3-5, which is the difference between
 * a line that can show an anchor decaying and three segments that can only show a
 * direction. It does NOT carry `corr_60d` — no point of it does — so the board's
 * "corr_60d, daily" heading still cannot be honoured; `CorrelationHistoryPanel` names
 * the window it draws and states the gap.
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

export async function GoldTab({ replay }: MacroTabProps) {
  const asOf = replay.kind === "replay" ? replay.asOf : null;
  // The domain state is fetched ONLY in live mode, and that is a clock decision rather
  // than an optimisation. This tab's date is an `obs_date` — the market day a reading is
  // about, matched exactly — while `/api/macro/gold` resolves an INSTANT. Handing this
  // tab's date to that endpoint would put two different questions under one pill and let
  // the answer to the second pass for the answer to the first. Live, both mean "newest",
  // so they agree and the pill is honest.
  const [posture, domain, gauge] = await Promise.all([
    settle(
      () => (asOf === null ? api.goldState() : api.goldReplay(asOf)),
      "gold posture API",
    ),
    asOf === null
      ? settle(() => api.macroDomainState("gold"), "gold state API")
      : Promise.resolve({ value: null, error: undefined }),
    // The anchor-decay panel's dense series, and live-only for the same clock reason as
    // the domain state above: `/api/gold/gauge` takes no date, so under replay it would
    // answer a question about today inside a tab that has named a past observation date.
    // Settled separately — a gauge outage must cost one panel's primary line, not the
    // tab, which is why it is not folded into the posture request.
    asOf === null
      ? settle(() => api.goldGauge(), "gold gauge API")
      : Promise.resolve({ value: null, error: undefined }),
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
          replayDate={asOf ?? undefined}
          showReplayPicker={false}
          anchorHistory={gauge.value?.history_60d}
          deskHeading={
            <GoldHeading
              posture={posture.value}
              domain={domain.value}
              domainNote={
                asOf !== null
                  ? "domain state not shown for a replayed observation date — this tab's date names a market day, and the state endpoint answers an instant"
                  : (domain.error ??
                    "no state — the engine has not run for this instant")
              }
            />
          }
        />
      </div>
    </>
  );
}
