"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { components } from "@/lib/types";
import { FlowSnapshotGrid } from "../panels/FlowSnapshotGrid";
import { FlowAlertSummary } from "../panels/FlowAlertSummary";
import { FlowTimelinePanel } from "../panels/FlowTimelinePanel";
import { OiMoversTable } from "../panels/OiMoversTable";
import { StrikeProfilePanel } from "../panels/StrikeProfilePanel";
import { TopAlertsTable } from "../panels/TopAlertsTable";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];
type OptionsDailyRow = components["schemas"]["OptionsDailyRow"];
type ChainRow = components["schemas"]["OptionChainPerStrikeRow"];

const SECTION_HEADING: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  margin: "8px 0",
};

export function FlowTab({ report }: { report: Report }) {
  // Derive spot from the report itself — keeps FlowTab's signature single-prop
  // (matches MarketStructureTab/VolatilityTab) so the dispatcher needs no
  // changes when wiring this tab.
  const spot = toNum(report.market_structure?.spot) ?? 0;
  const chain = useMemo<ChainRow[]>(
    () => report.option_chain_per_strike ?? [],
    [report.option_chain_per_strike],
  );

  // Cross-reference indexes for the two tables. Alerts key by `option_chain`
  // (OCC), OI movers key by `option_symbol` (OCC) — same alphabet.
  const alerts = useMemo(
    () => report.flow.top_alerts ?? [],
    [report.flow.top_alerts],
  );
  const oiMovers = useMemo(
    () => report.oi_change_top ?? [],
    [report.oi_change_top],
  );
  const alertCountBySymbol = useMemo(() => {
    const m = new Map<string, number>();
    for (const a of alerts) {
      if (!a.option_chain) continue;
      m.set(a.option_chain, (m.get(a.option_chain) ?? 0) + 1);
    }
    return m;
  }, [alerts]);
  const oiDiffBySymbol = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of oiMovers) {
      if (!r.option_symbol || r.oi_diff_plain == null) continue;
      m.set(r.option_symbol, r.oi_diff_plain);
    }
    return m;
  }, [oiMovers]);

  // Stored chain rows are already filtered to dte ≥ 0 in
  // aggregate_chain_per_strike, so every expiry here is today-or-future.
  // Computing "today" in the client was the source of an SSR/CSR hydration
  // mismatch (Date()-based render-time state) — drop it.
  const expiries = useMemo(
    () => Array.from(new Set(chain.map((r) => r.expiry))).sort(),
    [chain],
  );
  const [selectedExpiries, setSelectedExpiries] = useState<string[]>(() =>
    expiries.slice(0, 4),
  );
  const [strikeRangePct, setStrikeRangePct] = useState<number>(0.3);

  return (
    <div
      style={{ display: "flex", flexDirection: "column", gap: 24, padding: 16 }}
    >
      <FlowSnapshotGrid
        flow={report.flow}
        darkPool={{
          prints: report.dark_pool_print_count,
          notional: report.dark_pool_notional,
        }}
        shortData={report.short_data ?? null}
      />

      <TimelineSection
        timeline={report.options_timeline ?? []}
        nextEarnings={report.next_earnings_date ?? null}
      />

      {chain.length > 0 ? (
        <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <ProfileControls
            expiries={expiries}
            selectedExpiries={selectedExpiries}
            onSetExpiries={setSelectedExpiries}
            strikeRangePct={strikeRangePct}
            onStrikeRangeChange={setStrikeRangePct}
          />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 16,
            }}
          >
            <StrikeProfilePanel
              title="VOLUME BY STRIKE"
              metric="volume"
              rows={chain}
              selectedExpiries={selectedExpiries}
              strikeRangePct={strikeRangePct}
              spot={spot}
            />
            <StrikeProfilePanel
              title="OI BY STRIKE"
              metric="oi"
              rows={chain}
              selectedExpiries={selectedExpiries}
              strikeRangePct={strikeRangePct}
              spot={spot}
            />
          </div>
        </section>
      ) : (
        <div
          style={{
            fontFamily: "var(--font-mono)",
            color: "var(--text-muted)",
          }}
        >
          NO CHAIN DATA
        </div>
      )}

      <section>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            gap: 16,
            margin: "8px 0",
          }}
        >
          <h3 style={{ ...SECTION_HEADING, margin: 0 }}>Top Alerts</h3>
          <FlowAlertSummary flow={report.flow} />
        </div>
        <TopAlertsTable alerts={alerts} oiMoverIndex={oiDiffBySymbol} />
      </section>

      <section>
        <h3 style={SECTION_HEADING}>OI Change — Top Movers</h3>
        <OiMoversTable
          rows={oiMovers}
          spot={spot}
          alertIndex={alertCountBySymbol}
        />
      </section>
    </div>
  );
}

// Close the <details> popover when the user clicks anywhere outside it.
// Native <details> only toggles via summary clicks; this adds the
// conventional dropdown-style outside-click dismissal.
function useCloseOnOutsideClick(
  ref: React.RefObject<HTMLDetailsElement | null>,
) {
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const el = ref.current;
      if (el?.open && !el.contains(e.target as Node)) {
        el.open = false;
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [ref]);
}

const CONTROL_LABEL: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: 1.5,
  color: "var(--text-muted)",
};

// Shared trigger style so the expiry multi-select and the strike-range
// <select> read as the same control family.
const CONTROL_TRIGGER: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  background: "var(--bg-panel)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-dim)",
  padding: "2px 8px",
};

function ProfileControls({
  expiries,
  selectedExpiries,
  onSetExpiries,
  strikeRangePct,
  onStrikeRangeChange,
}: {
  expiries: string[];
  selectedExpiries: string[];
  onSetExpiries: (next: string[]) => void;
  strikeRangePct: number;
  onStrikeRangeChange: (v: number) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 12,
        flexWrap: "wrap",
        alignItems: "center",
      }}
    >
      <span style={CONTROL_LABEL}>EXPIRIES:</span>
      <ExpiryMultiSelect
        expiries={expiries}
        selected={selectedExpiries}
        onChange={onSetExpiries}
      />
      <span style={{ ...CONTROL_LABEL, marginLeft: 16 }}>STRIKE RANGE:</span>
      <StrikeRangeSelect
        value={strikeRangePct}
        onChange={onStrikeRangeChange}
      />
    </div>
  );
}

const STRIKE_RANGE_OPTIONS: { value: number; label: string }[] = [
  { value: 0.15, label: "±15%" },
  { value: 0.3, label: "±30%" },
  { value: 0.6, label: "±60%" },
  { value: 9.99, label: "All" },
];

// Single-select sibling of ExpiryMultiSelect. Native <select> picks up
// macOS chrome (white pill, blue selection) that fights the Argon dark
// theme, so we replace it with the same <details> pattern.
function StrikeRangeSelect({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  const current =
    STRIKE_RANGE_OPTIONS.find((o) => o.value === value)?.label ?? "—";
  const ref = useRef<HTMLDetailsElement>(null);
  useCloseOnOutsideClick(ref);
  return (
    <details ref={ref} style={{ position: "relative" }}>
      <summary
        style={{
          ...CONTROL_TRIGGER,
          listStyle: "none",
          cursor: "pointer",
          minWidth: 80,
          display: "inline-flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span>{current}</span>
        <span style={{ color: "var(--text-muted)" }}>▾</span>
      </summary>
      <div
        style={{
          position: "absolute",
          zIndex: 20,
          marginTop: 4,
          minWidth: 100,
          background: "var(--bg-panel)",
          border: "1px solid var(--border-dim)",
          padding: 4,
        }}
      >
        {STRIKE_RANGE_OPTIONS.map((o) => {
          const active = o.value === value;
          return (
            <button
              key={o.value}
              type="button"
              onClick={(e) => {
                onChange(o.value);
                // Close the <details> after selection.
                (
                  e.currentTarget.closest("details") as HTMLDetailsElement
                ).open = false;
              }}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "4px 8px",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                background: active ? "var(--accent-bg)" : "transparent",
                color: active ? "var(--bg-panel)" : "var(--text-primary)",
                border: "none",
                cursor: "pointer",
              }}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </details>
  );
}

// Multi-select built on a native <details> popover. Avoids click-outside
// state management and Portal mounting — the same <details> pattern that
// powers the (i) tooltips elsewhere in this tab. Trigger is styled to
// match the strike-range <select> so the two read as one control family.
function ExpiryMultiSelect({
  expiries,
  selected,
  onChange,
}: {
  expiries: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const selectedSet = new Set(selected);
  const summary =
    selected.length === 0
      ? "None"
      : selected.length === expiries.length
        ? "All"
        : selected.length === 1
          ? selected[0]
          : `${selected.length} selected`;

  const toggle = (e: string) =>
    onChange(
      selectedSet.has(e) ? selected.filter((x) => x !== e) : [...selected, e],
    );

  const ref = useRef<HTMLDetailsElement>(null);
  useCloseOnOutsideClick(ref);

  return (
    <details ref={ref} style={{ position: "relative" }}>
      <summary
        style={{
          ...CONTROL_TRIGGER,
          listStyle: "none",
          cursor: "pointer",
          minWidth: 140,
          display: "inline-flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span>{summary}</span>
        <span style={{ color: "var(--text-muted)" }}>▾</span>
      </summary>
      <div
        style={{
          position: "absolute",
          zIndex: 20,
          marginTop: 4,
          minWidth: 200,
          maxHeight: 320,
          overflowY: "auto",
          background: "var(--bg-panel)",
          border: "1px solid var(--border-dim)",
          padding: 6,
        }}
      >
        <div
          style={{
            display: "flex",
            gap: 6,
            padding: "2px 4px 6px",
            borderBottom: "1px solid var(--border-dim)",
            marginBottom: 4,
          }}
        >
          <button
            type="button"
            onClick={() => onChange([...expiries])}
            style={{ ...CONTROL_TRIGGER, fontSize: 10, padding: "1px 6px" }}
          >
            ALL
          </button>
          <button
            type="button"
            onClick={() => onChange([])}
            style={{ ...CONTROL_TRIGGER, fontSize: 10, padding: "1px 6px" }}
          >
            CLEAR
          </button>
        </div>
        {expiries.map((e) => (
          <label
            key={e}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "3px 4px",
              cursor: "pointer",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--text-primary)",
            }}
          >
            <input
              type="checkbox"
              checked={selectedSet.has(e)}
              onChange={() => toggle(e)}
            />
            {e}
          </label>
        ))}
      </div>
    </details>
  );
}

function TimelineSection({
  timeline,
  nextEarnings,
}: {
  timeline: OptionsDailyRow[];
  nextEarnings: string | null;
}) {
  if (timeline.length === 0) {
    return (
      <div
        style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}
      >
        NO TIMELINE DATA
      </div>
    );
  }

  const dates = timeline.map((r) => r.date);
  const totalVol = timeline.map((r) =>
    r.call_volume == null || r.put_volume == null
      ? null
      : r.call_volume + r.put_volume,
  );
  // P/C ratio: only the DENOMINATOR (call_volume) must be non-zero. A real
  // put_volume of 0 should chart as 0, not get filtered out as missing.
  const pcVol = timeline.map((r) =>
    r.call_volume != null && r.call_volume !== 0 && r.put_volume != null
      ? r.put_volume / r.call_volume
      : null,
  );
  const totalOi = timeline.map((r) =>
    r.call_open_interest == null || r.put_open_interest == null
      ? null
      : r.call_open_interest + r.put_open_interest,
  );
  const pcOi = timeline.map((r) =>
    r.call_open_interest != null &&
    r.call_open_interest !== 0 &&
    r.put_open_interest != null
      ? r.put_open_interest / r.call_open_interest
      : null,
  );
  const earnings = nextEarnings ? [nextEarnings] : [];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <FlowTimelinePanel
        title="OPTIONS VOLUME"
        primary={{
          label: "Volume",
          values: totalVol,
          color: "var(--accent-bg)",
        }}
        secondary={{
          label: "P/C Vol",
          values: pcVol,
          color: "var(--accent-warm)",
        }}
        dates={dates}
        markers={earnings}
      />
      <FlowTimelinePanel
        title="OPEN INTEREST"
        primary={{ label: "OI", values: totalOi, color: "var(--accent-bg)" }}
        secondary={{
          label: "P/C OI",
          values: pcOi,
          color: "var(--accent-warm)",
        }}
        dates={dates}
      />
    </div>
  );
}
