/* @vitest-environment jsdom */
// MenthorQ fields on the GEX tab with missing values. The real SPX payload
// (tests/fixtures/mcp/spx_regime_gex.json) has `mq: null` and
// `source_delta: null`, so each case builds the `mq` object from fields of that
// same payload (its data_date and gex_flip strike) and nulls the rest. Written
// before the `mq as MqLevels` / `source_delta as ...` / `hvl as number` casts
// were removed; it must pass unchanged after.
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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Loose = any;
const FLIP_STRIKE: number = gexFixture.levels.gex_flip.strike;

/** Real payload without a UW flip, plus an MQ block whose HVL is `hvl`. */
function withMq(hvl: number | null): Loose {
  const d: Loose = structuredClone(gexFixture);
  d.levels.gex_flip = null;
  d.mq = {
    source_date: d.data_date,
    spot: null,
    hvl,
    call_resistance_all: null,
    call_resistance_0dte: null,
    put_support_all: null,
    put_support_0dte: null,
    expected_high: null,
    expected_low: null,
    distance_to_hvl_pct: null,
    iv30d: null,
    hv30: null,
    iv_rank: null,
    top_gex_strikes: [],
  };
  return d;
}

function flipCard(root: HTMLElement): HTMLElement {
  const card = Array.from(
    root.querySelectorAll<HTMLElement>(".gex-metric-card"),
  ).find((c) =>
    c.querySelector(".gex-metric-label")?.textContent?.startsWith("GEX FLIP"),
  );
  if (!card) throw new Error("GEX FLIP card not found");
  return card;
}

function staticRoot(data: Loose): HTMLElement {
  state.data = data;
  const el = document.createElement("div");
  el.innerHTML = renderToStaticMarkup(<GexSubTab />);
  return el;
}

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-24T14:00:00Z"));
});
afterAll(() => {
  vi.useRealTimers();
});

describe("GEX FLIP falls back to the MQ HVL", () => {
  it("shows the MQ HVL when UW has no flip", () => {
    const card = flipCard(staticRoot(withMq(FLIP_STRIKE)));
    expect(card.textContent).toContain(
      FLIP_STRIKE.toLocaleString("en-US", { minimumFractionDigits: 2 }),
    );
    expect(card.textContent).toContain("MQ HVL");
  });

  it("shows the missing marker, not an MQ value, when the HVL is null too", () => {
    const card = flipCard(staticRoot(withMq(null)));
    expect(card.textContent).toContain("---");
    expect(card.textContent).not.toContain("MQ HVL");
  });
});

describe("MqLevelsPanel with missing levels and no source delta", () => {
  it("renders every missing level as the dash, without a crash", () => {
    const d = withMq(null);
    delete d.source_delta; // absent, not just null
    state.data = d;
    const { container } = render(<GexSubTab />);
    const toggle = container.querySelector<HTMLButtonElement>(".gex-mq-toggle");
    expect(toggle).not.toBeNull();
    fireEvent.click(toggle!);
    const levels = Array.from(container.querySelectorAll("span")).filter(
      (s) => s.textContent === "—",
    );
    expect(levels.length).toBeGreaterThanOrEqual(7);
    expect(container.textContent).not.toMatch(/NaN|undefined/);
  });
});
