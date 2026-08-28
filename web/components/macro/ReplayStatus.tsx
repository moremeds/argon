import {
  formatInstantUtc,
  type MacroReplayClock,
  type ReplayVerdict,
} from "./replay";

/**
 * What ONE publisher answered for the instant that was asked for.
 *
 * This is the half of the replay chrome that the tab owns rather than the desk, and the
 * split is the point. `ReplayControl` states the REQUEST — one control, above the tab
 * content, the same on every tab. This states the ANSWER, and there is one per publisher
 * because each publisher can decline separately: a tab that fetched two endpoints can be
 * replaying one and missing the other, and a single desk-level banner would have to
 * average that into a sentence that is true of neither.
 *
 * §8 of the port plan is explicit that the response, not the request, drives it:
 *
 *   > `/api/rates/snapshot` returns `computed_at`; a replay to instant T must see
 *   > `computed_at <= T` or render "this publisher did not answer for that instant"
 *   > instead of a curve. The check is free, is correct against both API images, and is
 *   > the only thing that survives a Watchtower race.
 *
 * So `answered_after` is a REFUSAL, not a warning: the caller withholds the content
 * (`replayWithholdsContent`) rather than drawing it under a replay heading. An old
 * `argon-app` image answers a replay request with the live snapshot and a 200 — there is
 * nothing else on the wire that can tell the operator he is looking at today.
 *
 * ### The clock is a REQUIRED prop, for the same reason it is on the registry entry
 *
 * §10-H settled the gold clock by labelling it, and P4 discharged that on the QUESTION
 * side: `ReplayControl` takes `MacroReplayClock` off `VALID_TABS`, with no default, so an
 * obs-date tab cannot inherit an instant tab's picker copy by omission. The ANSWER side
 * needed the same treatment, and this is it.
 *
 * Every sentence below used to be instant-shaped — "as it stood at the end of X UTC",
 * "no answer existed at the end of X UTC", "a replay that falls forward is a replay of the
 * wrong day". All three are false of `/api/gold/replay`, which matches `obs_date` with
 * exact equality and is not a point-in-time replay at all. A default would have let tab 05
 * render the honest question above the dishonest answer, which is §3.1's failure moved one
 * component to the right rather than fixed. There is no default: the caller names it, and
 * a caller that forgets does not compile.
 */

type Tone = "replay" | "refused";

/** A tab with no clock has no data path, so it can have no answer to report either — the
 *  `"none"` case is unrepresentable rather than handled. */
type AnswerClock = Exclude<MacroReplayClock, "none">;

type Copy = { tone: Tone; eyebrow: string; text: string };

function toneColor(tone: Tone): string {
  return tone === "replay" ? "var(--warning)" : "var(--negative)";
}

/** "What did the desk know at instant T" — `/api/rates/snapshot` and `/api/macro/*`.
 *  Both answer the same question for an operator even though they filter different
 *  columns (`computed_at` vs `as_of`); the column each gate reads is decided in
 *  `replay.ts`, not here. */
function instantCopy(
  verdict: Exclude<ReplayVerdict, { kind: "not_replaying" }>,
  publisher: string,
): Copy {
  switch (verdict.kind) {
    case "replaying":
      return {
        tone: "replay",
        eyebrow: "Replaying — not live",
        text: `Showing the ${publisher} as it stood at the end of ${verdict.asOf} UTC. That answer was computed ${formatInstantUtc(verdict.computedAt)}.`,
      };
    case "unanswered":
      return {
        tone: "refused",
        eyebrow: "No answer for that instant",
        text: `No ${publisher} existed at the end of ${verdict.asOf} UTC. Nothing from a later instant is shown in its place — a replay that falls forward is a replay of the wrong day.`,
      };
    case "request_failed":
      return {
        tone: "refused",
        eyebrow: "Request failed",
        text: `You asked for ${verdict.asOf}; the ${publisher} request failed, so nothing on this tab is from that instant. This is a fact about our API, not about what the publisher held on that day.`,
      };
    case "answered_after":
      return {
        tone: "refused",
        eyebrow: "Withheld — wrong instant",
        text:
          verdict.computedAt === null
            ? `The ${publisher} answered without a readable computed-at, so nothing here can be shown as ${verdict.asOf}'s answer.`
            : `The ${publisher} answered with a snapshot computed ${formatInstantUtc(verdict.computedAt)} — AFTER the end of ${verdict.asOf} UTC that was asked for. That is what a web release deployed ahead of the API's replay support looks like, so the answer is withheld rather than drawn under a replay heading.`,
      };
  }
}

/** "What was recorded for market day D" — `/api/gold/replay`, `WHERE obs_date = %s`.
 *  Nothing here may promise a point-in-time replay: an observation row says what the
 *  market did on a day, not what the desk knew at an instant, and it is matched exactly
 *  rather than at-or-before. */
function obsDateCopy(
  verdict: Exclude<ReplayVerdict, { kind: "not_replaying" }>,
  publisher: string,
): Copy {
  switch (verdict.kind) {
    case "replaying":
      return {
        tone: "replay",
        eyebrow: "Observation — not live",
        text: `Showing the ${publisher} recorded for market day ${verdict.asOf}, and that row was computed ${formatInstantUtc(verdict.computedAt)}. This is what was observed on that day, not a reconstruction of what the desk knew at the time.`,
      };
    case "unanswered":
      return {
        tone: "refused",
        eyebrow: "No row for that market day",
        text: `No ${publisher} was recorded for market day ${verdict.asOf}. The lookup is an exact match on the observation date, so a day with no row has no answer and does not fall back to the day before.`,
      };
    case "request_failed":
      return {
        tone: "refused",
        eyebrow: "Request failed",
        text: `You asked for market day ${verdict.asOf}; the ${publisher} request failed, so nothing on this tab is that day's reading. This is a fact about our API, not about what was observed.`,
      };
    case "answered_after":
      return {
        tone: "refused",
        eyebrow: "Withheld — wrong market day",
        text: `The ${publisher} answered with a row for a market day other than ${verdict.asOf}, so it is withheld rather than drawn under that date's heading. The lookup is an exact match, so this should be unreachable — seeing it means the response stopped matching the request.`,
      };
  }
}

const COPY: Record<
  AnswerClock,
  (
    verdict: Exclude<ReplayVerdict, { kind: "not_replaying" }>,
    publisher: string,
  ) => Copy
> = {
  instant: instantCopy,
  obs_date: obsDateCopy,
};

export function ReplayStatus({
  verdict,
  publisher,
  clock,
}: {
  verdict: ReplayVerdict;
  /** What answered, in the operator's words — "rates snapshot", not "endpoint". Appears
   *  mid-sentence, so it is lower case and singular. */
  publisher: string;
  /** Which question this tab asked, taken from its `VALID_TABS` entry. Required — see the
   *  note above; there is deliberately no default to inherit. */
  clock: AnswerClock;
}) {
  if (verdict.kind === "not_replaying") return null;

  const { tone, eyebrow, text } = COPY[clock](verdict, publisher);
  const color = toneColor(tone);

  return (
    <section
      data-testid="macro-replay-status"
      data-replay-state={verdict.kind}
      data-replay-clock={clock}
      role="status"
      style={{
        margin: "16px 24px 0",
        padding: "10px 14px",
        borderLeft: `3px solid ${color}`,
        background: "var(--bg-panel)",
      }}
    >
      <p
        style={{
          margin: 0,
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          color,
        }}
      >
        {eyebrow}
      </p>
      <p
        style={{
          margin: "4px 0 0",
          fontSize: 12,
          lineHeight: 1.5,
          color: "var(--text-secondary)",
          maxWidth: 760,
        }}
      >
        {text}
      </p>
    </section>
  );
}
