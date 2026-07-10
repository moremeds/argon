/* @vitest-environment jsdom */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TechnicalsResponse } from "@/lib/api";
import {
  SigmoidFitChart,
  TechnicalsDetailPanels,
} from "@/components/stock/panels/TechnicalsDetailPanels";

const actual = [100, 101, 103, 108, 120, 140, 160, 175, 182, 185];
const fit = [100, 101, 104, 110, 122, 141, 159, 174, 181, 184];

describe("SigmoidFitChart", () => {
  it("draws an actual and a fitted path", () => {
    const { container } = render(<SigmoidFitChart actual={actual} fit={fit} />);
    expect(container.querySelector('svg[role="img"]')).toBeTruthy();
    // one path for the actual segment, one for the fitted logistic
    expect(container.querySelectorAll("path").length).toBeGreaterThanOrEqual(2);
  });
});

function panelData(sigmoid: Record<string, unknown>): TechnicalsResponse {
  return {
    detail: { sigmoid, distribution: {}, kinematics: {} },
  } as unknown as TechnicalsResponse;
}

describe("TechnicalsDetailPanels — sigmoid visualization", () => {
  it("charts the fit when the sigmoid is valid", () => {
    const { container } = render(
      <TechnicalsDetailPanels
        data={panelData({ valid: true, phase: "SATURATED", actual, fit })}
      />,
    );
    expect(container.querySelector('svg[role="img"]')).toBeTruthy();
  });

  it("leaves it blank (no chart) when the sigmoid is invalid", () => {
    const { container, getByText } = render(
      <TechnicalsDetailPanels
        data={panelData({
          valid: false,
          r2_sigmoid: 0.4,
          r2_linear: 0.5,
        })}
      />,
    );
    expect(container.querySelector('svg[role="img"]')).toBeNull();
    expect(getByText(/No S-curve structure/i)).toBeTruthy();
  });
});
