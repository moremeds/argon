import Link from "next/link";

import {
  type MacroReplayClock,
  type MacroReplayRequest,
  replayHref,
  shiftDay,
} from "./replay";

/**
 * The desk's date navigation: the one place the operator states which instant he wants.
 *
 * Three things about it are deliberate.
 *
 * **1. It names the question, per tab, and the name is required.** §3.1 of the port plan
 * banned shipping one picker over all five domain tabs until the gold clock was settled,
 * because `/api/gold/replay` keys on `obs_date` with exact equality while everything else
 * keys on an instant — one control over both would have tab 02 answering "what the desk
 * knew at T" and tab 05 answering "what the market did on day T", under a single heading.
 * §10-H settled it: label it, do not change the API. So the label is driven by
 * `MacroReplayClock`, a REQUIRED field on every `VALID_TABS` entry. A tab registered
 * without declaring its clock is a compile error, which is what turns "we will remember
 * to label gold differently" into something the type system holds.
 *
 * **2. It is a server component with a plain GET form.** No `"use client"`, no
 * `useRouter`, no JS to submit a date. The desk is `force-dynamic` and every tab re-fetches
 * on the server anyway, so a form navigation costs exactly what a client-side push would
 * and works with scripting off.
 *
 * **3. `today` is a prop.** The control never reads the clock itself; the page passes it.
 * A component that calls `new Date()` inside renders differently every day and cannot be
 * tested for what it does on the boundary it exists to police — the `next` link is capped
 * at today precisely so the picker cannot ask the desk what it knew tomorrow.
 */

type ClockCopy = { eyebrow: string; sentence: string; inputLabel: string };

const CLOCK_COPY: Record<Exclude<MacroReplayClock, "none">, ClockCopy> = {
  instant: {
    eyebrow: "Point-in-time replay",
    sentence:
      "Shows the answer that existed at the END of this UTC day — the newest one computed at or before it. A day nobody answered on returns nothing; it never falls forward to a later answer.",
    inputLabel: "Replay the desk as it stood at the end of (UTC date)",
  },
  // Live only once P6 registers tab 05. Written now because §10-H is P4's decision to
  // take, and a decision recorded as a promise to future copy is not a decision.
  obs_date: {
    eyebrow: "Observation date",
    sentence:
      "Not a point-in-time replay. This names the MARKET DAY the reading is about, matched exactly — a day with no observation has no row, and does not fall back to the day before.",
    inputLabel: "Show the observation for (market date)",
  },
};

export function ReplayControl({
  request,
  clock,
  tabHref,
  today,
}: {
  request: MacroReplayRequest;
  clock: MacroReplayClock;
  /** This tab's own path, e.g. `/macro/rates`. The form posts back to it, so the
   *  navigation stays on the tab the operator is reading. */
  tabHref: string;
  /** Today in UTC, `YYYY-MM-DD`. Passed in, never read here — see the note above. */
  today: string;
}) {
  // A tab with no data path has no instant to ask about. Rendering an inert picker over
  // static prose would advertise a capability the tab does not have.
  if (clock === "none") return null;

  const copy = CLOCK_COPY[clock];
  const asOf = request.kind === "replay" ? request.asOf : null;
  // The picker starts from the day being replayed, or from today when live. `max` keeps
  // it from asking about the future, which no publisher can answer and which the API
  // would satisfy with the live row.
  const anchor = asOf ?? today;

  return (
    <section
      data-testid="macro-replay-control"
      data-replay-clock={clock}
      aria-label={copy.eyebrow}
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "flex-start",
        gap: 16,
        padding: "14px 24px",
        borderBottom: "1px solid var(--border-dim)",
        background: "var(--bg-panel)",
      }}
    >
      <div style={{ flex: "1 1 320px", minWidth: 260 }}>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted)",
          }}
        >
          {copy.eyebrow}
        </p>
        <p
          style={{
            margin: "4px 0 0",
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--text-secondary)",
            maxWidth: 620,
          }}
        >
          {copy.sentence}
        </p>
      </div>

      <form
        action={tabHref}
        method="get"
        style={{ display: "flex", alignItems: "center", gap: 8 }}
      >
        <input
          type="date"
          name="as_of"
          defaultValue={asOf ?? ""}
          max={today}
          aria-label={copy.inputLabel}
          data-testid="macro-replay-date"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            padding: "5px 8px",
            color: "var(--text-primary)",
            background: "var(--bg-base)",
            border: "1px solid var(--border-dim)",
            borderRadius: 3,
          }}
        />
        <button
          type="submit"
          data-testid="macro-replay-submit"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            padding: "6px 12px",
            color: "var(--text-primary)",
            background: "transparent",
            border: "1px solid var(--border-dim)",
            borderRadius: 3,
            cursor: "pointer",
          }}
        >
          Go
        </button>
      </form>

      <nav
        aria-label={`${copy.eyebrow} navigation`}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          textTransform: "uppercase",
        }}
      >
        <Link
          href={replayHref(tabHref, shiftDay(anchor, -1))}
          prefetch={false}
          data-testid="macro-replay-prev"
          style={{ color: "var(--text-secondary)", textDecoration: "none" }}
        >
          ← Prev day
        </Link>
        {anchor < today ? (
          <Link
            href={replayHref(tabHref, shiftDay(anchor, 1))}
            prefetch={false}
            data-testid="macro-replay-next"
            style={{ color: "var(--text-secondary)", textDecoration: "none" }}
          >
            Next day →
          </Link>
        ) : (
          // Rendered as inert text rather than dropped, so the strip does not reflow as
          // the operator steps forward and the boundary is visible rather than implied.
          <span
            data-testid="macro-replay-next-capped"
            style={{ color: "var(--text-muted)" }}
          >
            Next day →
          </span>
        )}
        {asOf ? (
          <Link
            href={tabHref}
            prefetch={false}
            data-testid="macro-replay-live"
            style={{ color: "var(--text-primary)", textDecoration: "none" }}
          >
            Back to live
          </Link>
        ) : (
          <span data-testid="macro-replay-is-live" style={{ color: "var(--text-muted)" }}>
            Live
          </span>
        )}
      </nav>

      {request.kind === "rejected" ? (
        <p
          data-testid="macro-replay-rejected"
          style={{
            flexBasis: "100%",
            margin: 0,
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--negative)",
          }}
        >
          {/* Named, not swallowed. An ignored parameter is indistinguishable from a
              parameter that worked, and the operator would read live numbers as the past
              he asked for. */}
          <strong>Ignored:</strong> <code>as_of={request.raw}</code> is not a UTC calendar
          date (<code>YYYY-MM-DD</code>). Nothing was replayed — everything below is live.
        </p>
      ) : null}
    </section>
  );
}
