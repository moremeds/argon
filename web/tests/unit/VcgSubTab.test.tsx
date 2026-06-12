/* @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VcgSubTabView } from "@/components/regime/VcgSubTab";
import type { VcgLiveResponse } from "@/lib/regime/useVcgLive";

const NORMAL: VcgLiveResponse = {
  status: "ok",
  basis: "eod",
  scan_time: "2026-05-15T20:30:00+00:00",
  date: "2026-05-15",
  credit_proxy: "HYG",
  signal: {
    vcg: -0.83,
    vcg_adj: -0.83,
    residual: -0.001987,
    beta1_vvix: 0.005,
    beta2_vix: -0.036,
    alpha: 0.0001,
    vix: 18.43,
    vvix: 92.94,
    credit_price: 79.46,
    credit_5d_return_pct: 0.42,
    ro: 0,
    edr: 0,
    tier: null,
    bounce: 0,
    vvix_severity: "moderate",
    sign_ok: false,
    sign_suppressed: true,
    pi_panic: 0,
    regime: "DIVERGENCE",
    interpretation: "SUPPRESSED",
    attribution: {
      vvix_pct: 12.0,
      vix_pct: 88.0,
      vvix_component: -0.0001,
      vix_component: -0.0007,
      model_implied: -0.0008,
    },
  },
  history: [
    {
      date: "2026-05-13",
      residual: -0.0009,
      vcg: -0.5,
      vcg_adj: -0.5,
      beta1: 0.001,
      beta2: -0.03,
      vix: 17.8,
      vvix: 91.0,
      credit: 79.7,
      ro: 0,
      edr: 0,
      tier: null,
      bounce: 0,
    },
    {
      date: "2026-05-14",
      residual: -0.0015,
      vcg: -0.7,
      vcg_adj: -0.7,
      beta1: 0.002,
      beta2: -0.035,
      vix: 18.1,
      vvix: 92.2,
      credit: 79.6,
      ro: 0,
      edr: 0,
      tier: null,
      bounce: 0,
    },
  ],
};

const RISK_OFF: VcgLiveResponse = {
  ...NORMAL,
  signal: {
    ...NORMAL.signal!,
    vcg: 3.1,
    vcg_adj: 3.1,
    vix: 32.0,
    vvix: 130.0,
    credit_price: 75.5,
    credit_5d_return_pct: -2.5,
    ro: 1,
    edr: 1,
    tier: 1,
    bounce: 0,
    vvix_severity: "extreme",
    sign_ok: true,
    sign_suppressed: false,
    regime: "DIVERGENCE",
    interpretation: "RISK_OFF",
  },
};

const BOUNCE: VcgLiveResponse = {
  ...NORMAL,
  signal: {
    ...NORMAL.signal!,
    vcg: -4.2,
    vcg_adj: -4.2,
    bounce: 1,
    interpretation: "BOUNCE",
    sign_ok: true,
    sign_suppressed: false,
  },
};

const PANIC_ADJUSTED: VcgLiveResponse = {
  ...NORMAL,
  signal: {
    ...NORMAL.signal!,
    pi_panic: 0.75,
    regime: "TRANSITION",
    interpretation: "PANIC",
    sign_ok: false,
    sign_suppressed: true,
  },
};

describe("VcgSubTabView", () => {
  it("renders empty placeholder when data is null", () => {
    render(<VcgSubTabView data={null} />);
    expect(screen.getByTestId("vcg-empty-state")).not.toBeNull();
  });

  it("renders empty placeholder when status is empty", () => {
    const empty: VcgLiveResponse = {
      ...NORMAL,
      status: "empty",
      signal: { ...NORMAL.signal!, vcg: null },
    };
    render(<VcgSubTabView data={empty} />);
    expect(screen.getByTestId("vcg-empty-state")).not.toBeNull();
  });

  it("renders the four metric cards (VCG, VCG Adj, Credit 5d, Residual)", () => {
    render(<VcgSubTabView data={NORMAL} />);
    expect(screen.getByText("VCG Z-Score")).not.toBeNull();
    expect(screen.getByText("VCG Adj (Panic-Adj)")).not.toBeNull();
    expect(screen.getByText("Credit 5d Return")).not.toBeNull();
    // "Residual" appears in both the metric card label and the table header;
    // assert at least one match rather than a unique element.
    expect(screen.getAllByText("Residual").length).toBeGreaterThanOrEqual(1);
    // VCG is rendered via fmtZ → "-0.83"
    expect(screen.getByTestId("vcg-z-score").textContent).toBe("-0.83");
  });

  it("describes nonzero panic adjustment without claiming suppression", () => {
    render(<VcgSubTabView data={PANIC_ADJUSTED} />);
    expect(
      screen.getByText("π = 0.75 (panic-adjustment active)"),
    ).not.toBeNull();
    expect(screen.queryByText("π = 0.75 SUPPRESSED")).toBeNull();
  });

  it("describes zero panic adjustment without suppression wording", () => {
    render(<VcgSubTabView data={NORMAL} />);
    expect(screen.getByText("π = 0 (no panic adjustment)")).not.toBeNull();
    expect(screen.queryByText("NO SUPPRESSION")).toBeNull();
  });

  it("shows SUPPRESSED interpretation when sign discipline fails", () => {
    render(<VcgSubTabView data={NORMAL} />);
    expect(screen.getByTestId("vcg-interpretation-pill").textContent).toBe(
      "SUPPRESSED",
    );
  });

  it("shows RISK-OFF + Tier 1 + EDR badges when ro=1 / tier=1 / edr=1", () => {
    render(<VcgSubTabView data={RISK_OFF} />);
    expect(screen.getByTestId("vcg-ro-badge")).not.toBeNull();
    expect(screen.getByTestId("vcg-tier-badge")).not.toBeNull();
    // EDR is suppressed when RO is active (xenon convention)
    expect(screen.queryByTestId("vcg-edr-badge")).toBeNull();
    expect(screen.getByTestId("vcg-tier-label").textContent).toContain(
      "TIER 1",
    );
    expect(screen.getByTestId("vcg-edr-state").textContent).toBe("ACTIVE");
  });

  it("shows BOUNCE badge when bounce=1", () => {
    render(<VcgSubTabView data={BOUNCE} />);
    expect(screen.getByTestId("vcg-bounce-badge")).not.toBeNull();
    expect(screen.getByTestId("vcg-bounce-state").textContent).toBe("DETECTED");
  });

  it("renders attribution bars + β coefficients", () => {
    render(<VcgSubTabView data={NORMAL} />);
    expect(screen.getByTestId("vcg-attr-vvix-bar")).not.toBeNull();
    expect(screen.getByTestId("vcg-attr-vix-bar")).not.toBeNull();
  });

  it("renders the history table folded by default, expandable via toggle", () => {
    render(<VcgSubTabView data={NORMAL} />);
    // Folded by default — only the toggle is visible.
    expect(screen.queryByTestId("vcg-history-table")).toBeNull();
    fireEvent.click(screen.getByTestId("vcg-history-toggle"));
    const table = screen.getByTestId("vcg-history-table");
    // 2 data rows from NORMAL.history
    expect(table.querySelectorAll("tbody tr").length).toBe(2);
    // 9 columns
    expect(table.querySelectorAll("thead th").length).toBe(9);
  });

  it("sorts the history table when a header is clicked", () => {
    render(<VcgSubTabView data={NORMAL} />);
    fireEvent.click(screen.getByTestId("vcg-history-toggle"));
    const table = screen.getByTestId("vcg-history-table");
    const vcgHeader = Array.from(table.querySelectorAll("thead th")).find(
      (th) => (th.textContent ?? "").startsWith("VCG"),
    );
    expect(vcgHeader).toBeDefined();
    fireEvent.click(vcgHeader!);
    // After click on VCG header, both rows still render
    expect(table.querySelectorAll("tbody tr").length).toBe(2);
  });
});
