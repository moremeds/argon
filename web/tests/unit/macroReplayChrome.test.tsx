import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// next/link renders an <a> here; `prefetch` is not a DOM attribute, so it is dropped
// rather than warned about. Matching `macroTabBar.test.tsx`.
vi.mock("next/link", () => ({
  default: ({
    href,
    prefetch,
    children,
    ...rest
  }: {
    href: string;
    prefetch?: boolean;
    children: React.ReactNode;
  } & Record<string, unknown>) => (
    <a href={href} data-prefetch={String(prefetch)} {...rest}>
      {children}
    </a>
  ),
}));

import { ReplayControl } from "@/components/macro/ReplayControl";
import { ReplayStatus } from "@/components/macro/ReplayStatus";
import { VALID_TABS } from "@/components/macro/tabs";

const TODAY = "2026-08-27";

describe("ReplayControl — the question, stated once", () => {
  it("renders nothing for a tab with no clock", () => {
    // Tab 08 is static prose. An inert picker over it would advertise a capability the
    // tab does not have.
    const { container } = render(
      <ReplayControl
        request={{ kind: "live" }}
        clock="none"
        tabHref="/macro/notes"
        today={TODAY}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("asks a VISIBLY DIFFERENT question for an obs-date tab", () => {
    // This is §3.1's ban being discharged rather than assumed. `/api/gold/replay` is
    // `WHERE obs_date = %s` — exact equality on the market day — while
    // `/api/rates/snapshot` is `WHERE computed_at <= %s`. §10-H settled it as a labelling
    // decision, so the two controls must not read the same, and the label must come off
    // the registry rather than off a comment somebody remembers to honour.
    const instant = render(
      <ReplayControl
        request={{ kind: "live" }}
        clock="instant"
        tabHref="/macro/rates"
        today={TODAY}
      />,
    );
    const instantControl = instant.getByTestId("macro-replay-control");
    const instantText = instantControl.textContent ?? "";
    expect(instantControl.getAttribute("data-replay-clock")).toBe("instant");
    expect(instantText).toMatch(/point-in-time replay/i);
    expect(instantText).toMatch(/end of this utc day/i);
    instant.unmount();

    const obs = render(
      <ReplayControl
        request={{ kind: "live" }}
        clock="obs_date"
        tabHref="/macro/gold"
        today={TODAY}
      />,
    );
    const obsControl = obs.getByTestId("macro-replay-control");
    const obsText = obsControl.textContent ?? "";
    expect(obsControl.getAttribute("data-replay-clock")).toBe("obs_date");
    expect(obsText).toMatch(/observation date/i);
    expect(obsText).toMatch(/not a point-in-time replay/i);
    expect(obsText).toMatch(/matched exactly/i);
    // And it must not borrow the other's promise, which is the specific lie the ban
    // exists to prevent: an obs-date row does not fall back to an earlier day.
    expect(obsText).not.toMatch(/end of this utc day/i);
  });

  it("posts back to its own tab so replaying does not change tab", () => {
    render(
      <ReplayControl
        request={{ kind: "live" }}
        clock="instant"
        tabHref="/macro/fed"
        today={TODAY}
      />,
    );
    const input = screen.getByTestId("macro-replay-date");
    expect(input.closest("form")?.getAttribute("action")).toBe("/macro/fed");
    expect(input.getAttribute("name")).toBe("as_of");
    // Capped at today: no publisher can answer for tomorrow, and the API would satisfy
    // the request with the live row rather than refusing it.
    expect(input.getAttribute("max")).toBe(TODAY);
  });

  it("navigates from the replayed day when replaying, and offers the way back to live", () => {
    render(
      <ReplayControl
        request={{ kind: "replay", asOf: "2026-08-20" }}
        clock="instant"
        tabHref="/macro/rates"
        today={TODAY}
      />,
    );
    expect(
      (screen.getByTestId("macro-replay-date") as HTMLInputElement).value,
    ).toBe("2026-08-20");
    expect(screen.getByTestId("macro-replay-prev").getAttribute("href")).toBe(
      "/macro/rates?as_of=2026-08-19",
    );
    expect(screen.getByTestId("macro-replay-next").getAttribute("href")).toBe(
      "/macro/rates?as_of=2026-08-21",
    );
    expect(screen.getByTestId("macro-replay-live").getAttribute("href")).toBe(
      "/macro/rates",
    );
  });

  it("will not step past today, and says it is live when it is", () => {
    render(
      <ReplayControl
        request={{ kind: "live" }}
        clock="instant"
        tabHref="/macro/rates"
        today={TODAY}
      />,
    );
    expect(screen.getByTestId("macro-replay-prev").getAttribute("href")).toBe(
      "/macro/rates?as_of=2026-08-26",
    );
    expect(screen.queryByTestId("macro-replay-next")).toBeNull();
    expect(screen.queryByTestId("macro-replay-next-capped")).not.toBeNull();
    expect(screen.queryByTestId("macro-replay-live")).toBeNull();
    expect(screen.queryByTestId("macro-replay-is-live")).not.toBeNull();
  });

  it("names a rejected value instead of quietly showing live data", () => {
    render(
      <ReplayControl
        request={{ kind: "rejected", raw: "yesterday" }}
        clock="instant"
        tabHref="/macro/rates"
        today={TODAY}
      />,
    );
    const rejected = screen.getByTestId("macro-replay-rejected");
    expect(rejected.textContent).toMatch(/as_of=yesterday/);
    expect(rejected.textContent).toMatch(/nothing was replayed/i);
    // A rejected request is not a replay, so the picker stays on today.
    expect(
      (screen.getByTestId("macro-replay-date") as HTMLInputElement).value,
    ).toBe("");
  });
});

describe("ReplayStatus — the answer, driven by the response", () => {
  it("says nothing when the page is live", () => {
    const { container } = render(
      <ReplayStatus
        verdict={{ kind: "not_replaying" }}
        publisher="rates snapshot"
        clock="instant"
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("reports the instant the store ANSWERED with, not the one that was asked for", () => {
    // The distinction the banner exists to make. The operator asked for 2026-08-20; the
    // newest answer at or before that day-end was computed on the 19th, and the banner
    // must say so rather than repeat the request back at him.
    render(
      <ReplayStatus
        verdict={{
          kind: "replaying",
          asOf: "2026-08-20",
          computedAt: "2026-08-19T22:15:00+00:00",
        }}
        publisher="rates snapshot"
        clock="instant"
      />,
    );
    const status = screen.getByTestId("macro-replay-status");
    expect(status.getAttribute("data-replay-state")).toBe("replaying");
    expect(status.textContent).toMatch(/end of 2026-08-20 UTC/);
    expect(status.textContent).toMatch(/computed 2026-08-19 22:15 UTC/);
    expect(status.textContent).toMatch(/not live/i);
  });

  it("refuses, in the operator's words, when the answer is from after the instant", () => {
    render(
      <ReplayStatus
        verdict={{
          kind: "answered_after",
          asOf: "2026-01-01",
          computedAt: "2026-08-27T03:00:00Z",
        }}
        publisher="rates snapshot"
        clock="instant"
      />,
    );
    const status = screen.getByTestId("macro-replay-status");
    expect(status.getAttribute("data-replay-state")).toBe("answered_after");
    expect(status.textContent).toMatch(/withheld/i);
    expect(status.textContent).toMatch(/2026-08-27 03:00 UTC/);
    expect(status.textContent).toMatch(/deployed ahead of the API/i);
  });

  it("keeps unanswered, failed and withheld as three different sentences", () => {
    const seen = new Set<string>();
    for (const verdict of [
      { kind: "unanswered", asOf: "2000-01-01" } as const,
      { kind: "request_failed", asOf: "2000-01-01" } as const,
      {
        kind: "answered_after",
        asOf: "2000-01-01",
        computedAt: null,
      } as const,
    ]) {
      const view = render(
        <ReplayStatus
          verdict={verdict}
          publisher="rates snapshot"
          clock="instant"
        />,
      );
      const status = view.getByTestId("macro-replay-status");
      expect(status.getAttribute("data-replay-state")).toBe(verdict.kind);
      seen.add(status.textContent ?? "");
      view.unmount();
    }
    // Three states, three sentences. Collapsing any two is §9 invariant 2's failure.
    expect(seen.size).toBe(3);
  });

  it("never prescribes", () => {
    // §9 invariant 7, and the same runtime ban `gold-page.spec.ts` enforces on this desk.
    const view = render(
      <ReplayStatus
        verdict={{
          kind: "replaying",
          asOf: "2026-08-20",
          computedAt: "2026-08-19T22:15:00Z",
        }}
        publisher="rates snapshot"
        clock="instant"
      />,
    );
    const text = view.getByTestId("macro-replay-status").textContent ?? "";
    expect(text).not.toMatch(
      /\bbuy\b|\bsell\b|position size|predicted return/i,
    );
  });
});

describe("ReplayStatus — the ANSWER carries the clock too, not just the question", () => {
  // P4 discharged §10-H on the question side: `ReplayControl` reads the clock off the
  // registry and refuses to render one tab's picker copy over another tab's question.
  // These hold the other half. Every sentence in the instant family is instant-shaped —
  // "as it stood at the end of X UTC", "a replay that falls forward" — and all of it is
  // false of an `obs_date` row, which is matched exactly and is not a replay at all.
  const VERDICTS = [
    {
      kind: "replaying",
      asOf: "2026-08-20",
      computedAt: "2026-08-20T19:05:00Z",
    },
    { kind: "unanswered", asOf: "2026-08-20" },
    { kind: "request_failed", asOf: "2026-08-20" },
    {
      kind: "answered_after",
      asOf: "2026-08-20",
      computedAt: "2026-08-27T03:00:00Z",
    },
  ] as const;

  it("says something DIFFERENT for every verdict, in both clock families", () => {
    const seen = new Set<string>();
    for (const clock of ["instant", "obs_date"] as const) {
      for (const verdict of VERDICTS) {
        const view = render(
          <ReplayStatus
            verdict={verdict}
            publisher="gold posture"
            clock={clock}
          />,
        );
        const status = view.getByTestId("macro-replay-status");
        expect(status.getAttribute("data-replay-clock")).toBe(clock);
        expect(status.getAttribute("data-replay-state")).toBe(verdict.kind);
        seen.add(status.textContent ?? "");
        view.unmount();
      }
    }
    // Four verdicts × two clocks = eight distinct sentences. Any collapse means one
    // family borrowed the other's wording for that state, which is the whole failure.
    expect(seen.size).toBe(8);
  });

  it("never lets an obs-date answer borrow the instant family's promise", () => {
    for (const verdict of VERDICTS) {
      const view = render(
        <ReplayStatus
          verdict={verdict}
          publisher="gold posture"
          clock="obs_date"
        />,
      );
      const text = view.getByTestId("macro-replay-status").textContent ?? "";
      // `/api/gold/replay` is `WHERE obs_date = %s`. It does not answer "what the desk
      // knew at the end of a UTC day", and it does not fall forward or back.
      expect(text).not.toMatch(/end of 2026-08-20 UTC/);
      expect(text).not.toMatch(/falls forward/);
      // It names what it IS instead.
      expect(text).toMatch(/market day/i);
      view.unmount();
    }
  });

  it("leaves the instant family's shipped wording exactly as it was", () => {
    // Tabs 01-04 all stand on this copy; the obs-date family was added beside it, not
    // over it.
    render(
      <ReplayStatus
        verdict={{
          kind: "replaying",
          asOf: "2026-08-20",
          computedAt: "2026-08-19T22:15:00+00:00",
        }}
        publisher="inflation state"
        clock="instant"
      />,
    );
    const text = screen.getByTestId("macro-replay-status").textContent ?? "";
    expect(text).toMatch(/end of 2026-08-20 UTC/);
    expect(text).toMatch(/computed 2026-08-19 22:15 UTC/);
  });
});

describe("the registry declares a clock for every tab", () => {
  it("names one of the three questions, never leaves it to be inferred", () => {
    // The structural half of §10-H: a tab cannot inherit another tab's question by
    // omission, because there is no default to inherit.
    for (const tab of VALID_TABS) {
      expect(["instant", "obs_date", "none"]).toContain(tab.replayClock);
    }
    // And the one tab with no data path says so, rather than carrying a picker that
    // cannot do anything.
    expect(VALID_TABS.find((tab) => tab.slug === "notes")?.replayClock).toBe(
      "none",
    );
  });
});
