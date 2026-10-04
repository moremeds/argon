/* @vitest-environment jsdom */
// Null-rendering cases for the regime GEX views. Every case deep-clones the
// REAL SPX GEX payload (tests/fixtures/mcp/spx_regime_gex.json) and nulls or
// deletes only the field under test. A missing market value must render as
// missing — never as 0, never in the positive/negative colour, never a crash.
import { fireEvent, render } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import gexFixture from "@/tests/fixtures/mcp/spx_regime_gex.json";

const state = vi.hoisted(() => ({ data: null as unknown }));

vi.mock("@/lib/regime/useGex", async (orig) => ({
  ...(await orig<typeof import("@/lib/regime/useGex")>()),
  useGex: () => ({
    data: state.data,
    loading: false,
    syncing: false,
    error: null,
    lastSync: gexFixture.scan_time,
    syncNow: () => undefined,
  }),
}));

import GexSubTab from "@/components/regime/GexSubTab";
import { ExpectedRangeBar } from "@/components/regime/gex/ExpectedRangeBar";
import { GexHistoryTable } from "@/components/regime/gex/GexHistoryTable";
import { MqLevelsPanel } from "@/components/regime/gex/MqLevelsPanel";
import GexCurvatureChart from "@/components/shared/GexCurvatureChart";
import { retagProfileForSpot } from "@/lib/regime/derive/gex";
import type {
  GexBucket,
  GexData,
  MqLevels,
  SourceDelta,
} from "@/lib/regime/useGex";

// Mutable deep clone of the real payload; tests edit only the field(s) under
// test. Typed loosely so a test can delete a field the API always sends.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Loose = any;
function realGex(): Loose {
  return structuredClone(gexFixture);
}

function dom(html: string): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = html;
  return el;
}

function renderSubTab(data: Loose): HTMLElement {
  state.data = data;
  return dom(renderToStaticMarkup(<GexSubTab />));
}

/** The `.gex-metric-card` whose label starts with `label`. */
function metricCard(root: HTMLElement, label: string): HTMLElement {
  const card = Array.from(
    root.querySelectorAll<HTMLElement>(".gex-metric-card"),
  ).find((c) =>
    c.querySelector(".gex-metric-label")?.textContent?.startsWith(label),
  );
  if (!card) throw new Error(`metric card ${label} not found`);
  return card;
}

const POSITIVE = "var(--signal-core)";
const NEGATIVE = "var(--fault)";

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-24T14:00:00Z"));
});
afterAll(() => {
  vi.useRealTimers();
});

describe("ExpectedRangeBar (bug 1)", () => {
  it("renders nothing when expected_range is absent", () => {
    const d = realGex();
    delete d.expected_range;
    expect(renderToStaticMarkup(<ExpectedRangeBar data={d} />)).toBe("");
  });

  it("renders the band without level markers when levels is absent", () => {
    const d = realGex();
    delete d.levels;
    const html = renderToStaticMarkup(<ExpectedRangeBar data={d} />);
    expect(html).toContain("SPOT");
    expect(html).not.toContain("GEX FLIP");
    expect(html).not.toContain("MAX MAGNET");
  });
});

describe("GexSubTab", () => {
  it("bug 2: absent bias renders the missing bias, no crash", () => {
    const d = realGex();
    delete d.bias;
    const root = renderSubTab(d);
    const dir = root.querySelector(".gex-bias-direction")!;
    expect(dir.textContent).toBe("---");
    expect(
      dir.parentElement!.querySelectorAll(".gex-bias-reason"),
    ).toHaveLength(0);
    expect(root.querySelector(".gex-day-badge")).toBeNull();
  });

  it("bug 2: absent levels renders every level card as missing, no crash", () => {
    const d = realGex();
    delete d.levels;
    const root = renderSubTab(d);
    const values = Array.from(root.querySelectorAll(".gex-level-value")).map(
      (n) => n.textContent,
    );
    expect(values).toEqual(["---", "---", "---", "---", "---"]);
    expect(
      metricCard(root, "GEX FLIP").querySelector(".gex-metric-value")!
        .textContent,
    ).toBe("---");
  });

  it("bug 3: null days_above_flip shows no day badge (no AT, no 0)", () => {
    const d = realGex();
    d.bias.days_above_flip = null;
    const root = renderSubTab(d);
    expect(root.querySelector(".gex-day-badge")).toBeNull();
    expect(root.textContent).not.toMatch(/AT GEX FLIP/);
  });

  it("bug 4: null net_gex / net_dex render missing in a neutral colour", () => {
    const d = realGex();
    d.net_gex = null;
    d.net_dex = null;
    const root = renderSubTab(d);
    for (const label of ["NET GEX", "NET DEX"]) {
      const v = metricCard(root, label).querySelector(".gex-metric-value")!;
      expect(v.textContent).toBe("---");
      const style = v.getAttribute("style") ?? "";
      expect(style).not.toContain(POSITIVE);
      expect(style).not.toContain(NEGATIVE);
    }
  });

  it("bug 5: absent expected_range (and no iv_rank) does not crash", () => {
    const d = realGex();
    delete d.expected_range;
    d.iv.iv_rank = null;
    const root = renderSubTab(d);
    // No iv_rank and no iv_1d → the IV 30D card has no sub line.
    expect(
      metricCard(root, "IV 30D").querySelector(".gex-metric-sub"),
    ).toBeNull();
  });

  it.each([["unknown"], [null]])(
    "bug 6: iv.source %s renders no source badge",
    (source) => {
      const d = realGex();
      d.iv.source = source;
      const root = renderSubTab(d);
      const label = metricCard(root, "IV 30D").querySelector(
        ".gex-metric-label",
      )!;
      // SourceBadge is the only span in the label carrying padding 1px 5px.
      expect(label.innerHTML).not.toContain("padding:1px 5px");
    },
  );

  it("bug 6 control: a known iv.source still renders its badge", () => {
    const root = renderSubTab(realGex());
    const label = metricCard(root, "IV 30D").querySelector(
      ".gex-metric-label",
    )!;
    expect(label.textContent).toContain("UW");
  });

  it("bug 7: null bias.direction renders the missing label, neutral colour", () => {
    const d = realGex();
    d.bias.direction = null;
    const root = renderSubTab(d);
    const dir = root.querySelector(".gex-bias-direction")!;
    expect(dir.textContent).toBe("---");
    const style = dir.getAttribute("style") ?? "";
    expect(style).not.toContain(POSITIVE);
    expect(style).not.toContain(NEGATIVE);
    // Reasons still render from the real payload.
    expect(
      dir.parentElement!.querySelectorAll(".gex-bias-reason"),
    ).toHaveLength(gexFixture.bias.reasons.length);
  });

  it("bug 8: null spot (no live spot) renders the chart without a spot rule", () => {
    const d = realGex();
    d.spot = null;
    const root = renderSubTab(d);
    const title = root.querySelector(".gex-profile-chart svg title")!;
    expect(title.textContent).toBe("Net GEX by strike; spot ---");
    expect(
      root.querySelector(".gex-profile-chart svg")!.textContent,
    ).not.toMatch(/SPOT /);
  });
});

describe("GexHistoryTable (bug 9)", () => {
  it("renders a null net_gex as missing in a neutral colour", () => {
    const d = realGex();
    const date = d.history[0].date;
    d.history[0].net_gex = null;
    const { container, getByText } = render(
      <GexHistoryTable history={d.history} />,
    );
    fireEvent.click(getByText(/History \(/));
    const row = Array.from(container.querySelectorAll("tr")).find(
      (r) => r.querySelector("td")?.textContent === date,
    )!;
    const cell = row.querySelectorAll("td")[3];
    expect(cell.textContent).toBe("---");
    const style = cell.getAttribute("style") ?? "";
    expect(style).not.toContain(POSITIVE);
    expect(style).not.toContain(NEGATIVE);
  });
});

describe("MqLevelsPanel (bug 10)", () => {
  // The real payload has mq: null and source_delta: null. These objects are
  // built ONLY from fields of the real payload (its spot and UW level
  // strikes); the MQ-side values under test are null, nothing is invented.
  function realMq(): MqLevels {
    return {
      source_date: gexFixture.data_date,
      spot: gexFixture.spot,
      hvl: null,
      call_resistance_all: null,
      call_resistance_0dte: null,
      put_support_all: null,
      put_support_0dte: null,
      expected_high: gexFixture.expected_range.high,
      expected_low: gexFixture.expected_range.low,
      distance_to_hvl_pct: null,
      iv30d: null,
      hv30: null,
      iv_rank: null,
      top_gex_strikes: [],
    };
  }

  it("renders null delta / uw / mq inside a present entry as missing, no crash", () => {
    const sd: SourceDelta = {
      flip_vs_hvl: {
        uw: gexFixture.levels.gex_flip.strike,
        mq: null,
        delta: null,
      },
      put_wall_vs_support_all: {
        uw: null,
        mq: null,
        delta: null,
      },
      put_wall_vs_support_0dte: null,
      call_wall_vs_resistance_all: null,
      call_wall_vs_resistance_0dte: null,
    };
    const { container, getByText } = render(
      <MqLevelsPanel mq={realMq()} sourceDelta={sd} />,
    );
    fireEvent.click(getByText(/MenthorQ Key Levels/));
    const text = container.textContent ?? "";
    expect(text).toContain("Flip vs HVL");
    // The real UW flip strike is shown; the null MQ side is a dash.
    expect(text).toContain("7725");
    expect(text).not.toMatch(/NaN|null|undefined/);
  });
});

describe("GexCurvatureChart (bugs 11, 12)", () => {
  const profile = (): GexBucket[] => structuredClone(gexFixture.profile);
  const LEFT = 72; // PAD.left: the x of the smallest plotted strike.

  /** Points of the stroke path (the fill="none" path). */
  function linePoints(container: HTMLElement): [number, number][] {
    const d = container.querySelector('path[fill="none"]')!.getAttribute("d")!;
    return Array.from(d.matchAll(/[ML]\s*([-\d.]+)[ ,]([-\d.]+)/g)).map((m) => [
      Number(m[1]),
      Number(m[2]),
    ]);
  }

  it("drops null-strike and null-net_gex buckets; never plots them at 0", () => {
    const p = profile();
    p[0].strike = null; // the smallest strike
    p[10].net_gex = null;
    const { container } = render(
      <GexCurvatureChart profile={p} spot={gexFixture.spot} />,
    );
    const pts = linePoints(container as HTMLElement);
    expect(pts).toHaveLength(p.length - 2);
    // x-domain starts at the smallest NON-null strike (p[1]), not at 0.
    expect(pts[0][0]).toBeCloseTo(LEFT, 6);
    // No real bucket has net_gex 0, so no point may sit on the zero line.
    const zeroY = Number(
      container
        .querySelector('line[stroke="var(--border-dim)"]')!
        .getAttribute("y1"),
    );
    expect(pts.some(([, y]) => Math.abs(y - zeroY) < 1e-9)).toBe(false);
  });

  it("renders its insufficient state when fewer than 2 usable buckets remain", () => {
    const p = profile().map((b, i) => (i === 0 ? b : { ...b, net_gex: null }));
    const { container } = render(
      <GexCurvatureChart profile={p} spot={gexFixture.spot} />,
    );
    expect(container.textContent).toContain("Not enough strikes");
  });

  it("bug 12: hovering where a null-strike bucket would sort does not crash", () => {
    const p = profile();
    p[0].strike = null;
    const { container } = render(
      <GexCurvatureChart profile={p} spot={gexFixture.spot} />,
    );
    const svg = container.querySelector("svg")!;
    svg.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 1000, height: 320 }) as DOMRect;
    fireEvent.mouseMove(svg, { clientX: LEFT, clientY: 100 });
    expect(container.textContent).toContain(
      `STRIKE ${gexFixture.profile[1].strike.toLocaleString()}`,
    );
  });

  it("bug 12: the readout never lands on a null-net_gex bucket", () => {
    const p = profile();
    // Null the net_gex of the bucket nearest spot: the default readout target.
    const spot = gexFixture.spot;
    const nearest = p.reduce(
      (best, b, i) =>
        Math.abs(b.strike! - spot) < Math.abs(p[best].strike! - spot)
          ? i
          : best,
      0,
    );
    p[nearest].net_gex = null;
    const { container } = render(<GexCurvatureChart profile={p} spot={spot} />);
    const readout = Array.from(container.querySelectorAll("span")).find((s) =>
      s.textContent?.startsWith("NET GEX "),
    )!;
    const value = readout.querySelector("span")!;
    expect(value.textContent).not.toBe("---");
  });

  it("bug 12: a null spot renders the missing marker, no spot rule", () => {
    const { container } = render(
      <GexCurvatureChart profile={profile()} spot={null} />,
    );
    expect(container.querySelector("svg title")!.textContent).toBe(
      "Net GEX by strike; spot ---",
    );
    expect(container.querySelector("svg")!.textContent).not.toMatch(/SPOT /);
  });
});

describe("retagProfileForSpot (bug 13)", () => {
  it("never tags or measures a null-strike bucket", () => {
    const d = realGex() as GexData;
    const p = structuredClone(d.profile!);
    // Make the null-strike bucket carry a stale SPOT tag to prove it is cleared.
    p[0] = { ...p[0], strike: null, pct_from_spot: null, tag: "SPOT" };
    const out = retagProfileForSpot(p, d.spot as number, d.levels);
    expect(out[0].pct_from_spot).toBeNull();
    expect(out[0].tag).toBeNull();
    expect(out[0].net_gex).toBe(p[0].net_gex);
    // Every other bucket is tagged exactly as if the null bucket were absent.
    expect(out.slice(1)).toEqual(
      retagProfileForSpot(p.slice(1), d.spot as number, d.levels),
    );
  });

  it("is not picked nearest even when the live spot is near 0", () => {
    const d = realGex() as GexData;
    const p = structuredClone(d.profile!);
    p[0] = { ...p[0], strike: null, pct_from_spot: null, tag: null };
    // A tiny live spot: |null - spot| == spot would win "nearest" before.
    const out = retagProfileForSpot(p, 1, null);
    expect(out[0].tag).toBeNull();
    expect(out[0].pct_from_spot).toBeNull();
    expect(out[1].tag).toBe("SPOT");
  });
});
