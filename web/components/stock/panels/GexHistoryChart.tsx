"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api";
import type { RegimeGexResponse } from "@/lib/api";

const PANEL: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 16,
  fontFamily: "var(--font-mono)",
};

const HEADING: React.CSSProperties = {
  fontSize: 12,
  color: "var(--text-secondary)",
};

type Bar = { date: string; net_gex: number | null; spot: number | null };

function buildBars(resp: RegimeGexResponse | null): Bar[] {
  const hist = resp?.history ?? [];
  return hist.map((h) => ({
    date: h.date,
    net_gex: h.net_gex ?? null,
    spot: h.spot ?? null,
  }));
}

function fmtTick(v: number): string {
  const abs = Math.abs(v);
  const sign = v >= 0 ? "" : "-";
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(0)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

export function GexHistoryChart({ ticker }: { ticker: string }) {
  const [data, setData] = useState<RegimeGexResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setErr(null);
    setLoading(true);
    api
      .regimeGex(ticker)
      .then((r) => {
        if (!cancelled) {
          setData(r);
          setErr(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  const bars = useMemo(() => buildBars(data), [data]);

  if (loading) {
    return (
      <div style={PANEL}>
        <div style={HEADING}>Daily Gamma Exposure (GEX) — {ticker}</div>
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>Loading…</div>
      </div>
    );
  }

  if (err || bars.length === 0) {
    return (
      <div style={PANEL}>
        <div style={HEADING}>Daily Gamma Exposure (GEX) — {ticker}</div>
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          No GEX history yet.
        </div>
      </div>
    );
  }

  const W = 760;
  const H = 280;
  const PAD = { top: 20, right: 56, bottom: 24, left: 56 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const gexValues = bars
    .map((b) => b.net_gex)
    .filter((v): v is number => v != null);
  const spotValues = bars
    .map((b) => b.spot)
    .filter((v): v is number => v != null);

  if (gexValues.length === 0) {
    return (
      <div style={PANEL}>
        <div style={HEADING}>Daily Gamma Exposure (GEX) — {ticker}</div>
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Thin GEX history for {ticker}.
        </div>
      </div>
    );
  }

  const gexMax = Math.max(...gexValues.map(Math.abs), 1);
  const yGex = (v: number) =>
    PAD.top + innerH / 2 - (v / gexMax) * (innerH / 2 - 4);

  // Pad the spot domain so a constant series doesn't sit at the chart floor.
  let spotMin: number, spotMax: number;
  if (spotValues.length > 0) {
    const lo = Math.min(...spotValues);
    const hi = Math.max(...spotValues);
    if (lo === hi) {
      const pad = Math.max(Math.abs(lo) * 0.02, 1);
      spotMin = lo - pad;
      spotMax = hi + pad;
    } else {
      spotMin = lo;
      spotMax = hi;
    }
  } else {
    spotMin = 0;
    spotMax = 1;
  }
  const spotRange = spotMax - spotMin || 1;
  const ySpot = (v: number) =>
    PAD.top + innerH - ((v - spotMin) / spotRange) * innerH;

  const barW = innerW / bars.length;

  return (
    <div style={PANEL}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <div style={HEADING}>Daily Gamma Exposure (GEX) — {ticker}</div>
        <div style={{ display: "flex", gap: 12, fontSize: 10 }}>
          <span style={{ color: "var(--accent-warm)" }}>— Price</span>
          <span style={{ color: "var(--accent-vivid)" }}>■ Net Gamma</span>
        </div>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ width: "100%", height: "auto", aspectRatio: `${W} / ${H}` }}
        role="img"
        aria-label="Daily GEX history"
      >
        <title>Daily GEX history — net gamma bars with price overlay</title>
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={PAD.top + innerH / 2}
          y2={PAD.top + innerH / 2}
          stroke="var(--border-dim)"
          strokeWidth={1}
        />
        {bars.map((b, i) => {
          if (b.net_gex == null) return null;
          const x = PAD.left + i * barW + 1;
          const y0 = PAD.top + innerH / 2;
          const y = yGex(b.net_gex);
          return (
            <rect
              key={b.date}
              x={x}
              y={Math.min(y, y0)}
              width={Math.max(barW - 2, 1)}
              height={Math.abs(y - y0)}
              fill="var(--accent-vivid)"
              opacity={0.7}
            />
          );
        })}
        {spotValues.length > 0 && (
          <polyline
            fill="none"
            stroke="var(--accent-warm)"
            strokeWidth={1.5}
            points={bars
              .map((b, i) =>
                b.spot == null
                  ? null
                  : `${PAD.left + i * barW + barW / 2},${ySpot(b.spot)}`,
              )
              .filter(Boolean)
              .join(" ")}
          />
        )}
        <text
          x={PAD.left - 8}
          y={PAD.top + 8}
          textAnchor="end"
          fontSize={9}
          fill="var(--text-muted)"
        >
          {fmtTick(gexMax)}
        </text>
        <text
          x={PAD.left - 8}
          y={PAD.top + innerH - 4}
          textAnchor="end"
          fontSize={9}
          fill="var(--text-muted)"
        >
          {fmtTick(-gexMax)}
        </text>
        {spotValues.length > 0 && (
          <>
            <text
              x={W - PAD.right + 8}
              y={PAD.top + 8}
              fontSize={9}
              fill="var(--text-muted)"
            >
              {spotMax.toFixed(0)}
            </text>
            <text
              x={W - PAD.right + 8}
              y={PAD.top + innerH - 4}
              fontSize={9}
              fill="var(--text-muted)"
            >
              {spotMin.toFixed(0)}
            </text>
          </>
        )}
      </svg>
    </div>
  );
}
