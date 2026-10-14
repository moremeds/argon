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
    goldInputSeries: vi.fn(),
    goldFactor: vi.fn(),
    goldFlows: vi.fn(),
    macroDxy: vi.fn(),
  },
}));

describe("OverviewTab data binding", () => {
  beforeEach(() => {
    captureOverview.mockReset();
    vi.mocked(api.macroDomainState).mockReset().mockResolvedValue(null);
    vi.mocked(api.macroContextSnapshot).mockReset().mockResolvedValue(null);
    vi.mocked(api.macroPolicy).mockReset().mockResolvedValue(null);
    vi.mocked(api.goldInputSeries).mockReset().mockResolvedValue(null);
    vi.mocked(api.goldFactor).mockReset().mockResolvedValue(null);
    vi.mocked(api.goldFlows).mockReset().mockResolvedValue(null as never);
    vi.mocked(api.macroDxy)
      .mockReset()
      .mockResolvedValue({
        computed_at: "2026-10-13T21:40:00Z",
        last_date: "2026-10-13",
        points: [
          { obs_date: "2026-10-06", dxy: 98.1 },
          { obs_date: "2026-10-13", dxy: 99.0 },
        ],
      } as never);
  });

  it("bounds every replay series and skips the live-only gold and dollar reads", async () => {
    render(
      await OverviewTab({
        replay: { kind: "replay", asOf: "2026-08-22" },
      }),
    );

    expect(screen.getByTestId("overview-desk")).toBeTruthy();
    for (const [, range] of vi.mocked(api.goldInputSeries).mock.calls) {
      expect(range).toMatchObject({ asOf: "2026-08-22" });
    }
    expect(api.goldFactor).not.toHaveBeenCalled();
    expect(api.macroDxy).not.toHaveBeenCalled();
    const props = captureOverview.mock.calls[0][0];
    expect(props.deltas[3].spec.id).toBe("DXY");
    expect(props.deltas[3].points).toEqual([]);
    expect(props.deltas[3].error).toMatch(/not shown in replay/);
  });

  it("puts the synthetic DXY after the three yields when live", async () => {
    render(await OverviewTab({ replay: { kind: "live" } }));

    expect(api.goldFactor).toHaveBeenCalled();
    const ids = captureOverview.mock.calls[0][0].deltas.map(
      (d: { spec: { id: string } }) => d.spec.id,
    );
    expect(ids).toEqual(["DGS10", "DFII10", "T10YIE", "DXY", "VIXCLS"]);
    expect(
      captureOverview.mock.calls[0][0].deltas[3].points.map(
        (p: { value: string }) => p.value,
      ),
    ).toEqual(["98.1", "99"]);
  });
});
