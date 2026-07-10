import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TechnicalsResponse } from "@/lib/api";
import { TechnicalsKinematicsChart } from "@/components/stock/panels/TechnicalsOscillators";

const data = {
  series: [
    {
      as_of: "2026-07-08",
      kin_slope20: 0.1,
      kin_slope50: 0.05,
      kin_slope200: 0.02,
    },
    {
      as_of: "2026-07-09",
      kin_slope20: 0.12,
      kin_slope50: 0.06,
      kin_slope200: 0.01,
    },
  ],
  detail: {
    kinematics: {
      sma20: { tstat: 14.2 },
      sma50: { tstat: 1.1 }, // weak: |t| < 2
      sma200: { tstat: 275.6 },
      alignment: -1,
    },
  },
} as unknown as TechnicalsResponse;

describe("TechnicalsKinematicsChart (blended trend)", () => {
  it("shows the current alignment badge", () => {
    const { getByText } = render(<TechnicalsKinematicsChart data={data} />);
    expect(getByText(/ALIGN.*-1\/3/i)).toBeTruthy();
  });

  it("surfaces each MA's t-stat so significance is legible", () => {
    const { getByText } = render(<TechnicalsKinematicsChart data={data} />);
    expect(getByText(/SMA200.*276/)).toBeTruthy(); // 275.6 -> t 276
    expect(getByText(/SMA50.*1\.1/)).toBeTruthy();
  });
});
