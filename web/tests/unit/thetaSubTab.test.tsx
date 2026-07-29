import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ThetaSubTab, {
  formatCredit,
  formatDelta,
  formatTheta,
  verdictLabel,
} from "@/components/scanner/theta/ThetaSubTab";

// ThetaSubTab fetches on mount. Stub the client so the render test exercises
// the warning banner, not the network — vitest runs with no API available.
vi.mock("@/lib/api", () => ({
  api: {
    thetaHarvester: () => Promise.resolve({ as_of: null, candidates: [] }),
    thetaHarvesterRescan: () => Promise.resolve({}),
    thetaHarvesterQuote: () => Promise.resolve({}),
  },
}));

describe("verdictLabel", () => {
  it("shortens the three radon verdicts for a dense table", () => {
    expect(verdictLabel("THETA_HARVEST")).toBe("TRUE THETA");
    expect(verdictLabel("DIRECTIONAL_DISGUISE")).toBe("DIRECTIONAL");
    expect(verdictLabel("WATCHLIST")).toBe("WATCH");
  });

  it("passes an unknown verdict through rather than blanking the cell", () => {
    expect(verdictLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });
});

describe("research-only warning", () => {
  it("is rendered — the DB table COMMENT is invisible to the operator", () => {
    render(<ThetaSubTab />);
    const warn = screen.getByTestId("theta-research-warning");
    expect(warn.textContent).toMatch(/undefined risk/i);
    expect(warn.textContent).toMatch(/not an argon trade proposal/i);
  });

  it("states the sweep verdict so the ranking is not read as an edge", () => {
    // The 2026-07-29 sweep found the score ORDERS (IC +0.075) but its selected
    // set does not pay. A table of scored rows with no such caption invites
    // exactly the misreading the whole measurement exercise was meant to avoid.
    render(<ThetaSubTab />);
    const warn = screen.getByTestId("theta-research-warning");
    expect(warn.textContent).toMatch(/ranks/i);
    expect(warn.textContent).toMatch(
      /does not.*profitab|no demonstrated edge/i,
    );
  });
});

describe("formatCredit", () => {
  it("marks a theoretical credit so it is never mistaken for a fill", () => {
    expect(formatCredit(4.15, null)).toBe("$4.15 theo");
  });

  it("prefers the live IB quote when one exists", () => {
    expect(formatCredit(4.15, 3.9)).toBe("$3.90 IB");
  });

  it("renders an em dash when there is no mark at all", () => {
    expect(formatCredit(null, null)).toBe("—");
  });
});

describe("formatDelta", () => {
  it("renders position delta in share equivalents", () => {
    expect(formatDelta(0.007)).toBe("+0.7 sh");
    expect(formatDelta(-0.004)).toBe("-0.4 sh");
  });

  it("normalises a negative that rounds to zero", () => {
    // Seen live: AVGO rendered "-0.0 sh", which reads as a formatting bug on
    // the one column that means "this is flat".
    expect(formatDelta(-0.0001)).toBe("0.0 sh");
    expect(formatDelta(-0)).toBe("0.0 sh");
  });
});

describe("formatTheta", () => {
  it("scales per-share theta to a per-contract daily figure", () => {
    expect(formatTheta(0.4643)).toBe("+46.43/day");
  });

  it("does not fake a plus sign on a negative theta", () => {
    // A negative here means the short position is PAYING decay, which the
    // gates are supposed to exclude — it must be visibly negative.
    expect(formatTheta(-0.01)).toBe("-1.00/day");
  });
});
