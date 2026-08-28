import { formatInstantUtc, type ReplayVerdict } from "./replay";

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
 */

type Tone = "replay" | "refused";

function toneColor(tone: Tone): string {
  return tone === "replay" ? "var(--warning)" : "var(--negative)";
}

function body(
  verdict: Exclude<ReplayVerdict, { kind: "not_replaying" }>,
  publisher: string,
): { tone: Tone; eyebrow: string; text: string } {
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

export function ReplayStatus({
  verdict,
  publisher,
}: {
  verdict: ReplayVerdict;
  /** What answered, in the operator's words — "rates snapshot", not "endpoint". Appears
   *  mid-sentence, so it is lower case and singular. */
  publisher: string;
}) {
  if (verdict.kind === "not_replaying") return null;

  const { tone, eyebrow, text } = body(verdict, publisher);
  const color = toneColor(tone);

  return (
    <section
      data-testid="macro-replay-status"
      data-replay-state={verdict.kind}
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
