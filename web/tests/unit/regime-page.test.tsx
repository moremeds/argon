/* @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RegimePanel from "@/components/regime/RegimePanel";

// Stub GexSubTab so this test doesn't depend on d3 / fetch internals.
vi.mock("@/components/regime/GexSubTab", () => ({
  default: () => <div data-testid="gex-subtab-stub">GEX subtab</div>,
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

  it("shows pending placeholder on CRI tab", () => {
    render(<RegimePanel />);
    fireEvent.click(screen.getByTestId("regime-tab-cri"));
    expect(screen.queryByTestId("regime-pending-cri")).not.toBeNull();
    expect(screen.queryByText(/coming soon/i)).not.toBeNull();
  });

  it("shows pending placeholder on VCG tab", () => {
    render(<RegimePanel />);
    fireEvent.click(screen.getByTestId("regime-tab-vcg"));
    expect(screen.queryByTestId("regime-pending-vcg")).not.toBeNull();
  });
});
