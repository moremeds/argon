/* @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RegimePanel from "@/components/regime/RegimePanel";

// Stub the sub-tabs so this test doesn't depend on chart / fetch internals.
vi.mock("@/components/regime/GexSubTab", () => ({
  default: () => <div data-testid="gex-subtab-stub">GEX subtab</div>,
}));
vi.mock("@/components/regime/CriSubTab", () => ({
  default: () => <div data-testid="cri-subtab-stub">CRI subtab</div>,
}));
vi.mock("@/components/regime/VcgSubTab", () => ({
  default: () => <div data-testid="vcg-subtab-stub">VCG subtab</div>,
}));

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    }),
  );
});

describe("RegimePanel", () => {
  it("renders three sub-tab buttons with GEX active by default", () => {
    render(<RegimePanel />);
    expect(screen.getByTestId("regime-tab-cri").textContent).toBe("CRI");
    expect(screen.getByTestId("regime-tab-vcg").textContent).toBe("VCG");
    expect(screen.getByTestId("regime-tab-gex").textContent).toBe("GEX");
    expect(screen.getByTestId("regime-tab-gex").className).toMatch(/active/);
    expect(screen.queryByTestId("gex-subtab-stub")).not.toBeNull();
  });

  it("renders CRI subtab when CRI tab clicked", () => {
    render(<RegimePanel />);
    fireEvent.click(screen.getByTestId("regime-tab-cri"));
    expect(screen.queryByTestId("cri-subtab-stub")).not.toBeNull();
  });

  it("renders VCG subtab when VCG tab clicked", () => {
    render(<RegimePanel />);
    fireEvent.click(screen.getByTestId("regime-tab-vcg"));
    expect(screen.queryByTestId("vcg-subtab-stub")).not.toBeNull();
  });
});
