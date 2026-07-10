/* @vitest-environment jsdom */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TechnicalsResponse } from "@/lib/api";
import {
  SigmoidFitChart,
  TechnicalsDetailPanels,
  sigmoidRejectReason,
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
          r2_sigmoid: 0.31,
          r2_linear: 0.05,
        })}
      />,
    );
    expect(container.querySelector('svg[role="img"]')).toBeNull();
    // The real failure here is the absolute-fit gate (0.31 < 0.80), NOT the
    // beats-linear gate — the copy must not falsely claim "0.31 ≤ 0.05 + 0.05".
    const msg = getByText(/No S-curve reported/i);
    expect(msg.textContent).toMatch(/too choppy/i);
    expect(msg.textContent).toMatch(/not an error/i);
    expect(msg.textContent).not.toMatch(/0\.05 \+ 0\.05/);
  });
});

describe("sigmoidRejectReason", () => {
  it("blames the weak absolute fit when R² is below 0.80", () => {
    const r = sigmoidRejectReason(0.31, 0.05);
    expect(r).toMatch(/too choppy/i);
    expect(r).toMatch(/31%/);
    expect(r).toMatch(/80%/);
  });

  it("blames the straight line when the sigmoid barely beats linear", () => {
    // 0.90 ≥ 0.80 but 0.90 < 0.88 + 0.05 → beats-linear gate fails.
    expect(sigmoidRejectReason(0.9, 0.88)).toMatch(/straight line/i);
  });

  it("blames curve direction when both R² gates pass (k must be ≤ 0)", () => {
    // 0.95 ≥ 0.80 and 0.95 ≥ 0.10 + 0.05 → only k ≤ 0 remains.
    expect(sigmoidRejectReason(0.95, 0.1)).toMatch(/wrong way/i);
  });

  it("reports missing history when R² is absent", () => {
    expect(sigmoidRejectReason(null, null)).toMatch(/not enough/i);
  });
});
