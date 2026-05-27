import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RegimePill } from "@/components/regime/primitives/RegimePill";

describe("RegimePill", () => {
  it("renders Confirmed Canary label", () => {
    render(<RegimePill state="CONFIRMED_CANARY_ACTIVE" />);
    expect(screen.queryByText(/Confirmed Canary/i)).not.toBeNull();
  });

  it("renders Buy The Dip label", () => {
    render(<RegimePill state="BUY_THE_DIP_ACTIVE" />);
    expect(screen.queryByText(/Buy The Dip/i)).not.toBeNull();
  });

  it("renders Ambiguous for both-active", () => {
    render(<RegimePill state="BOTH_ACTIVE_AMBIGUOUS" />);
    expect(screen.queryByText(/Ambiguous/i)).not.toBeNull();
  });

  it("renders No Signal default", () => {
    render(<RegimePill state="NONE" />);
    expect(screen.queryByText(/No Signal/i)).not.toBeNull();
  });

  it("renders Neutral for speed-tier neutral days", () => {
    render(<RegimePill state="NEUTRAL" />);
    expect(screen.queryByText(/Neutral/i)).not.toBeNull();
  });
});
