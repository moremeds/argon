/* @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GuidancePanel } from "@/components/regime/GuidancePanel";

const FAKE = {
  state: "low_contango",
  posture: "opportunistic",
  body_md: "**LOW + contango.** Vol is cheap.",
  matched_condition: "level == 'LOW' and vix_vix3m_ratio < 0.95",
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => FAKE })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GuidancePanel", () => {
  it("renders the active rule's state and posture", async () => {
    render(<GuidancePanel />);
    await waitFor(() =>
      expect(screen.getByTestId("guidance-panel")).not.toBeNull(),
    );
    expect(screen.getByTestId("guidance-posture").textContent).toBe(
      "OPPORTUNISTIC",
    );
  });

  it("stays silent on fetch failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 500 })),
    );
    const { container } = render(<GuidancePanel />);
    await new Promise((r) => setTimeout(r, 50));
    expect(
      container.querySelector('[data-testid="guidance-panel"]'),
    ).toBeNull();
  });
});
