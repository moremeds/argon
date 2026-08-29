import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InputManifestPanel } from "@/components/gold/InputManifestPanel";
import type { components } from "@/lib/types";

type Provenance = components["schemas"]["GoldInputProvenance"];

// Real shapes from the orchestrator's manifest: DFII10 as read, COMEX inventory as a
// REQUIRED input whose window returned nothing (the genuine gap), and fx as one that is
// never read at all and not required (a recorded scope decision).
const INPUTS: Record<string, Provenance> = {
  DFII10: {
    obs_date: "2026-08-19",
    as_of: "2026-08-20T05:00:00Z",
    lens: ["L2"],
    causal_role: "decomposition_component",
    source: "fred",
    row_count: 1289,
    required: true,
    omission_reason: null,
  },
  exchange_inventory_daily: {
    obs_date: null,
    as_of: null,
    lens: ["L1"],
    causal_role: "supply",
    source: "comex",
    row_count: 0,
    required: true,
    omission_reason:
      "no rows in comex for exchange_inventory_daily at or before as_of",
  },
  fx: {
    obs_date: null,
    as_of: null,
    lens: ["L1"],
    causal_role: "curve",
    source: "none",
    row_count: 0,
    required: false,
    omission_reason: "compute_structural_posture is called with fx_rows=[]",
  },
  // Read, but old enough to reach the staleness table. cb reserves are quarterly by
  // nature, which is exactly why the table prints an age instead of a verdict.
  cb_gold_reserves_monthly: {
    obs_date: "2026-03-31",
    as_of: "2026-05-18T05:00:00Z",
    lens: ["L1"],
    causal_role: "supply",
    source: "wgc",
    row_count: 42,
    required: false,
    omission_reason: null,
  },
};

function renderPanel(inputs: Record<string, Provenance> = INPUTS) {
  return render(
    <InputManifestPanel
      obsDate="2026-08-19"
      computedAt="2026-08-20T05:00:00Z"
      inputsUsed={inputs}
    />,
  );
}

describe("InputManifestPanel", () => {
  it("leads with coverage, read over declared", () => {
    renderPanel();
    // The count is the whole point: a manifest that listed only what it had would read
    // as complete while naming half the inputs.
    const coverage = screen.getByTestId("gold-manifest-coverage");
    expect(coverage.textContent).toContain("2 read of 4 declared");
    expect(coverage.textContent).toContain("50% coverage");
  });

  it("separates a required omission from a recorded scope decision", () => {
    renderPanel();
    // Flattening these into one "missing" list turns a deliberate boundary into a
    // pipeline failure and hides the row that actually wants fixing.
    const gaps = screen.getByTestId("gold-manifest-gaps");
    expect(gaps.textContent).toContain("exchange_inventory_daily");
    expect(gaps.textContent).not.toContain("fx");

    const decisions = screen.getByTestId("gold-manifest-decisions");
    expect(decisions.textContent).toContain("fx");
    expect(decisions.textContent).not.toContain("exchange_inventory_daily");
  });

  it("renders an omission as a decision, never as obs null", () => {
    renderPanel();
    const decisions = screen.getByTestId("gold-manifest-decisions");
    expect(decisions.textContent).toContain("not read");
    expect(decisions.textContent).not.toContain("null");
  });

  it("gives each omission its reason", () => {
    renderPanel();
    expect(screen.getByTestId("gold-manifest-gaps").textContent).toContain(
      "no rows in comex",
    );
    expect(screen.getByTestId("gold-manifest-decisions").textContent).toContain(
      "fx_rows=[]",
    );
  });

  it("keeps read inputs out of both omission lists", () => {
    renderPanel();
    expect(screen.getByTestId("gold-manifest-gaps").textContent).not.toContain(
      "DFII10",
    );
    expect(
      screen.getByTestId("gold-manifest-decisions").textContent,
    ).not.toContain("DFII10");
  });

  it("ages a stale read against the observation date, not today", () => {
    renderPanel();
    // 2026-03-31 -> 2026-08-19 is 141 days. Keying this on the observation makes the
    // assertion stable; keying it on `Date.now()` would date-bomb on the next calendar
    // roll and quietly re-measure something else.
    const stale = screen.getByTestId("gold-manifest-stale");
    expect(
      stale.querySelector('[data-raw-value="cb_gold_reserves_monthly"]'),
    ).toBeTruthy();
    expect(stale.textContent).toContain("Central-bank gold reserves");
    expect(stale.textContent).toContain("~141d");
    // A freshly-read input is not stale and must not appear.
    expect(stale.textContent).not.toContain("DFII10");
  });

  it("labels each input with the lenses that consume it", () => {
    renderPanel();
    expect(screen.getByTestId("gold-manifest-decisions").textContent).toContain(
      "[L1]",
    );
  });

  it("renders no omission lists when every input was read", () => {
    renderPanel({ DFII10: INPUTS.DFII10 });
    expect(screen.queryByTestId("gold-manifest-gaps")).toBeNull();
    expect(screen.queryByTestId("gold-manifest-decisions")).toBeNull();
  });

  it("renders no staleness table when every read input is current", () => {
    renderPanel({ DFII10: INPUTS.DFII10 });
    expect(screen.queryByTestId("gold-manifest-stale")).toBeNull();
  });
});
