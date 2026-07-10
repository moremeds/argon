import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TechnicalsResponse } from "@/lib/api";
import {
  TechnicalsKinematicsChart,
  TechnicalsRsChart,
} from "@/components/stock/panels/TechnicalsOscillators";

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
  it("labels + reddens a bearish alignment badge", () => {
    // data has alignment: -1 -> a bearish lean, shown as BEAR + red.
    const { getByText } = render(<TechnicalsKinematicsChart data={data} />);
    const badge = getByText(/BEAR ALIGN 1\/3/i);
    expect(badge).toBeTruthy();
    expect(badge.style.color).toBe("var(--negative)");
  });

  it("labels + greens a bullish alignment badge", () => {
    const bull = {
      series: data.series,
      detail: {
        kinematics: {
          sma20: { tstat: 14.2 },
          sma50: { tstat: 1.1 },
          sma200: { tstat: 275.6 },
          alignment: 3,
        },
      },
    } as unknown as TechnicalsResponse;
    const { getByText } = render(<TechnicalsKinematicsChart data={bull} />);
    const badge = getByText(/BULL ALIGN 3\/3/i);
    expect(badge.style.color).toBe("var(--positive)");
  });

  it("surfaces each MA's t-stat so significance is legible", () => {
    const { getByText } = render(<TechnicalsKinematicsChart data={data} />);
    expect(getByText(/SMA200.*276/)).toBeTruthy(); // 275.6 -> t 276
    expect(getByText(/SMA50.*1\.1/)).toBeTruthy();
  });

  it("adds a plain-English reading of the current slopes", () => {
    // sma20 +14.2 & sma200 +275.6 are significant & rising; sma50 weak.
    const { getByText } = render(<TechnicalsKinematicsChart data={data} />);
    expect(getByText(/Reading:.*rising.*uptrend/i)).toBeTruthy();
  });

  it("shades the below-zero region so falling slopes read as a downtrend zone", () => {
    // slopes that dip below 0 -> the negative band must have real height.
    const down = {
      series: [
        {
          as_of: "2026-07-08",
          kin_slope20: -0.1,
          kin_slope50: -0.05,
          kin_slope200: 0.02,
        },
        {
          as_of: "2026-07-09",
          kin_slope20: -0.12,
          kin_slope50: -0.06,
          kin_slope200: 0.01,
        },
      ],
      detail: {
        kinematics: {
          sma20: { tstat: -14.2 },
          sma50: { tstat: -1.1 },
          sma200: { tstat: 3.0 },
          alignment: -1,
        },
      },
    } as unknown as TechnicalsResponse;
    const { container } = render(<TechnicalsKinematicsChart data={down} />);
    const shade = Array.from(container.querySelectorAll("rect")).find(
      (r) => r.getAttribute("fill") === "var(--negative)",
    );
    expect(shade).toBeTruthy();
    expect(Number(shade!.getAttribute("height"))).toBeGreaterThan(0);
  });

  it("does not shade other oscillators (the band is opt-in to kinematics)", () => {
    const rs = {
      series: [
        { as_of: "2026-07-08", rs_ratio: -0.2 },
        { as_of: "2026-07-09", rs_ratio: -0.3 },
      ],
      detail: { rs: { ratio: -0.3, trend: "LAGGING" } },
    } as unknown as TechnicalsResponse;
    const { container } = render(<TechnicalsRsChart data={rs} />);
    const shade = Array.from(container.querySelectorAll("rect")).find(
      (r) => r.getAttribute("fill") === "var(--negative)",
    );
    expect(shade).toBeUndefined();
  });
});
