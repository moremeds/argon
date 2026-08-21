import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataAuditFooter } from "@/components/gold/DataAuditFooter";
import type { components } from "@/lib/types";

type Provenance = components["schemas"]["GoldInputProvenance"];

// Real shapes from the orchestrator's manifest: DFII10 as read, COMEX inventory as an
// input whose window returned nothing, and fx as one that is never read at all.
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
};

function renderFooter(inputs: Record<string, Provenance> = INPUTS) {
  return render(
    <DataAuditFooter
      obsDate="2026-08-19"
      computedAt="2026-08-20T05:00:00Z"
      inputsUsed={inputs}
    />,
  );
}

describe("DataAuditFooter", () => {
  it("states how many declared inputs were actually read", () => {
    renderFooter();
    // The count is the whole point: a manifest that listed only what it had would read
    // as complete while naming a third of the inputs.
    expect(screen.getByText(/INPUTS 1\/3 READ/)).toBeTruthy();
  });

  it("renders an omission as a decision, never as obs null", () => {
    renderFooter();
    const omissions = screen.getByTestId("gold-audit-omissions");
    expect(omissions.textContent).toContain("NOT READ");
    expect(omissions.textContent).not.toContain("null");
  });

  it("gives each omission its reason", () => {
    renderFooter();
    const omissions = screen.getByTestId("gold-audit-omissions");
    expect(omissions.textContent).toContain("no rows in comex");
    expect(omissions.textContent).toContain("fx_rows=[]");
  });

  it("keeps read inputs out of the omission list", () => {
    renderFooter();
    expect(screen.getByTestId("gold-audit-omissions").textContent).not.toContain(
      "DFII10",
    );
  });

  it("labels each input with the lenses that consume it", () => {
    renderFooter();
    expect(screen.getByText(/DFII10 \[L2\]/)).toBeTruthy();
  });

  it("renders no omission list when every input was read", () => {
    renderFooter({ DFII10: INPUTS.DFII10 });
    expect(screen.queryByTestId("gold-audit-omissions")).toBeNull();
  });
});
