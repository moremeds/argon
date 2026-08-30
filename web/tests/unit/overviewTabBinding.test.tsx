/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OverviewTab } from "@/app/macro/[tab]/overviewTab";
import { api } from "@/lib/api";

const { captureOverview } = vi.hoisted(() => ({
  captureOverview: vi.fn(),
}));

vi.mock("@/components/macro/OverviewDesk", () => ({
  OverviewDesk: (props: unknown) => {
    captureOverview(props);
    return <div data-testid="overview-desk" />;
  },
}));

vi.mock("@/lib/api", () => ({
  api: {
    macroDomainState: vi.fn(),
    macroContextSnapshot: vi.fn(),
    macroPolicy: vi.fn(),
    goldGauge: vi.fn(),
    goldInputSeries: vi.fn(),
  },
}));

describe("OverviewTab data binding", () => {
  beforeEach(() => {
    captureOverview.mockReset();
    vi.mocked(api.macroDomainState).mockReset().mockResolvedValue(null);
    vi.mocked(api.macroContextSnapshot).mockReset().mockResolvedValue(null);
    vi.mocked(api.macroPolicy).mockReset().mockResolvedValue(null);
    vi.mocked(api.goldInputSeries).mockReset().mockResolvedValue(null);
    vi.mocked(api.goldGauge)
      .mockReset()
      .mockResolvedValue({ current: {}, history_252d: [] } as never);
  });

  it("bounds every replay series and tolerates an old gauge response", async () => {
    render(
      await OverviewTab({
        replay: { kind: "replay", asOf: "2026-08-22" },
      }),
    );

    expect(screen.getByTestId("overview-desk")).toBeTruthy();
    expect(api.goldGauge).toHaveBeenCalledWith("2026-08-22");
    for (const [, range] of vi.mocked(api.goldInputSeries).mock.calls) {
      expect(range).toMatchObject({ asOf: "2026-08-22" });
    }
    expect(captureOverview.mock.calls[0][0].gauge.value.history_60d).toEqual(
      [],
    );
  });
});
