import { describe, expect, it } from "vitest";
import {
  formatNumber,
  formatPercent,
  formatSignedNumber,
} from "@/components/regime/primitives/format";
import { fmtGex, gateColor } from "@/components/regime/GrgSubTab";

describe("regime format primitives (used by GRG)", () => {
  it("formats null as ---", () => {
    expect(formatNumber(null)).toBe("---");
    expect(formatPercent(undefined)).toBe("---");
    expect(formatSignedNumber(null)).toBe("---");
  });

  it("signs positive numbers", () => {
    expect(formatSignedNumber(0.04)).toBe("+0.04");
    expect(formatPercent(0.24)).toBe("+0.24%");
  });

  it("keeps negative sign", () => {
    expect(formatSignedNumber(-0.79)).toBe("-0.79");
  });
});

describe("GRG fmtGex (signed magnitude, radon style)", () => {
  it("renders K/M magnitudes with sign", () => {
    expect(fmtGex(-702100)).toBe("-702.1K");
    expect(fmtGex(7700000)).toBe("+7.7M");
    expect(fmtGex(0)).toBe("0");
  });
  it("renders --- for null/NaN", () => {
    expect(fmtGex(null)).toBe("---");
    expect(fmtGex(undefined)).toBe("---");
  });
});

describe("GRG gateColor", () => {
  it("maps statuses to tokens", () => {
    expect(gateColor("PASS")).toBe("var(--positive)");
    expect(gateColor("FAIL")).toBe("var(--negative)");
    expect(gateColor("WATCH")).toBe("var(--warning)");
  });
});
