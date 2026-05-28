"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";

import type { components } from "@/lib/types";
import { regimeApi } from "@/lib/regime/api";

import { VcgStressHistoryTable } from "./VcgStressHistoryTable";

type VcgValidationResponse = components["schemas"]["VcgValidationResponse"];

/**
 * Self-fetching section that pulls /api/regime/vcg-validation and renders
 * the stress_history table. Kept separate from VcgSubTabView so that view
 * stays pure (props-only) and testable without HTTP mocking — only this
 * section owns the fetch.
 *
 * The section header is a toggle: click to collapse / expand. Defaults open.
 * The fetch still fires on mount regardless of fold state — the cost is a
 * one-time GET, and pre-fetching keeps the count visible in the header.
 */
export default function VcgStressHistorySection() {
  const [data, setData] = useState<VcgValidationResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch(regimeApi.vcgValidation())
      .then(async (r) => {
        if (r.ok) return r.json();
        const body = await r.json().catch(() => null);
        const detail =
          body && typeof body.detail === "string"
            ? body.detail
            : `HTTP ${r.status}`;
        throw new Error(detail);
      })
      .then((d: VcgValidationResponse) => {
        if (cancelled) return;
        setData(d);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = data?.stress_history ?? [];
  const totalDays = data?.n_days ?? null;

  return (
    <div className="section" data-testid="vcg-stress-history-section">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid="vcg-stress-history-toggle"
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
          PANIC / RISK-OFF / EDR History (all-time)
          {totalDays != null && (
            <span
              style={{
                marginLeft: "8px",
                fontFamily: "var(--font-mono)",
                fontSize: "10px",
                color: "var(--text-muted)",
              }}
            >
              {rows.length} stress days · {totalDays} total
            </span>
          )}
        </div>
      </button>
      {open && err && (
        <div data-testid="vcg-stress-history-error">
          Stress history unavailable: {err}
        </div>
      )}
      {open && !err && !data && <div>Loading…</div>}
      {open && !err && data && (
        <div className="section-body table-wrap">
          <VcgStressHistoryTable rows={rows} />
        </div>
      )}
    </div>
  );
}
