"use client";

import { fmtDecimal } from "@/lib/formatters";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";
import {
  type CriHistoryEntry,
  type CriResponse,
  useCri,
} from "@/lib/regime/useCri";

const LEVEL_COLOR: Record<"LOW" | "ELEVATED" | "HIGH" | "CRITICAL", string> = {
  LOW: "var(--positive)",
  ELEVATED: "var(--accent-warm)",
  HIGH: "var(--warning)",
  CRITICAL: "var(--negative)",
};

const COMPONENT_LABELS: Record<keyof CriComponentsShape, string> = {
  vix: "VIX",
  vvix: "VVIX",
  correlation: "COR1M",
  momentum: "SPX MOM",
};

type CriComponentsShape = {
  vix: number;
  vvix: number;
  correlation: number;
  momentum: number;
};

function componentColor(score: number): string {
  if (score < 12.5) return "var(--positive)";
  if (score < 20) return "var(--accent-warm)";
  return "var(--negative)";
}

function Tile({
  label,
  children,
  hint,
}: {
  label: string;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div
      title={hint}
      style={{
        padding: "12px 14px",
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: "0.15em",
          color: "var(--text-muted)",
          textTransform: "uppercase",
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

function CompositeScore({ cri }: { cri: CriResponse["cri"] }) {
  const score = cri?.score ?? 0;
  const level = cri?.level ?? "LOW";
  return (
    <Tile label="Crash Risk Indicator">
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <div
          style={{
            fontSize: 38,
            fontWeight: 700,
            fontFamily: "var(--font-mono)",
            color: LEVEL_COLOR[level],
            lineHeight: 1,
          }}
          data-testid="cri-score"
        >
          {fmtDecimal(score, 1)}
        </div>
        <div
          style={{
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: "0.08em",
            color: LEVEL_COLOR[level],
            textTransform: "uppercase",
          }}
          data-testid="cri-level"
        >
          {level}
        </div>
        <div
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            marginLeft: "auto",
          }}
        >
          / 100
        </div>
      </div>
    </Tile>
  );
}

function ComponentBar({ name, score }: { name: string; score: number }) {
  const pct = Math.min(100, Math.max(0, (score / 25) * 100));
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "70px 1fr 44px",
        alignItems: "center",
        gap: 8,
        marginBottom: 6,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: "0.12em",
          color: "var(--text-muted)",
          textTransform: "uppercase",
        }}
      >
        {name}
      </div>
      <div
        style={{
          position: "relative",
          height: 8,
          background: "var(--border-dim)",
          borderRadius: 2,
        }}
      >
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: `${pct}%`,
            height: "100%",
            background: componentColor(score),
            borderRadius: 2,
          }}
        />
      </div>
      <div
        style={{
          fontSize: 11,
          fontFamily: "var(--font-mono)",
          color: "var(--text-primary)",
          textAlign: "right",
        }}
      >
        {fmtDecimal(score, 1)}
      </div>
    </div>
  );
}

function ComponentBreakdown({
  components,
}: {
  components: CriComponentsShape;
}) {
  return (
    <Tile label="Component Scores (each 0-25)">
      <div style={{ marginTop: 4 }}>
        {(Object.keys(COMPONENT_LABELS) as Array<keyof CriComponentsShape>).map(
          (key) => (
            <ComponentBar
              key={key}
              name={COMPONENT_LABELS[key]}
              score={components[key] ?? 0}
            />
          ),
        )}
      </div>
    </Tile>
  );
}

function CrashTriggerCard({
  trigger,
}: {
  trigger: CriResponse["crash_trigger"];
}) {
  const fired = trigger?.fired ?? false;
  const c = trigger?.conditions;
  return (
    <Tile label="Crash Trigger">
      <div
        style={{
          fontSize: 16,
          fontWeight: 600,
          fontFamily: "var(--font-mono)",
          color: fired ? "var(--negative)" : "var(--positive)",
          marginBottom: 8,
        }}
        data-testid="crash-trigger-state"
      >
        {fired ? "FIRED" : "SILENT"}
      </div>
      <div
        style={{
          fontSize: 11,
          color: "var(--text-secondary)",
          lineHeight: 1.7,
        }}
      >
        <ConditionRow
          label="SPX < 100d MA"
          on={c?.spx_below_100d_ma ?? false}
        />
        <ConditionRow
          label="Realized vol > 25%"
          on={c?.realized_vol_gt_25 ?? false}
        />
        <ConditionRow label="COR1M > 60" on={c?.cor1m_gt_60 ?? false} />
      </div>
    </Tile>
  );
}

function ConditionRow({ label, on }: { label: string; on: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between" }}>
      <span>{label}</span>
      <span
        style={{
          color: on ? "var(--negative)" : "var(--text-muted)",
          fontFamily: "var(--font-mono)",
        }}
      >
        {on ? "ON" : "off"}
      </span>
    </div>
  );
}

function CtaCard({ cta }: { cta: CriResponse["cta"] }) {
  const exposure = cta?.exposure_pct ?? null;
  const reduction = cta?.forced_reduction_pct ?? null;
  const selling = cta?.est_selling_bn ?? null;
  return (
    <Tile
      label="CTA Vol-Target Model"
      hint="vol_target=10% · max_exposure=200% · AUM=$350B"
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 10,
        }}
      >
        <Stat
          label="Exposure"
          value={exposure != null ? `${fmtDecimal(exposure, 0)}%` : "—"}
          color={
            exposure != null && exposure < 60
              ? "var(--warning)"
              : "var(--text-primary)"
          }
        />
        <Stat
          label="Forced Cut"
          value={reduction != null ? `${fmtDecimal(reduction, 0)}%` : "—"}
          color={
            reduction != null && reduction > 0
              ? "var(--negative)"
              : "var(--positive)"
          }
        />
        <Stat
          label="Est. Selling"
          value={selling != null ? `$${fmtDecimal(selling, 1)}B` : "—"}
          color={
            selling != null && selling > 0
              ? "var(--negative)"
              : "var(--text-primary)"
          }
        />
      </div>
    </Tile>
  );
}

function Stat({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          color: "var(--text-muted)",
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 16,
          fontWeight: 600,
          fontFamily: "var(--font-mono)",
          color,
        }}
      >
        {value}
      </div>
    </div>
  );
}

const CHART_W = 760;
const CHART_H = 160;
const PAD = { top: 12, right: 56, bottom: 22, left: 56 };

function MiniHistoryChart({ history }: { history: CriHistoryEntry[] }) {
  if (!history.length) return null;

  const xScale = linearScale(
    [0, Math.max(history.length - 1, 1)],
    [PAD.left, CHART_W - PAD.right],
  );
  const vixD = finiteDomain(history.map((h) => h.vix));
  const corD = finiteDomain(history.map((h) => h.cor1m));
  const yVix = vixD
    ? linearScale([vixD.lo, vixD.hi], [CHART_H - PAD.bottom, PAD.top])
    : null;
  const yCor = corD
    ? linearScale([corD.lo, corD.hi], [CHART_H - PAD.bottom, PAD.top])
    : null;

  const pathFor = (
    pick: (h: CriHistoryEntry) => number | null | undefined,
    y: ((v: number) => number) | null,
  ) =>
    y == null
      ? ""
      : pathFromPoints(
          history
            .map((h, i): [number, number] | null => {
              const v = pick(h);
              return v == null ? null : [xScale(i), y(v)];
            })
            .filter((p): p is [number, number] => p != null),
        );

  return (
    <div style={{ marginTop: 12 }}>
      <div
        style={{
          fontSize: 10,
          letterSpacing: "0.15em",
          color: "var(--text-muted)",
          textTransform: "uppercase",
          marginBottom: 4,
        }}
      >
        20-day history · VIX (orange) · COR1M (blue)
      </div>
      <svg
        role="img"
        aria-label="CRI 20-day mini history"
        viewBox={`0 0 ${CHART_W} ${CHART_H}`}
        style={{ width: "100%", height: CHART_H, display: "block" }}
        data-testid="cri-mini-history"
      >
        <title>CRI inputs — VIX and COR1M trailing 20 sessions</title>
        <path
          d={pathFor((h) => h.vix, yVix)}
          fill="none"
          stroke="var(--accent-warm)"
          strokeWidth={1.4}
        />
        <path
          d={pathFor((h) => h.cor1m, yCor)}
          fill="none"
          stroke="var(--accent-bg)"
          strokeWidth={1.4}
        />
      </svg>
    </div>
  );
}

export function CriSubTabView({ data }: { data: CriResponse | null }) {
  if (!data || data.status === "empty") {
    return (
      <div
        data-testid="cri-empty-state"
        style={{
          padding: 32,
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
        }}
      >
        No CRI snapshot yet — trigger a scan via POST /api/regime/scan.
      </div>
    );
  }
  const cri = data.cri ?? {
    score: 0,
    level: "LOW" as const,
    components: undefined,
  };
  const components: CriComponentsShape = {
    vix: cri.components?.vix ?? 0,
    vvix: cri.components?.vvix ?? 0,
    correlation: cri.components?.correlation ?? 0,
    momentum: cri.components?.momentum ?? 0,
  };

  return (
    <div data-testid="cri-subtab">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
        }}
      >
        <CompositeScore cri={cri} />
        <ComponentBreakdown components={components} />
        <CrashTriggerCard trigger={data.crash_trigger} />
        <CtaCard cta={data.cta} />
      </div>
      <MiniHistoryChart history={data.history ?? []} />
    </div>
  );
}

export default function CriSubTab() {
  const { data } = useCri();
  return <CriSubTabView data={data} />;
}
