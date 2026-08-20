import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DealerPathChart, shortHorizon } from "@/components/rates/DealerPathChart";
import { SepDotPlot } from "@/components/rates/SepDotPlot";
import { POLICY_COMPARISON, type PolicyComparison } from "./fixture";

type Slot = PolicyComparison["committee_projection"];

const SEP = POLICY_COMPARISON.committee_projection;
const DEALER = POLICY_COMPARISON.dealer_expectations;

function withheldCopyOf(slot: Slot): Slot {
  return { ...slot, path: { ...slot.path!, source_kind: "mock" } };
}

describe("SepDotPlot", () => {
  it("draws one dot per participant, so dispersion is visible rather than summarised", () => {
    // 1 + 8 + 3 + 5 + 1 in the fixture's 2026 column, straight from parse_sep_release().
    const { container } = render(<SepDotPlot slot={SEP} />);

    expect(container.querySelectorAll("circle")).toHaveLength(18);
    expect(screen.getByText(/18 participants/)).toBeTruthy();
  });

  it("counts participants per horizon rather than summing the columns", () => {
    // Summing gives 18 for this fixture too, so make the columns disagree: a 71 on a
    // four-year plot reads as a participant count and is not one.
    const twoColumns: Slot = {
      ...SEP,
      path: {
        ...SEP.path!,
        points: [SEP.path!.points![0], SEP.path!.points![0]],
      },
    };
    render(<SepDotPlot slot={twoColumns} />);

    expect(screen.getByText(/18 participants/)).toBeTruthy();
    expect(screen.queryByText(/36/)).toBeNull();
  });

  it("renders a horizon whose dots the publisher did not break out", () => {
    // The fixture's 2027 column has a median and a central tendency but an empty
    // distribution. It must still appear -- a dropped column is a dropped year.
    render(<SepDotPlot slot={SEP} />);

    expect(screen.getByText("2027")).toBeTruthy();
    expect(screen.getByText("0 dots")).toBeTruthy();
  });

  it("attributes no dot to a named participant", () => {
    const { container } = render(<SepDotPlot slot={SEP} />);

    expect(screen.getByTestId("sep-plot-anonymity-note").textContent).toMatch(
      /anonymous/i,
    );
    expect(container.textContent).not.toMatch(/chair|powell/i);
    // Every dot's own tooltip has to stay anonymous too, not just the caption.
    for (const title of container.querySelectorAll("circle title")) {
      expect(title.textContent).toMatch(/anonymous/);
    }
  });

  it("says why it is empty instead of drawing an empty axis", () => {
    // A chart cannot render "unreadable release" -- a bare axis reads as a flat path,
    // which is a claim about rates that nobody published.
    render(<SepDotPlot slot={undefined} />);

    expect(screen.getByTestId("sep-dot-plot-missing").textContent).toMatch(
      /has not been ingested/,
    );
  });

  it("withholds a non-publisher source rather than plotting it", () => {
    const { container } = render(<SepDotPlot slot={withheldCopyOf(SEP)} />);

    expect(screen.getByTestId("sep-dot-plot-missing").textContent).toMatch(
      /not a publisher/,
    );
    expect(container.querySelectorAll("circle")).toHaveLength(0);
  });
});

describe("DealerPathChart", () => {
  it("draws the median as a path and the quartiles as a band", () => {
    const { container } = render(<DealerPathChart slot={DEALER} />);

    expect(container.querySelectorAll("polyline")).toHaveLength(1);
    expect(container.querySelector('[data-testid="dealer-path-band"]')).toBeTruthy();
    expect(container.querySelectorAll("circle")).toHaveLength(2);
  });

  it("reports the respondent count and whether it varies by horizon", () => {
    render(<DealerPathChart slot={DEALER} />);
    expect(screen.getByTestId("dealer-path-note").textContent).toMatch(
      /n=26 at every horizon/,
    );

    const shrinking: Slot = {
      ...DEALER,
      path: {
        ...DEALER.path!,
        points: [
          DEALER.path!.points![0],
          { ...DEALER.path!.points![1], respondent_count: 21 },
        ],
      },
    };
    render(<DealerPathChart slot={shrinking} />);
    expect(screen.getAllByTestId("dealer-path-note")[1].textContent).toMatch(
      /n varies by horizon, 21–26/,
    );
  });

  it("omits the band where the publisher printed no quartiles", () => {
    const noQuartiles: Slot = {
      ...DEALER,
      path: {
        ...DEALER.path!,
        points: DEALER.path!.points!.map((point) => ({
          ...point,
          p25_percent: null,
          p75_percent: null,
        })),
      },
    };
    const { container } = render(<DealerPathChart slot={noQuartiles} />);

    // No band beats a zero-width one: the second would draw "the dealers agreed".
    expect(container.querySelector('[data-testid="dealer-path-band"]')).toBeNull();
    expect(container.querySelectorAll("polyline")).toHaveLength(1);
  });

  it("says why it is empty instead of drawing an empty axis", () => {
    render(<DealerPathChart slot={undefined} />);

    expect(screen.getByTestId("dealer-path-missing").textContent).toMatch(
      /has not been ingested/,
    );
  });

  it("withholds a non-publisher source rather than plotting it", () => {
    const { container } = render(<DealerPathChart slot={withheldCopyOf(DEALER)} />);

    expect(screen.getByTestId("dealer-path-missing").textContent).toMatch(
      /not a publisher/,
    );
    expect(container.querySelectorAll("polyline")).toHaveLength(0);
  });
});

describe("shortHorizon", () => {
  it.each([
    ["Jun. 16-17 2026", "Jun 26"],
    ["Jul. 28-29 2026", "Jul 26"],
    ["2027 Q2", "27Q2"],
    ["2029", "2029"],
    // Nothing it does not recognise is silently dropped; sixteen crowded labels beat
    // one horizon that quietly disappeared off the axis.
    ["some horizon the survey invents next year", "some horizon the survey invents next year"],
  ])("%s -> %s", (input, expected) => {
    expect(shortHorizon(input)).toBe(expected);
  });
});
