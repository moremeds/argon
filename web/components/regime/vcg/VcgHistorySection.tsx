"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState, type ComponentProps } from "react";

import { VcgHistoryTable } from "./VcgHistoryTable";

/* ─── 20d history table, folded by default (same toggle pattern as
 * VcgStressHistorySection). ─────────────────────────────────── */

export function VcgHistorySection(
  props: ComponentProps<typeof VcgHistoryTable>,
) {
  const [open, setOpen] = useState(false);
  return (
    <div className="section" data-testid="vcg-history-section">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid="vcg-history-toggle"
        className="section-header"
        style={{
          width: "100%",
          background: "transparent",
          border: "none",
          padding: 0,
          cursor: "pointer",
          textAlign: "left",
          color: "inherit",
        }}
      >
        <div
          className="section-title"
          style={{ display: "flex", alignItems: "center", gap: "6px" }}
        >
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          VCG History (20d)
        </div>
      </button>
      {open && (
        <div className="section-body table-wrap">
          <VcgHistoryTable {...props} />
        </div>
      )}
    </div>
  );
}
