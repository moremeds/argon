import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { SetupBadge } from "@/components/watchlist/SetupBadge";

describe("SetupBadge", () => {
  it("renders C-BULL in positive color", () => {
    const { getByText } = render(<SetupBadge type="C" direction="bull" />);
    expect(getByText("C-BULL")).toBeTruthy();
  });
  it("renders C-BEAR in negative color", () => {
    const { getByText } = render(<SetupBadge type="C" direction="bear" />);
    expect(getByText("C-BEAR")).toBeTruthy();
  });
  it("renders F-MULTI for F setup", () => {
    const { getByText } = render(<SetupBadge type="F" direction={null} />);
    expect(getByText("F-MULTI")).toBeTruthy();
  });
  it("renders NEUTRAL for null setup", () => {
    const { getByText } = render(<SetupBadge type={null} direction={null} />);
    expect(getByText("NEUTRAL")).toBeTruthy();
  });
});
