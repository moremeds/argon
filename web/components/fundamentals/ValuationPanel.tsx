"use client";

/**
 * Question 3 — what am I paying for it?
 *
 * ONE RULE GOVERNS THIS PANEL, AND IT CAME FROM MEASUREMENT RATHER THAN TASTE.
 * Valuation in this store TIMES A NAME AGAINST ITS OWN HISTORY (within-ticker
 * `sales_to_ev` IC +0.0744, t 5.77) and INVERTS ACROSS NAMES (cross-sectional
 * `book_to_price` IC -0.0365, t -2.32). So each name is shown against itself
 * and there is no way to sort the strip. Ranking here would be selling a
 * measured negative as a signal.
 *
 * The percentile is a YIELD percentile: 0.80 means CHEAP, not expensive. That
 * inversion is the most misreadable number on this desk, so it never appears
 * as a bare figure without the word beside it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ChainMetricCell } from "@/lib/api";
import {
  DASH,
  LARR,
  MID,
  RARR,
  alpha,
  median,
  onThemeChange,
  readPalette,
  valuationMarks,
  valuationPhrase,
  VALUATION_CHEAP,
  VALUATION_RICH,
  type DeskPalette,
  type ValuationMark,
} from "@/lib/fundamentals/desk";

import { MONO, Note, Num, VizFrame } from "./DeskSection";

const HEIGHT = 176;
const PAD = { l: 28, r: 28, t: 22, b: 36 };
/** Label thresholds for reading, never a screen. Shared with the stage table
 *  and the funnel readout through `valuationPhrase`, so one surface can never
 *  call a name rich while another calls it mid-range. */
const CHEAP = VALUATION_CHEAP;
const RICH = VALUATION_RICH;

interface Dot {
  x: number;
  y: number;
  mark: ValuationMark;
}

export function ValuationPanel({ cells }: { cells: ChainMetricCell[] }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dotsRef = useRef<Dot[]>([]);
  // A ref, not state — see the note in CapexPanel: the palette is an
  // external system the canvas reads, and nothing renders from it.
  const paletteRef = useRef<DeskPalette | null>(null);
  const [hover, setHover] = useState<ValuationMark | null>(null);

  // Memoised because `draw` closes over `marks`: recomputed every render, the
  // callback's dependency changes every render and the memoisation the canvas
  // relies on is silently dropped.
  const { marks, universe } = useMemo(() => valuationMarks(cells), [cells]);
  const values = marks.map((m) => m.percentile);
  const mid = median(values);
  const nRich = values.filter((v) => v <= RICH).length;
  const nCheap = values.filter((v) => v >= CHEAP).length;

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || marks.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const c = paletteRef.current ?? readPalette();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = canvas.clientWidth || 640;
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(HEIGHT * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, HEIGHT);

    const iw = W - PAD.l - PAD.r;
    const base = HEIGHT - PAD.b;
    ctx.font = `10px ${MONO}, monospace`;
    ctx.textBaseline = "top";
    for (let g = 0; g <= 10; g += 2) {
      const x = PAD.l + (g / 10) * iw;
      ctx.strokeStyle = c.grid;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x + 0.5, PAD.t - 10);
      ctx.lineTo(x + 0.5, base);
      ctx.stroke();
      ctx.fillStyle = c.faint;
      ctx.textAlign = "center";
      ctx.fillText(`P${g * 10}`, x, base + 7);
    }
    // The words, not just the axis. A bare 0.80 reads as expensive to anyone
    // who has met a price percentile before.
    ctx.textAlign = "left";
    ctx.fillStyle = c.bad;
    ctx.fillText(`${LARR} rich against its own history`, PAD.l, base + 21);
    ctx.textAlign = "right";
    ctx.fillStyle = c.good;
    ctx.fillText(`cheap against its own history ${RARR}`, W - PAD.r, base + 21);

    // Beeswarm: names at the same percentile stack upward rather than
    // overplotting, so the shape of the distribution survives.
    const bins = new Map<number, number>();
    const dots: Dot[] = [];
    for (const mark of marks) {
      const x = PAD.l + mark.percentile * iw;
      const key = Math.round(x / 9);
      const n = (bins.get(key) ?? 0) + 1;
      bins.set(key, n);
      dots.push({ x, y: base - 8 - (n - 1) * 9, mark });
    }
    dotsRef.current = dots;

    for (const d of dots) {
      const hot = hover?.ticker === d.mark.ticker;
      ctx.beginPath();
      ctx.arc(d.x, d.y, hot ? 5.4 : 3.8, 0, Math.PI * 2);
      ctx.fillStyle =
        d.mark.percentile >= CHEAP
          ? alpha(c.good, 0.85)
          : d.mark.percentile <= RICH
            ? alpha(c.bad, 0.78)
            : alpha(c.layer[1], 0.7);
      ctx.fill();
      if (hot) {
        ctx.strokeStyle = c.ink;
        ctx.lineWidth = 1.6;
        ctx.stroke();
        ctx.font = `600 11px ${MONO}, monospace`;
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.fillStyle = c.ink;
        ctx.fillText(d.mark.ticker, d.x, d.y - 7);
        ctx.font = `10px ${MONO}, monospace`;
        ctx.textBaseline = "top";
      }
    }
  }, [hover, marks]);

  useEffect(() => {
    paletteRef.current = readPalette();
    draw();
  }, [draw]);
  useEffect(() => {
    const off = onThemeChange(() => {
      paletteRef.current = readPalette();
      draw();
    });
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

  if (marks.length === 0) {
    return (
      <Note>
        None of the <Num>{universe}</Num> companies on this desk carries an
        own-history valuation band, so the reading is unavailable. The desk
        says so rather than reaching for a cross-sectional rank, which measured
        INVERTED in this same universe.
      </Note>
    );
  }

  return (
    <>
      <VizFrame
        caption={
          <>
            Own-history yield percentile {MID} right is cheap against a
            name&apos;s own past {MID} each mark is one company
          </>
        }
        readout={
          hover ? (
            <>
              <span>
                <b style={{ color: "var(--text-primary)" }}>{hover.ticker}</b>
              </span>
              <span>
                own-history yield percentile{" "}
                <b style={{ color: "var(--text-primary)" }}>
                  {valuationPhrase(hover.percentile)}
                </b>
              </span>
              <span>relative to its own history, not to its peers</span>
            </>
          ) : (
            <>
              <span>
                <b style={{ color: "var(--text-primary)" }}>{marks.length}</b>{" "}
                of <b style={{ color: "var(--text-primary)" }}>{universe}</b>{" "}
                companies carry a band
              </span>
              <span>
                median{" "}
                <b style={{ color: "var(--text-primary)" }}>
                  {valuationPhrase(mid)}
                </b>
              </span>
              <span>
                <b style={{ color: "var(--text-primary)" }}>{nRich}</b> rich{" "}
                {MID} <b style={{ color: "var(--text-primary)" }}>{nCheap}</b>{" "}
                cheap
              </span>
            </>
          )
        }
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
            const mx = e.clientX - rect.left;
            const my = e.clientY - rect.top;
            let best: ValuationMark | null = null;
            let bd = Infinity;
            for (const d of dotsRef.current) {
              const dist = Math.hypot(d.x - mx, d.y - my);
              if (dist < 9 && dist < bd) {
                bd = dist;
                best = d.mark;
              }
            }
            setHover(best);
          }}
          onPointerLeave={() => setHover(null)}
        />
      </VizFrame>

      <Note>
        <strong style={{ color: "var(--text-secondary)" }}>
          Coverage is the honest headline here.
        </strong>{" "}
        Only <Num>{marks.length}</Num> of <Num>{universe}</Num> companies on the
        chain map carry a band at all {DASH} the rest are simply unavailable
        here, and this panel does not say why. Among those that do, the median
        sits at <Num>{valuationPhrase(mid)}</Num>:{" "}
        {mid != null && mid < 0.5 ? (
          <>
            the typical covered name is <em>richer</em> than it has usually been
            against itself
          </>
        ) : (
          <>
            the typical covered name is <em>cheaper</em> than it has usually
            been against itself
          </>
        )}
        , <Num>{nRich}</Num> rich against <Num>{nCheap}</Num> cheap. The
        percentile is a <em>yield</em> percentile against the name&apos;s own
        history {DASH} P80 means cheap relative to its own past, not an 80%
        discount {DASH} which is the most misreadable number on this desk, so
        it never appears as a bare figure without the word beside it. There is
        no way to sort this strip, deliberately.
      </Note>
    </>
  );
}
