import { describe, expect, it } from "vitest";

import {
  formatInstantUtc,
  parseInstantMs,
  parseReplayRequest,
  replayHref,
  replayVerdict,
  replayVerdictForDomainState,
  replayVerdictForObsDate,
  replayWithholdsContent,
  shiftDay,
} from "@/components/macro/replay";

/**
 * The replay arithmetic, apart from any component.
 *
 * These are the assertions that make the desk-wide picker safe to ship: what counts as a
 * date, what a naive timestamp means, and — the one that matters most — that the verdict
 * is computed from the RESPONSE and refuses when the response is not from the instant
 * that was asked for. §8 of the port plan measured that a pre-P1 `argon-app` image
 * answers `?as_of=2026-01-01` with the live snapshot and a 200, so the refusal below is
 * the only thing standing between an operator and today's curve under a replay heading.
 */

describe("parseReplayRequest", () => {
  it("reads a UTC calendar date", () => {
    expect(parseReplayRequest("2026-08-27")).toEqual({
      kind: "replay",
      asOf: "2026-08-27",
    });
  });

  it("treats an absent or emptied parameter as live", () => {
    expect(parseReplayRequest(undefined)).toEqual({ kind: "live" });
    // What the control's own date input submits once it has been cleared.
    expect(parseReplayRequest("")).toEqual({ kind: "live" });
    expect(parseReplayRequest("   ")).toEqual({ kind: "live" });
  });

  it("rejects garbage rather than silently showing live data", () => {
    // The whole point of the third state: a rejected request must stay visible, because
    // "your date was ignored" and "here is the past you asked for" look identical once
    // the page renders.
    for (const raw of [
      "notadate",
      "27/08/2026",
      "2026-8-27",
      "yesterday",
      "0",
    ]) {
      expect(parseReplayRequest(raw)).toEqual({ kind: "rejected", raw });
    }
  });

  it("rejects a date shaped like one that the calendar does not have", () => {
    // Passes the regex, is not a day. A shape check alone would forward it to the API.
    expect(parseReplayRequest("2026-02-30")).toEqual({
      kind: "rejected",
      raw: "2026-02-30",
    });
    expect(parseReplayRequest("2026-13-01")).toEqual({
      kind: "rejected",
      raw: "2026-13-01",
    });
  });

  it("rejects two dates at once instead of picking one", () => {
    // `?as_of=a&as_of=b` is two questions. Answering one of them silently answers a
    // question nobody asked — the same refusal `resolve_instant` makes (HTTP 422) when
    // handed both `as_of` and `as_of_ts`.
    expect(parseReplayRequest(["2026-08-27", "2026-08-01"])).toEqual({
      kind: "rejected",
      raw: "2026-08-27, 2026-08-01",
    });
  });

  it("caps the echoed value so a pasted essay cannot become the page", () => {
    const raw = "x".repeat(500);
    const parsed = parseReplayRequest(raw);
    expect(parsed.kind).toBe("rejected");
    expect(parsed.kind === "rejected" && parsed.raw.length).toBe(64);
  });
});

describe("parseInstantMs", () => {
  it("reads an offset-carrying timestamp as written", () => {
    expect(parseInstantMs("2026-08-27T03:42:00+00:00")).toBe(
      Date.parse("2026-08-27T03:42:00Z"),
    );
    expect(parseInstantMs("2026-08-27T03:42:00Z")).toBe(
      Date.parse("2026-08-27T03:42:00Z"),
    );
  });

  it("reads a NAIVE timestamp as UTC, not as local time", () => {
    // `RatesSnapshotResponse.computed_at` is a plain `datetime` (models/rates.py:241) and
    // the router normalises a naive one to UTC (routers/rates.py:99-100). JavaScript does
    // the opposite with the same string: no offset means LOCAL time. On a UTC+8 desk that
    // is an eight-hour error, which is enough to flip the day-boundary comparison and
    // withhold a snapshot that was computed in time.
    expect(parseInstantMs("2026-08-27T03:42:00")).toBe(
      Date.parse("2026-08-27T03:42:00Z"),
    );
  });

  it("returns null rather than NaN for something unreadable", () => {
    expect(parseInstantMs("not a timestamp")).toBeNull();
  });
});

describe("shiftDay / replayHref / formatInstantUtc", () => {
  it("steps across a month and a leap day in UTC", () => {
    expect(shiftDay("2026-03-01", -1)).toBe("2026-02-28");
    expect(shiftDay("2024-03-01", -1)).toBe("2024-02-29");
    expect(shiftDay("2026-12-31", 1)).toBe("2027-01-01");
  });

  it("attaches the date to a tab href, or leaves it bare", () => {
    expect(replayHref("/macro/rates", "2026-08-27")).toBe(
      "/macro/rates?as_of=2026-08-27",
    );
    expect(replayHref("/macro/rates", null)).toBe("/macro/rates");
  });

  it("renders an answer's clock in UTC, because the boundary is a UTC one", () => {
    expect(formatInstantUtc("2026-08-27T03:42:11+00:00")).toBe(
      "2026-08-27 03:42 UTC",
    );
    // Unreadable in, unchanged out — never an invented time.
    expect(formatInstantUtc("garbage")).toBe("garbage");
  });
});

describe("replayVerdict", () => {
  const replaying = { kind: "replay", asOf: "2026-08-27" } as const;

  it("says nothing at all when the request was not a replay", () => {
    for (const request of [
      { kind: "live" } as const,
      { kind: "rejected", raw: "nope" } as const,
    ]) {
      expect(
        replayVerdict(request, { computedAt: "2026-08-27T01:00:00Z" }),
      ).toEqual({ kind: "not_replaying" });
    }
  });

  it("accepts an answer computed at or before the end of the requested UTC day", () => {
    expect(
      replayVerdict(replaying, { computedAt: "2026-08-27T23:59:59.999Z" }),
    ).toEqual({
      kind: "replaying",
      asOf: "2026-08-27",
      computedAt: "2026-08-27T23:59:59.999Z",
    });
    expect(
      replayVerdict(replaying, { computedAt: "2020-01-01T00:00:00Z" }),
    ).toMatchObject({ kind: "replaying" });
  });

  it("REFUSES an answer computed after the instant asked for", () => {
    // The Watchtower race, exactly: an API image that does not know `as_of` returns the
    // live snapshot with a 200, and only `computed_at` can tell the difference.
    expect(
      replayVerdict(replaying, { computedAt: "2026-08-28T00:00:00Z" }),
    ).toEqual({
      kind: "answered_after",
      asOf: "2026-08-27",
      computedAt: "2026-08-28T00:00:00Z",
    });
  });

  it("refuses an answer whose clock it cannot read", () => {
    expect(replayVerdict(replaying, { computedAt: "sometime" })).toEqual({
      kind: "answered_after",
      asOf: "2026-08-27",
      computedAt: null,
    });
  });

  it("keeps 'nothing was answered' apart from 'the request failed'", () => {
    // §9 invariant 2. One is a fact about the publisher's history, the other about our
    // API being reachable, and rendering them as the same sentence is the defect §4.6
    // records `/gold`'s raw fetch shipping for months.
    expect(replayVerdict(replaying, { computedAt: null })).toEqual({
      kind: "unanswered",
      asOf: "2026-08-27",
    });
    expect(replayVerdict(replaying, {})).toEqual({
      kind: "unanswered",
      asOf: "2026-08-27",
    });
    expect(replayVerdict(replaying, { failed: true })).toEqual({
      kind: "request_failed",
      asOf: "2026-08-27",
    });
    // A failure wins over whatever stale value came with it.
    expect(
      replayVerdict(replaying, {
        failed: true,
        computedAt: "2026-08-27T01:00:00Z",
      }),
    ).toEqual({ kind: "request_failed", asOf: "2026-08-27" });
  });
});

describe("replayVerdictForDomainState", () => {
  const replaying = { kind: "replay", asOf: "2026-08-27" } as const;

  it("GATES ON as_of, not computed_at — a late recompute is still that day's answer", () => {
    // The defect this function exists to prevent, and the reason tabs 03/04 do not reuse
    // `replayVerdict`. `/api/macro/{domain}` selects `WHERE as_of <= %s`
    // (`macro_domain_state.py:222`) and the store deliberately permits `computed_at` to be
    // LATER than `as_of` — its docstring calls a later recompute of the same instant "a
    // better answer to the same question" and breaks ties by the later `computed_at`.
    //
    // A backfilled state: answers for the 27th, written on the 30th. Gated on
    // `computed_at` this would be refused as `answered_after` and the desk would blame a
    // deploy race for an answer it actually holds.
    expect(
      replayVerdictForDomainState(replaying, {
        asOf: "2026-08-27T12:00:00Z",
        computedAt: "2026-08-30T04:00:00Z",
      }),
    ).toEqual({
      kind: "replaying",
      asOf: "2026-08-27",
      // Printed, not gated on: "that answer was computed X" is a sentence about a compute
      // time, and `as_of` is not one.
      computedAt: "2026-08-30T04:00:00Z",
    });

    // Proof the two functions really do disagree on this input, rather than the assertion
    // above passing for some incidental reason.
    expect(
      replayVerdict(replaying, { computedAt: "2026-08-30T04:00:00Z" }),
    ).toMatchObject({ kind: "answered_after" });
  });

  it("still REFUSES a state that answers for a later instant", () => {
    // An API image that ignored `as_of` hands back the newest state, whose `as_of` is
    // after the day asked for. That is the one refusal this gate must keep.
    expect(
      replayVerdictForDomainState(replaying, {
        asOf: "2026-08-28T00:00:00Z",
        computedAt: "2026-08-28T04:00:00Z",
      }),
    ).toEqual({
      kind: "answered_after",
      asOf: "2026-08-27",
      computedAt: "2026-08-28T04:00:00Z",
    });
  });

  it("falls back to the state's own as_of when no compute time came with it", () => {
    expect(
      replayVerdictForDomainState(replaying, { asOf: "2026-08-27T12:00:00Z" }),
    ).toEqual({
      kind: "replaying",
      asOf: "2026-08-27",
      computedAt: "2026-08-27T12:00:00Z",
    });
  });

  it("refuses a state whose as_of it cannot read", () => {
    expect(
      replayVerdictForDomainState(replaying, {
        asOf: "sometime",
        computedAt: "2026-08-27T04:00:00Z",
      }),
    ).toEqual({
      kind: "answered_after",
      asOf: "2026-08-27",
      computedAt: "2026-08-27T04:00:00Z",
    });
  });

  it("keeps the three kinds of nothing apart, like its rates sibling", () => {
    expect(
      replayVerdictForDomainState({ kind: "live" }, { asOf: "x" }),
    ).toEqual({ kind: "not_replaying" });
    // A 404 from `_domain_state` is "no state has been computed for an instant at or
    // before this one" — a fact about the pipeline, which `allow404` turns into a null
    // value rather than a throw.
    expect(replayVerdictForDomainState(replaying, {})).toEqual({
      kind: "unanswered",
      asOf: "2026-08-27",
    });
    expect(replayVerdictForDomainState(replaying, { failed: true })).toEqual({
      kind: "request_failed",
      asOf: "2026-08-27",
    });
    // A failure wins over whatever came with it.
    expect(
      replayVerdictForDomainState(replaying, {
        failed: true,
        asOf: "2026-08-27T12:00:00Z",
      }),
    ).toEqual({ kind: "request_failed", asOf: "2026-08-27" });
  });
});

describe("replayVerdictForObsDate", () => {
  const replaying = { kind: "replay", asOf: "2026-08-27" } as const;

  it("matches the MARKET DAY exactly, and never falls back to an earlier one", () => {
    // `/api/gold/replay` is `WHERE obs_date = %s`. The day before is a different reading,
    // not a stale version of this one — which is precisely why this cannot reuse
    // `replayVerdict`, whose comparison is an at-or-before on an instant and would have
    // accepted the 26th as the 27th's answer.
    expect(
      replayVerdictForObsDate(replaying, {
        obsDate: "2026-08-27",
        computedAt: "2026-08-27T23:10:00Z",
      }),
    ).toEqual({
      kind: "replaying",
      asOf: "2026-08-27",
      computedAt: "2026-08-27T23:10:00Z",
    });
    expect(
      replayVerdictForObsDate(replaying, {
        obsDate: "2026-08-26",
        computedAt: "2026-08-26T23:10:00Z",
      }),
    ).toEqual({
      kind: "answered_after",
      asOf: "2026-08-27",
      computedAt: "2026-08-26T23:10:00Z",
    });

    // The two functions really do disagree on that input, which is the point of having
    // both: the instant gate reads an earlier day as a perfectly good answer.
    expect(
      replayVerdict(replaying, { computedAt: "2026-08-26T23:10:00Z" }),
    ).toMatchObject({ kind: "replaying" });
  });

  it("keeps 'no row for that day' apart from 'the request failed'", () => {
    // `/api/gold/replay` 404s for a day it never reconstructed, which `allow404` turns
    // into a null value — a fact about the posture history, not about our API.
    expect(replayVerdictForObsDate(replaying, {})).toEqual({
      kind: "unanswered",
      asOf: "2026-08-27",
    });
    expect(replayVerdictForObsDate(replaying, { failed: true })).toEqual({
      kind: "request_failed",
      asOf: "2026-08-27",
    });
    expect(
      replayVerdictForObsDate({ kind: "live" }, { obsDate: "2026-08-27" }),
    ).toEqual({ kind: "not_replaying" });
  });

  it("falls back to the market day itself when no compute time came with the row", () => {
    expect(
      replayVerdictForObsDate(replaying, { obsDate: "2026-08-27" }),
    ).toEqual({
      kind: "replaying",
      asOf: "2026-08-27",
      computedAt: "2026-08-27",
    });
  });
});

describe("replayWithholdsContent", () => {
  it("withholds only when what came back is not that instant's answer", () => {
    expect(
      replayWithholdsContent({ kind: "unanswered", asOf: "2026-08-27" }),
    ).toBe(true);
    expect(
      replayWithholdsContent({
        kind: "answered_after",
        asOf: "2026-08-27",
        computedAt: "2026-08-28T00:00:00Z",
      }),
    ).toBe(true);

    // A failed request still renders the tab: the desk's own empty state is what says
    // "API unavailable", and the banner beside it says which instant went unanswered.
    expect(
      replayWithholdsContent({ kind: "request_failed", asOf: "2026-08-27" }),
    ).toBe(false);
    expect(
      replayWithholdsContent({
        kind: "replaying",
        asOf: "2026-08-27",
        computedAt: "2026-08-27T01:00:00Z",
      }),
    ).toBe(false);
    expect(replayWithholdsContent({ kind: "not_replaying" })).toBe(false);
  });
});
