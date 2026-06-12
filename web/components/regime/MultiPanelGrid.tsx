"use client";

import {
  finiteDomain,
  linearScale,
  pathFromNullablePoints,
} from "@/lib/svgChart";

const PANEL_W = 210;
const PANEL_H = 96;
const PAD = { top: 6, right: 8, bottom: 8, left: 8 };

export type PanelSpec<Row> = {
  key: string;
  label: string;
  color?: string;
  fmt?: (v: number) => string;
  get: (row: Row) => number | null | undefined;
};

function defaultFmt(v: number): string {
  return Math.abs(v) >= 1000 ? v.toFixed(0) : v.toFixed(2);
}

function MiniSeries({
  label,
  color,
  fmt,
  values,
  dividers,
}: {
  label: string;
  color: string;
  fmt: (v: number) => string;
  values: (number | null)[];
  dividers: number[];
}) {
  const x = linearScale(
    [0, Math.max(values.length - 1, 1)],
    [PAD.left, PANEL_W - PAD.right],
  );
  const domain = finiteDomain(values);
  const y = domain
    ? linearScale([domain.lo, domain.hi], [PANEL_H - PAD.bottom, PAD.top + 14])
    : null;

  // Break the path at each session divider so overnight motion isn't drawn —
  // same rule as GexIntradayChart.pathFor.
  const bounds = [0, ...dividers, values.length];
  const path = y
    ? bounds
        .slice(0, -1)
        .map((start, i) =>
          pathFromNullablePoints(
            values
              .slice(start, bounds[i + 1])
              .map((v, j): [number, number] | null =>
                v == null ? null : [x(start + j), y(v)],
              ),
          ),
        )
        .filter((s) => s.length > 0)
        .join(" ")
    : "";

  const latest = [...values].reverse().find((v) => v != null) ?? null;

  return (
    <div
      style={{
        border: "1px solid var(--border-dim)",
        background: "var(--bg-panel)",
        padding: 4,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          padding: "0 4px",
        }}
      >
        <span
          style={{
            fontSize: 10,
            letterSpacing: "0.15em",
            textTransform: "uppercase",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
          }}
        >
          {label}
        </span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            fontFamily: "var(--font-mono)",
            color: "var(--text-primary)",
          }}
        >
          {latest != null ? fmt(latest) : "—"}
        </span>
      </div>
      <svg
        role="img"
        aria-label={label}
        viewBox={`0 0 ${PANEL_W} ${PANEL_H}`}
        style={{ width: "100%", height: "auto", display: "block" }}
      >
        {dividers.map((d) => (
          <line
            key={d}
            x1={x(d)}
            x2={x(d)}
            y1={PAD.top + 14}
            y2={PANEL_H - PAD.bottom}
            stroke="var(--border-dim)"
            strokeWidth={1}
          />
        ))}
        <path
          d={path}
          fill="none"
          stroke={color}
          strokeWidth={1.3}
          strokeLinecap="round"
        />
      </svg>
    </div>
  );
}

export function MultiPanelGrid<Row>({
  title,
  panels,
  rows,
  dividers,
  testId,
}: {
  title: string;
  panels: PanelSpec<Row>[];
  rows: Row[];
  /** Row indices where a new session starts (empty for daily grids). */
  dividers: number[];
  testId: string;
}) {
  if (!rows.length) {
    return (
      <div className="section" data-testid={`${testId}-empty`}>
        <div className="section-header">
          <div className="section-title">{title}</div>
        </div>
        <div
          className="section-body"
          style={{
            padding: 24,
            textAlign: "center",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
          }}
        >
          No snapshots yet.
        </div>
      </div>
    );
  }
  return (
    <div className="section" data-testid={testId}>
      <div className="section-header">
        <div className="section-title">{title}</div>
      </div>
      <div
        className="section-body"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 8,
          padding: 12,
        }}
      >
        {panels.map((p) => (
          <MiniSeries
            key={p.key}
            label={p.label}
            color={p.color ?? "var(--accent-bg, #05AD98)"}
            fmt={p.fmt ?? defaultFmt}
            values={rows.map((r) => p.get(r) ?? null)}
            dividers={dividers}
          />
        ))}
      </div>
    </div>
  );
}
