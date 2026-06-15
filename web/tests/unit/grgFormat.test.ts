import { describe, expect, it } from "vitest";
import {
  formatNumber,
  formatPercent,
  formatSignedNumber,
} from "@/components/regime/primitives/format";
import {
  assetStateHelp,
  fmtGex,
  gateColor,
  pairStateColor,
  shortState,
  sigmaColor,
} from "@/components/regime/GrgSubTab";

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

describe("GRG event helpers (Recent Tops/Bottoms)", () => {
  it("pairStateColor: risk-off/dual-whip negative, risk-on/dual-cushion positive", () => {
    expect(pairStateColor("RISK_OFF_DIVERGENCE")).toBe("var(--negative)");
    expect(pairStateColor("DUAL_WHIP")).toBe("var(--negative)");
    expect(pairStateColor("RISK_ON_DIVERGENCE")).toBe("var(--positive)");
    expect(pairStateColor("DUAL_CUSHION")).toBe("var(--positive)");
    expect(pairStateColor("NEUTRAL")).toBe("var(--text-muted)");
    expect(pairStateColor(null)).toBe("var(--text-muted)");
  });

  it("shortState abbreviates the pair state", () => {
    expect(shortState("RISK_OFF_DIVERGENCE")).toBe("RISK-OFF");
    expect(shortState("RISK_ON_DIVERGENCE")).toBe("RISK-ON");
    expect(shortState("DUAL_WHIP")).toBe("DUAL WHIP");
    expect(shortState(undefined)).toBe("NEUTRAL");
  });

  it("sigmaColor: colors by sign so -0.79 reads negative", () => {
    expect(sigmaColor(-0.79)).toBe("var(--negative)");
    expect(sigmaColor(2.06)).toBe("var(--positive)");
    expect(sigmaColor(null)).toBe("var(--text-muted)");
  });

  it("assetStateHelp: scoped to the asset's own state", () => {
    expect(assetStateHelp("WHIP")).toMatch(/^WHIP:/);
    expect(assetStateHelp("WHIP")).not.toMatch(/CUSHION/);
    expect(assetStateHelp("CUSHION")).toMatch(/^CUSHION:/);
    expect(assetStateHelp("CUSHION")).not.toMatch(/WHIP/);
    expect(assetStateHelp("NEUTRAL")).toMatch(/^NEUTRAL:/);
    expect(assetStateHelp(null)).toMatch(/^NEUTRAL:/);
  });
});
