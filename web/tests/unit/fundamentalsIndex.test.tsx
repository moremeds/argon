import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RadarResponse } from "@/lib/api";

/**
 * The `/fundamentals` index and the routes that fold into it.
 *
 * Three redirects and one moved surface. The redirects are the whole point of
 * the task: `/radar` and `/chains` keep working as URLs (they are in people's
 * history and in this repo's own docs) while the desk becomes the one place
 * the hierarchy starts. A redirect that silently 404s is worse than no
 * redirect, so each target is asserted by name rather than "it redirected
 * somewhere".
 */

vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`REDIRECT:${to}`);
  },
}));

const radar = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: { ...actual.api, radar: (...a: unknown[]) => radar(...a) },
  };
});

// A spy standing in for the real table: this test pins the PAGE's wiring —
// that the fetched response reaches the component unchanged — not the table's
// own rendering, which is its own concern and unmodified by this task.
const seen: { data?: RadarResponse } = {};
vi.mock("@/components/radar/RadarTable", () => ({
  RadarTable: ({ data }: { data: RadarResponse }) => {
    seen.data = data;
    return <div data-testid="radar-table">{data.rows.length} rows</div>;
  },
}));

const RADAR: RadarResponse = {
  engine_version: "fundamentals-v2",
  tier: "ranked",
  as_of: "2026-08-16",
  rows: [
    {
      ticker: "COHR",
      state: "ok",
      composite: 0.41,
      as_of: "2026-08-16",
      dimensions: [],
    },
  ],
} as unknown as RadarResponse;

async function expectRedirect(importPath: string, target: string) {
  const mod = await import(/* @vite-ignore */ importPath);
  await expect((mod.default as () => Promise<unknown>)()).rejects.toThrow(
    `REDIRECT:${target}`,
  );
}

describe("the /fundamentals index", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    seen.data = undefined;
    radar.mockResolvedValue(RADAR);
  });

  it("sends /fundamentals to the one section that exists", async () => {
    await expectRedirect("@/app/fundamentals/page", "/fundamentals/ai-semi");
  });

  it("keeps the old /radar URL working by moving it under fundamentals", async () => {
    await expectRedirect("@/app/radar/page", "/fundamentals/radar");
  });

  it("folds /chains into the desk rather than leaving a parallel surface", async () => {
    await expectRedirect("@/app/chains/page", "/fundamentals/ai-semi");
  });
});

describe("the radar triage tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    seen.data = undefined;
    radar.mockResolvedValue(RADAR);
  });

  it("hands the fetched response to the table unchanged", async () => {
    const { default: Page } = await import("@/app/fundamentals/radar/page");
    render(await Page({ searchParams: Promise.resolve({}) }));
    expect(screen.getByTestId("radar-table")).not.toBeNull();
    expect(seen.data).toBe(RADAR);
    expect(radar).toHaveBeenCalledWith(
      expect.objectContaining({ tier: "ranked", limit: 300 }),
    );
  });

  it("passes the tier and engine through from the query string", async () => {
    const { default: Page } = await import("@/app/fundamentals/radar/page");
    render(
      await Page({
        searchParams: Promise.resolve({
          tier: "all",
          engine: "fundamentals-v1",
        }),
      }),
    );
    expect(radar).toHaveBeenCalledWith(
      expect.objectContaining({
        tier: "all",
        engine_version: "fundamentals-v1",
      }),
    );
  });

  it("renders a transport failure as a failure, never as a data state", async () => {
    radar.mockRejectedValue(new Error("API 500 for /api/radar: boom"));
    const { default: Page } = await import("@/app/fundamentals/radar/page");
    render(await Page({ searchParams: Promise.resolve({}) }));
    // `no_coverage` is a claim about companies. A broken request is a claim
    // about us, and rendering one as the other blames the companies for it.
    const alert = screen.getByRole("alert");
    expect(alert.textContent ?? "").toContain("500");
    expect(screen.queryByTestId("radar-table")).toBeNull();
  });
});

describe("the sidebar", () => {
  it("offers one Fundamentals entry and no bare Radar or Chains entry", async () => {
    const { NAV } = await import("@/components/shared/Sidebar");
    const hrefs = NAV.map((n) => n.href);
    expect(hrefs).toContain("/fundamentals");
    // Both old surfaces now redirect into the desk; a nav entry pointing at a
    // redirect is a second door to the same room, labelled as if it were a
    // different room.
    expect(hrefs).not.toContain("/radar");
    expect(hrefs).not.toContain("/chains");
  });
});
