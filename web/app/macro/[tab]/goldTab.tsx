import { GoldCompassLayout } from "@/components/gold/GoldCompassLayout";
import { GoldPostureNotice } from "@/components/gold/GoldPostureNotice";
import { ReplayStatus } from "@/components/macro/ReplayStatus";
import {
  replayVerdictForObsDate,
  replayWithholdsContent,
} from "@/components/macro/replay";
import type { MacroTabProps } from "@/components/macro/tabs";
import { settle } from "@/components/rates/deskShared";
import { api } from "@/lib/api";

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
 * It deliberately does NOT call `/api/gold/gauge` — §4.5 of the plan measured that route
 * recomputing 262 correlation gauges per request, and `correlation_history` already
 * arrives inside the state response.
 */
const GOLD_PUBLISHER = "gold posture";

export async function GoldTab({ replay }: MacroTabProps) {
  const asOf = replay.kind === "replay" ? replay.asOf : null;
  const posture = await settle(
    () => (asOf === null ? api.goldState() : api.goldReplay(asOf)),
    "gold posture API",
  );

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
      <GoldCompassLayout
        state={posture.value}
        replayDate={asOf ?? undefined}
        showReplayPicker={false}
      />
    </>
  );
}
