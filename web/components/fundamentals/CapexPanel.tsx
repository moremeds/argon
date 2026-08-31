"use client";

/**
 * Question 1 — is the money still coming?
 *
 * Every revenue dollar downstream on this desk is somebody else's capital
 * expenditure, which makes this the one number here not derived from another
 * number here. It is the desk's PREMISE, not its edge: the figure is on every
 * sell-side deck in the sector, and nothing on this desk is ranked by it.
 *
 * THE SIGN WARNING, KEPT FROM THE STRIP THIS PANEL REPLACES. For the names
 * that SPEND the capex it is a cost line, not evidence of demand — it reaches
 * their income statement as depreciation. Rising capex read as bullish for the
 * spender inverts its meaning.
 *
 * The LEVEL is not the story; the INTENSITY is. A chain fed by a third of its
 * customers' revenue is not fed by a budget line, it is fed by a decision that
 * can be revisited in a single quarter — which is the whole reason this is
 * question one rather than an appendix.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  DASH,
  MID,
  TIMES,
  alpha,
  onThemeChange,
  pct,
  readPalette,
  sgn,
  usdB,
  type DeskPalette,
} from "@/lib/fundamentals/desk";
import type { CapexQuarter, DeskCapexResponse } from "@/lib/api";

import { Finding, MONO, Note, Num, VizFrame, labelStyle } from "./DeskSection";

const PAD = { l: 56, r: 58, t: 18, b: 30 };
const HEIGHT = 300;

/** A round ceiling above `max`, so gridlines land on readable numbers. */
function ceilTo(max: number, step: number): number {
  return Math.max(step, Math.ceil(max / step) * step);
}

function Tile({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div
      style={{
        padding: "10px 14px",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        background: "var(--bg-panel)",
        minWidth: 0,
      }}
    >
      <div style={labelStyle}>{label}</div>
      <div
        style={{
          marginTop: 5,
          fontFamily: MONO,
          fontSize: 22,
          fontWeight: 700,
          letterSpacing: 1,
          color: "var(--text-primary)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
      <div
        style={{
          marginTop: 3,
          fontFamily: MONO,
          fontSize: 10.5,
          color: "var(--text-muted)",
        }}
      >
        {sub}
      </div>
    </div>
  );
}

export function CapexPanel({ data }: { data: DeskCapexResponse }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // The palette is an EXTERNAL system (argon's CSS custom properties), not
  // React state: it is read during a paint and never renders anything by
  // itself. Holding it in state would set state from an effect on every
  // theme change and cascade a render for a value only the canvas reads.
  const paletteRef = useRef<DeskPalette | null>(null);
  const [hover, setHover] = useState<number>(-1);

  const quarters = data.quarters;
  const first = quarters[0];
  const last = quarters[quarters.length - 1];
  // Four quarters back, not "the previous row": a year-over-year comparison
  // against an adjacent quarter would report seasonality as growth.
  /** `2026Q2` -> `2025Q2`, matched by KEY and never by array position.
   *
   *  `quarters[i - 4]` assumes the series has no holes. It does have holes: a
   *  quarter appears only if at least one panel member filed capex for it, so
   *  one absent quarter silently turns "year over year" into a comparison
   *  against the wrong period, still labelled YoY. */
  const byQuarter = useMemo(
    () => new Map(quarters.map((q) => [q.quarter, q])),
    [quarters],
  );
  const priorYear = (key: string): CapexQuarter | null => {
    const [y, n] = key.split("Q");
    return byQuarter.get(`${Number(y) - 1}Q${n}`) ?? null;
  };

  /** The latest quarter every panel member has filed.
   *
   *  Hyperscalers report across a ~3-week window, so the most recent row is
   *  routinely PARTIAL: `capex_usd` sums only the names that filed, while the
   *  panel is larger. Headlining that sum would render an incomplete quarter
   *  as a fall in spending — on the one question the desk opens with. The
   *  chart still draws every quarter (partial ones hollow); only the headline
   *  refuses to compare a partial sum against a whole one. */
  const base = [...quarters].reverse().find((q) => q.complete) ?? null;
  const partialTail = base !== null && base.quarter !== last?.quarter;
  const yearAgo = base ? priorYear(base.quarter) : null;
  /** A growth multiple, or `null` through a zero base.
   *
   *  The same refusal `summariseCase` makes for amplification: a ratio through
   *  zero is arithmetic, not growth, and `Infinity×` on the desk's opening
   *  tile would be the most confident-looking number on the page. */
  const times = (now: number | null, then: number | null): string | null =>
    now != null && then != null && then > 0 ? `${(now / then).toFixed(1)}${TIMES}` : null;
  const capexTimes = times(base?.capex_usd ?? null, first?.capex_usd ?? null);
  const revenueTimes = times(base?.revenue_usd ?? null, first?.revenue_usd ?? null);

  const scales = useMemo(() => {
    const maxCapex = quarters.reduce((a, q) => Math.max(a, q.capex_usd), 0);
    const maxIntensity = quarters.reduce(
      (a, q) => (q.revenue_usd ? Math.max(a, q.capex_usd / q.revenue_usd) : a),
      0,
    );
    return {
      capex: ceilTo(maxCapex / 1e9, 40) * 1e9,
      intensity: ceilTo(maxIntensity, 0.1),
    };
  }, [quarters]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || quarters.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const c = paletteRef.current ?? readPalette();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = canvas.clientWidth || 640;
    const H = HEIGHT;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const iw = W - PAD.l - PAD.r;
    const ih = H - PAD.t - PAD.b;
    const bw = iw / quarters.length;
    ctx.font = `10px ${MONO}, monospace`;
    ctx.textBaseline = "middle";

    const capexB = scales.capex / 1e9;
    for (let g = 0; g <= capexB; g += 40) {
      const y = PAD.t + ih - (g / capexB) * ih;
      ctx.strokeStyle = c.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(PAD.l, y + 0.5);
      ctx.lineTo(W - PAD.r, y + 0.5);
      ctx.stroke();
      ctx.fillStyle = c.faint;
      ctx.textAlign = "right";
      ctx.fillText(`$${g}B`, PAD.l - 8, y);
    }
    for (let p = 0; p <= scales.intensity * 100 + 0.001; p += 10) {
      ctx.fillStyle = c.layer[3];
      ctx.textAlign = "left";
      ctx.fillText(
        `${p}%`,
        W - PAD.r + 8,
        PAD.t + ih - (p / 100 / scales.intensity) * ih,
      );
    }

    quarters.forEach((q, i) => {
      const h = (q.capex_usd / scales.capex) * ih;
      // An incomplete quarter is drawn hollow: its level stepped because a
      // filer is missing, not because anything changed at the companies.
      const x = PAD.l + i * bw + bw * 0.16;
      const w = bw * 0.68;
      if (q.complete) {
        ctx.fillStyle = i === hover ? c.layer[1] : alpha(c.layer[1], 0.7);
        ctx.fillRect(x, PAD.t + ih - h, w, h);
      } else {
        ctx.strokeStyle = alpha(c.warn, 0.9);
        ctx.lineWidth = 1.4;
        ctx.setLineDash([3, 3]);
        ctx.strokeRect(
          x + 0.5,
          PAD.t + ih - h + 0.5,
          w - 1,
          Math.max(1, h - 1),
        );
        ctx.setLineDash([]);
      }
    });

    const line = quarters
      .map((q, i) =>
        q.revenue_usd
          ? {
              x: PAD.l + i * bw + bw / 2,
              y:
                PAD.t +
                ih -
                (q.capex_usd / q.revenue_usd / scales.intensity) * ih,
            }
          : null,
      )
      .filter((p): p is { x: number; y: number } => p !== null);
    ctx.strokeStyle = c.layer[3];
    ctx.lineWidth = 2;
    ctx.beginPath();
    line.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    ctx.stroke();
    for (const p of line) {
      ctx.fillStyle = c.card;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 3.4, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = c.layer[3];
      ctx.lineWidth = 1.8;
      ctx.stroke();
    }

    ctx.fillStyle = c.faint;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    quarters.forEach((q, i) => {
      if (i % 2 === 0 || i === quarters.length - 1)
        ctx.fillText(q.quarter, PAD.l + i * bw + bw / 2, PAD.t + ih + 9);
    });
    ctx.strokeStyle = c.rule;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD.l, PAD.t + ih + 0.5);
    ctx.lineTo(W - PAD.r, PAD.t + ih + 0.5);
    ctx.stroke();
  }, [hover, quarters, scales]);

  useEffect(() => {
    paletteRef.current = readPalette();
    draw();
  }, [draw]);

  useEffect(() => {
    const repaint = () => {
      paletteRef.current = readPalette();
      draw();
    };
    const off = onThemeChange(repaint);
    let timer: ReturnType<typeof setTimeout>;
    const onResize = () => {
      clearTimeout(timer);
      timer = setTimeout(draw, 120);
    };
    window.addEventListener("resize", onResize);
    return () => {
      off();
      clearTimeout(timer);
      window.removeEventListener("resize", onResize);
    };
  }, [draw]);

  if (quarters.length === 0) {
    return (
      <Note>
        No member of <span style={{ fontFamily: MONO }}>{data.chain}</span>{" "}
        files in USD, so this desk cannot state a combined capital-expenditure
        figure for it at all. That is an unanswered question, not an answer of
        zero — a converted total would be this desk inventing an exchange rate.
      </Note>
    );
  }

  const shown = hover >= 0 ? quarters[hover] : (base ?? last);
  const shownPrior =
    hover >= 0 ? priorYear(quarters[hover].quarter) : yearAgo;
  const intensityNow =
    base?.revenue_usd ? base.capex_usd / base.revenue_usd : null;
  const intensityThen = first.revenue_usd
    ? first.capex_usd / first.revenue_usd
    : null;

  return (
    <>
      <div
        style={{
          marginTop: 16,
          display: "grid",
          gap: 10,
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        }}
      >
        <Tile
          label={partialTail ? "latest complete quarter" : "latest quarter"}
          value={base ? usdB(base.capex_usd) : "na"}
          sub={
            base
              ? `${base.quarter} ${MID} ${base.tickers.join(" ")}${
                  partialTail ? ` ${MID} ${last.quarter} still filing` : ""
                }`
              : "no quarter yet holds every panel member"
          }
        />
        <Tile
          label="year over year"
          value={
            base && yearAgo && yearAgo.capex_usd > 0
              ? sgn(base.capex_usd / yearAgo.capex_usd - 1)
              : "na"
          }
          sub={
            yearAgo
              ? `vs ${yearAgo.quarter} ${usdB(yearAgo.capex_usd)}`
              : "fewer than five quarters held"
          }
        />
        <Tile
          label={`since ${first.quarter}`}
          value={capexTimes ?? "na"}
          sub={
            base
              ? `${usdB(first.capex_usd)} ${DASH} ${usdB(base.capex_usd)}`
              : usdB(first.capex_usd)
          }
        />
        <Tile
          label="share of revenue"
          value={pct(intensityNow)}
          sub={
            intensityThen == null
              ? "no revenue held for the base quarter"
              : `was ${pct(intensityThen)} in ${first.quarter}`
          }
        />
      </div>

      <VizFrame
        caption={
          <>
            Quarterly capital expenditure {MID} {data.included.length} USD
            filers, bars {MID} capex as a share of their revenue, line
          </>
        }
        readout={<CapexReadout q={shown} prior={shownPrior} />}
      >
        <canvas
          ref={canvasRef}
          height={HEIGHT}
          style={{
            display: "block",
            width: "100%",
            height: HEIGHT,
            cursor: "crosshair",
          }}
          onPointerMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const bw = (rect.width - PAD.l - PAD.r) / quarters.length;
            const i = Math.floor((e.clientX - rect.left - PAD.l) / bw);
            setHover(i >= 0 && i < quarters.length ? i : -1);
          }}
          onPointerLeave={() => setHover(-1)}
        />
      </VizFrame>

      <Finding label="Finding">
        The level is not the story {DASH} the <em>intensity</em> is. These{" "}
        {data.included.length} companies committed{" "}
        <Num>{pct(intensityNow)}</Num> of their combined quarterly revenue to
        capital expenditure in {base ? base.quarter : DASH}, against{" "}
        <Num>{pct(intensityThen)}</Num> in {first.quarter}.
        {capexTimes ? (
          <>
            {" "}
            Spending grew <Num>{capexTimes}</Num>
            {revenueTimes ? (
              <>
                {" "}
                while their revenue grew <Num>{revenueTimes}</Num>
              </>
            ) : null}
            .
          </>
        ) : null}{" "}
        A chain fed by that share of its customers&apos; revenue is not fed by
        a budget line. It is fed by a decision that can be revisited in a single
        quarter, which is why this is question one and not an appendix.
      </Finding>

      <Note>
        <strong style={{ color: "var(--text-secondary)" }}>Panel:</strong>{" "}
        {data.included.join(", ")} {DASH} the members of argon&apos;s{" "}
        <span style={{ fontFamily: MONO }}>{data.chain}</span> chain that file
        in USD.{" "}
        {Object.entries(data.excluded).map(([ticker, currency], i) => (
          <span key={ticker}>
            {i > 0 ? "; " : ""}
            <strong style={{ color: "var(--text-secondary)" }}>
              {ticker}
            </strong>{" "}
            is excluded because it files in {currency}
          </span>
        ))}
        {Object.keys(data.excluded).length ? ", and " : ""}
        this desk does not convert currencies. Fiscal quarters are assigned to
        the calendar quarter containing their end date, which is what lets a
        May-ending filer sit beside a June-ending one. And read the direction
        with care: for the names that <em>spend</em> this, rising capex is a
        cost line arriving as depreciation, not evidence of their own demand.
      </Note>
    </>
  );
}

function CapexReadout({
  q,
  prior,
}: {
  q: CapexQuarter;
  prior: CapexQuarter | null;
}) {
  return (
    <>
      <span>
        <b style={{ color: "var(--text-primary)" }}>{q.quarter}</b>
      </span>
      <span>
        capex{" "}
        <b style={{ color: "var(--text-primary)" }}>{usdB(q.capex_usd)}</b>
      </span>
      <span>
        revenue{" "}
        <b style={{ color: "var(--text-primary)" }}>
          {q.revenue_usd == null ? "na" : usdB(q.revenue_usd)}
        </b>
      </span>
      <span>
        intensity{" "}
        <b style={{ color: "var(--text-primary)" }}>
          {q.revenue_usd == null ? "na" : pct(q.capex_usd / q.revenue_usd)}
        </b>
      </span>
      {prior && prior.capex_usd > 0 ? (
        <span>
          year over year{" "}
          <b style={{ color: "var(--text-primary)" }}>
            {sgn(q.capex_usd / prior.capex_usd - 1)}
          </b>
          {/* Comparing a partial quarter to a whole one is a fall that did
              not happen, so the readout says which side is incomplete rather
              than letting the percentage speak for a panel it does not hold. */}
          {q.complete && prior.complete ? null : " (partial)"}
        </span>
      ) : null}
      {q.complete ? null : (
        <span style={{ color: "var(--warning)" }}>
          {q.tickers.join(" ")} only {DASH} not the whole panel
        </span>
      )}
    </>
  );
}
