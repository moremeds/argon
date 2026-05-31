"use client";

import { useState, type CSSProperties, type ReactNode } from "react";

import type { components } from "@/lib/types";

export type Framework = components["schemas"]["TradeFramework"];

// "na" sentinel — absent values are null or empty string. Render those
// explicitly as "na", never as a blank cell.
function na(value: unknown): string {
  if (value === null || value === undefined) return "na";
  const s = String(value).trim();
  return s === "" ? "na" : s;
}

function verdictColor(v: string): string {
  if (v === "bull") return "var(--positive)";
  if (v === "bear") return "var(--negative)";
  return "var(--text-muted)";
}

const labelStyle: CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono, monospace)",
};

export function Fold({
  title,
  badge,
  defaultOpen = true,
  children,
}: {
  title: string;
  badge?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 6,
        marginBottom: 12,
        background: "var(--bg-panel)",
      }}
    >
      <button
        type="button"
        className="section-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          padding: "10px 14px",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          color: "var(--text-primary)",
        }}
      >
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        <span style={{ ...labelStyle, color: "var(--text-secondary)" }}>
          {title}
        </span>
        {badge ? <span style={{ marginLeft: "auto" }}>{badge}</span> : null}
      </button>
      {open ? (
        <div className="section-body" style={{ padding: "4px 14px 14px" }}>
          {children}
        </div>
      ) : null}
    </section>
  );
}

export function Pill({
  text,
  color = "var(--text-muted)",
}: {
  text: string;
  color?: string;
}) {
  return (
    <span
      style={{
        ...labelStyle,
        color,
        border: `1px solid ${color}`,
        borderRadius: 4,
        padding: "2px 6px",
      }}
    >
      {text}
    </span>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={labelStyle}>{label}</div>
      <div
        style={{
          fontFamily: "var(--font-mono, monospace)",
          fontSize: 18,
          fontWeight: 700,
          color: "var(--text-primary)",
        }}
      >
        {value}
      </div>
    </div>
  );
}

const tileRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))",
  gap: 14,
};

function AxisRow({
  name,
  verdict,
  prose,
  extra,
}: {
  name: string;
  verdict: string;
  prose: string;
  extra?: string;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "110px 90px 1fr",
        gap: 10,
        alignItems: "baseline",
        padding: "6px 0",
        borderBottom: "1px solid var(--border-dim)",
      }}
    >
      <span style={labelStyle}>{name}</span>
      <span
        style={{
          fontFamily: "var(--font-mono, monospace)",
          fontWeight: 700,
          color: verdictColor(verdict),
        }}
      >
        {na(verdict)}
      </span>
      <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>
        {na(prose)}
        {extra ? (
          <span style={{ ...labelStyle, marginLeft: 8 }}>{extra}</span>
        ) : null}
      </span>
    </div>
  );
}

export function ThreeAxisSection({ fw }: { fw: Framework }) {
  const { direction, vega, asymmetry } = fw.three_axis;
  return (
    <Fold title="3-Axis Read">
      <AxisRow
        name="Direction"
        verdict={direction.verdict}
        prose={direction.prose}
      />
      <AxisRow
        name="Vega"
        verdict={vega.regime}
        prose={vega.prose}
        extra={vega.ivr != null ? `IVR ${na(vega.ivr)}` : undefined}
      />
      <AxisRow
        name="Asymmetry"
        verdict={asymmetry.structure_family}
        prose={asymmetry.prose}
        extra={asymmetry.rule_on ? "rule ✓" : "rule ✗"}
      />
    </Fold>
  );
}

export function GammaSection({ fw }: { fw: Framework }) {
  const g = fw.gamma;
  return (
    <Fold title="Gamma Map" badge={<Pill text={`${na(g.regime)} gamma`} />}>
      <div style={tileRow}>
        <Tile label="Flip strike" value={na(g.flip_strike)} />
        <Tile label="Call wall" value={na(g.call_wall)} />
        <Tile label="Put wall" value={na(g.put_wall)} />
      </div>
      {g.prose ? (
        <p style={{ color: "var(--text-secondary)", marginTop: 10 }}>
          {g.prose}
        </p>
      ) : null}
    </Fold>
  );
}

// Per v2 spec §5.6 MUST-1: no_conflict MUST render visibly differently
// from stand_aside. Map each enum value to a friendly label + tone color
// so a user glancing at the page can distinguish "no event risk" from
// "earnings forces stand aside" without parsing the raw enum string.
const CATALYST_LABEL: Record<string, string> = {
  no_conflict: "no event risk",
  exit_before_print: "exit before print",
  stand_aside: "stand aside",
  hold_through_leaps: "hold through (leaps)",
};

function catalystColor(handling: string): string {
  if (handling === "no_conflict") return "var(--text-muted)";
  if (handling === "stand_aside") return "var(--warning)";
  return "var(--text-secondary)";
}

export function CatalystSection({ fw }: { fw: Framework }) {
  const c = fw.catalyst;
  const handling = c.handling ?? "";
  const label = CATALYST_LABEL[handling] ?? na(handling);
  const color = catalystColor(handling);
  return (
    <Fold title="Catalyst" badge={<Pill text={label} color={color} />}>
      <div style={tileRow}>
        <Tile label="Next ER" value={na(c.next_er_date)} />
        <Tile label="DTE to ER" value={na(c.dte_to_er)} />
        <Tile label="Implied move" value={na(c.implied_move)} />
      </div>
      {c.prose ? (
        <p style={{ color: "var(--text-secondary)", marginTop: 8 }}>
          {c.prose}
        </p>
      ) : null}
    </Fold>
  );
}

// Per v2 spec §5.6 MUST-2: items in missing_data[] starting with
// "auto-correct:" MUST be surfaced separately from the rest of
// missing_data AND associated with the corrected field. Until a typed
// `corrections[]` array lands (Open Question #1), the frontend parses
// the prose prefix.
const AUTO_CORRECT_PREFIX = "auto-correct:";

export function isAutoCorrectNote(note: string): boolean {
  return note.trim().startsWith(AUTO_CORRECT_PREFIX);
}

export function entryStateAutoCorrectNote(
  missingData: readonly string[] | null | undefined,
): string | null {
  for (const note of missingData ?? []) {
    const trimmed = note.trim();
    if (
      trimmed.startsWith(AUTO_CORRECT_PREFIX) &&
      trimmed.includes("headline.entry_state")
    ) {
      return trimmed.slice(AUTO_CORRECT_PREFIX.length).trim();
    }
  }
  return null;
}

const ENTRY_STATE_COLOR: Record<string, string> = {
  ACTIVE: "var(--positive)",
  CONDITIONAL: "var(--warning)",
  NO_ENTRY: "var(--text-muted)",
};

export function EntryStateStrip({
  entryState,
  autoCorrectNote,
}: {
  entryState: string | null | undefined;
  autoCorrectNote: string | null;
}) {
  const state = entryState ?? "";
  const color = ENTRY_STATE_COLOR[state] ?? "var(--text-muted)";
  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        flexWrap: "wrap",
        marginBottom: 12,
        padding: "8px 10px",
        border: `1px solid ${
          autoCorrectNote ? "var(--warning)" : "var(--border-dim)"
        }`,
        borderRadius: 4,
        background: "var(--bg-panel)",
      }}
    >
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <span style={labelStyle}>Entry state</span>
        <Pill text={na(state)} color={color} />
      </div>
      {autoCorrectNote ? (
        <div
          style={{
            display: "flex",
            gap: 6,
            alignItems: "flex-start",
            color: "var(--warning)",
            fontSize: 12,
            lineHeight: 1.35,
            flex: "1 1 320px",
          }}
          data-testid="entry-state-autocorrect"
        >
          <span style={{ ...labelStyle, color: "var(--warning)" }}>
            State corrected
          </span>
          <span>{autoCorrectNote}</span>
        </div>
      ) : null}
    </div>
  );
}

function factorColor(status: string): string {
  if (status === "yes") return "var(--positive)";
  if (status === "no") return "var(--negative)";
  return "var(--text-muted)";
}

function ConvictionDots({ score, max }: { score: number; max: number }) {
  const safeMax = max > 0 ? max : 8;
  const filled = Math.max(0, Math.min(safeMax, score));
  return (
    <span
      style={{ fontFamily: "var(--font-mono, monospace)", letterSpacing: 2 }}
    >
      {"●".repeat(filled)}
      {"○".repeat(Math.max(0, safeMax - filled))}{" "}
      <span style={{ color: "var(--text-secondary)" }}>
        {score}/{safeMax}
      </span>
    </span>
  );
}

export function ConvictionSection({ fw }: { fw: Framework }) {
  // The 8 canonical factors are a fixed-length list (min/max 8 in the contract).
  return (
    <Fold
      title="Conviction"
      badge={<ConvictionDots score={fw.conviction.score} max={8} />}
    >
      {(fw.conviction.factors ?? []).length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>na</p>
      ) : (
        (fw.conviction.factors ?? []).map((f, i) => (
          <div
            key={`${f.name}-${i}`}
            style={{
              display: "grid",
              gridTemplateColumns: "200px 50px 1fr",
              gap: 10,
              padding: "5px 0",
              borderBottom: "1px solid var(--border-dim)",
            }}
            title={na(f.note)}
          >
            <span style={{ color: "var(--text-secondary)", fontSize: 13 }}>
              {f.name}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono, monospace)",
                color: factorColor(f.status),
              }}
            >
              {na(f.status)}
            </span>
            <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
              {na(f.note)}
            </span>
          </div>
        ))
      )}
      {fw.conviction.prose ? (
        <p style={{ color: "var(--text-secondary)", marginTop: 8 }}>
          {fw.conviction.prose}
        </p>
      ) : null}
    </Fold>
  );
}

export function ConfluenceSection({ fw }: { fw: Framework }) {
  const c = fw.confluence;
  return (
    <Fold
      title="Confluence"
      badge={
        <Pill
          text={c.aligned ? "aligned" : "mixed"}
          color={c.aligned ? "var(--positive)" : "var(--warning)"}
        />
      }
    >
      {(c.signals ?? []).length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>na</p>
      ) : (
        (c.signals ?? []).map((s, i) => (
          <span
            key={`${s.name}-${i}`}
            style={{
              marginRight: 10,
              color: "var(--text-secondary)",
              fontSize: 13,
            }}
          >
            {s.name}:{" "}
            <strong style={{ color: verdictColor(s.direction) }}>
              {na(s.direction)}
            </strong>
          </span>
        ))
      )}
      {c.prose ? (
        <p style={{ color: "var(--text-secondary)", marginTop: 8 }}>
          {c.prose}
        </p>
      ) : null}
    </Fold>
  );
}

export function PitfallsSection({ fw }: { fw: Framework }) {
  const pitfalls = fw.pitfalls ?? [];
  const triggered = pitfalls.filter((p) => p.triggered);
  return (
    <Fold
      title="Pitfalls"
      badge={
        <Pill
          text={`${triggered.length} triggered`}
          color={triggered.length ? "var(--warning)" : "var(--text-muted)"}
        />
      }
      defaultOpen={triggered.length > 0}
    >
      {pitfalls.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>None evaluated.</p>
      ) : (
        pitfalls.map((p, i) => (
          <div
            key={`${p.id}-${i}`}
            style={{
              padding: "5px 0",
              borderBottom: "1px solid var(--border-dim)",
              opacity: p.triggered ? 1 : 0.55,
            }}
          >
            <span
              style={{
                color: p.triggered ? "var(--warning)" : "var(--text-muted)",
                marginRight: 8,
              }}
            >
              {p.triggered ? "●" : "○"}
            </span>
            <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>
              {na(p.title)}
            </span>
            {p.note ? (
              <span style={{ color: "var(--text-muted)", marginLeft: 8 }}>
                — {p.note}
              </span>
            ) : null}
          </div>
        ))
      )}
    </Fold>
  );
}

export function CandidatesSection({ fw }: { fw: Framework }) {
  const candidates = fw.candidates ?? [];
  return (
    <Fold title="Candidate Ladder" defaultOpen={false}>
      {candidates.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>na</p>
      ) : (
        candidates.map((c, i) => (
          <div
            key={`${c.name}-${i}`}
            style={{
              padding: "6px 0",
              borderBottom: "1px solid var(--border-dim)",
            }}
          >
            <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>
              {na(c.name)}
            </span>
            {!c.defined_risk ? (
              <span style={{ color: "var(--negative)", marginLeft: 8 }}>
                ⚠ undefined risk
              </span>
            ) : null}
            {(c.legs ?? []).length ? (
              <div
                style={{
                  color: "var(--text-secondary)",
                  fontSize: 13,
                  fontFamily: "var(--font-mono, monospace)",
                }}
              >
                {(c.legs ?? []).join(" / ")}
              </div>
            ) : null}
            <div style={{ ...labelStyle, marginTop: 2 }}>
              bull {na(c.pnl_bull)} · base {na(c.pnl_base)} · bear{" "}
              {na(c.pnl_bear)}
            </div>
          </div>
        ))
      )}
    </Fold>
  );
}

export function BestSetupSection({ fw }: { fw: Framework }) {
  const b = fw.best_setup;
  const legs = b.legs ?? [];
  const standAside = b.structure === "stand_aside";
  return (
    <section
      style={{
        border: `2px solid ${
          standAside ? "var(--warning)" : "var(--accent-vivid, var(--positive))"
        }`,
        borderRadius: 6,
        padding: 16,
        marginBottom: 12,
        background: "var(--bg-panel)",
      }}
    >
      <div
        style={{
          ...labelStyle,
          color: standAside
            ? "var(--warning)"
            : "var(--accent-vivid, var(--positive))",
        }}
      >
        Best Setup
      </div>
      <h3
        style={{
          margin: "6px 0",
          color: "var(--text-primary)",
          fontFamily: "var(--font-mono, monospace)",
        }}
      >
        {na(b.structure)}
      </h3>
      {legs.length > 0 ? (
        <ul style={{ margin: "6px 0", paddingLeft: 18 }}>
          {legs.map((leg, i) => (
            <li
              key={i}
              style={{
                color: "var(--text-secondary)",
                fontFamily: "var(--font-mono, monospace)",
                fontSize: 13,
              }}
            >
              {leg}
            </li>
          ))}
        </ul>
      ) : null}
      <div style={{ ...tileRow, marginTop: 8 }}>
        <Tile label="Cost" value={na(b.cost)} />
        <Tile label="Max risk" value={na(b.max_risk)} />
      </div>
      {b.rationale ? (
        <p style={{ color: "var(--text-secondary)", marginTop: 8 }}>
          {b.rationale}
        </p>
      ) : null}
      {b.invalidation ? (
        <p style={{ color: "var(--text-muted)", marginTop: 6 }}>
          <span style={labelStyle}>Invalidation</span> {b.invalidation}
        </p>
      ) : null}
      {b.why_not_alternatives ? (
        <p style={{ color: "var(--text-muted)", marginTop: 6, fontSize: 12 }}>
          Why not alternatives: {b.why_not_alternatives}
        </p>
      ) : null}
    </section>
  );
}

export function WhatChangesSection({ fw }: { fw: Framework }) {
  const whatChanges = fw.what_changes ?? [];
  if (whatChanges.length === 0 && !fw.bottom_line) return null;
  return (
    <Fold title="What Changes the View / Bottom Line">
      {whatChanges.map((w, i) => (
        <div
          key={i}
          style={{ color: "var(--text-secondary)", padding: "3px 0" }}
        >
          <strong style={{ color: "var(--text-primary)" }}>
            {na(w.signal)}
          </strong>{" "}
          → {na(w.effect)}
        </div>
      ))}
      {fw.bottom_line ? (
        <p
          style={{
            color: "var(--text-primary)",
            fontWeight: 600,
            marginTop: 8,
          }}
        >
          {fw.bottom_line}
        </p>
      ) : null}
    </Fold>
  );
}
