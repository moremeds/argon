"use client";

/**
 * Stage growth comparison — the chains whose stages the taxonomy ranks.
 *
 * Each ring is one stage, and its RADIUS IS THAT STAGE'S MEDIAN REVENUE GROWTH
 * (TTM YoY). Both cases are drawn on ONE SHARED SCALE, so the two objects are
 * directly comparable. The taxonomy's rank order sets the stacking order and
 * nothing more: it is not a procurement chain, no payment is traced between
 * stages, and two stages may simply be parallel suppliers.
 *
 * THE SHARED SCALE IS LOAD-BEARING AND SILENT WHEN BROKEN. `radius()` is one
 * function over both cases and `GROWTH_CAP` is a constant, deliberately: a cap
 * fitted to the data would let one outlier compress every other stage, and a
 * per-case scale would make the two silhouettes look comparable while
 * measuring different things. Nothing on screen would show it. Both funnels
 * therefore render from one component, side by side, from one request.
 *
 * A company past the cap is clamped to the rim and flagged in the stage table
 * rather than allowed to set the scale for everyone else.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CaseStageMember, DeskCase } from "@/lib/api";
import {
  DASH,
  GROWTH_CAP,
  MID,
  alpha,
  onThemeChange,
  pct,
  readPalette,
  sgn,
  caseToken,
  stageLabel,
  summariseCase,
  valuationPhrase,
  type CaseSummary,
  type DeskPalette,
} from "@/lib/fundamentals/desk";
import { createScene, type SceneHandle } from "@/lib/fundamentals/scene";

import { MONO, Note, VizButton, VizFrame, labelStyle } from "./DeskSection";

const HEIGHT = 470;
const RADIUS_MIN = 0.12;
const RADIUS_MAX = 0.78;
function radius(growth: number | null): number {
  if (growth == null) return RADIUS_MIN;
  const clamped = Math.max(0, Math.min(GROWTH_CAP, growth));
  return RADIUS_MIN + (clamped / GROWTH_CAP) * (RADIUS_MAX - RADIUS_MIN);
}

interface HoverTarget {
  member: CaseStageMember;
  stage: string;
}

export function CaseFunnels({ cases }: { cases: DeskCase[] }) {
  const [spin, setSpin] = useState(true);
  const [hover, setHover] = useState<HoverTarget | null>(null);
  const scenes = useRef<(SceneHandle<HoverTarget> | null)[]>([]);

  // A STABLE callback, not the ref itself: a child writing through a ref prop
  // is a render-phase mutation, and a fresh inline closure per render would
  // re-run the child's scene effect on every state change — tearing down and
  // rebuilding both funnels each time the readout updates.
  const register = useCallback(
    (index: number, handle: SceneHandle<HoverTarget> | null) => {
      scenes.current[index] = handle;
    },
    [],
  );

  // Cases that can actually be drawn, paired with their summary.
  //
  // Filtered INDIVIDUALLY, not all-or-nothing. A single case with one stage —
  // a chain the taxonomy has begun ranking and not finished — used to blank
  // every funnel on the page under a message saying no chain carries ranked
  // stages, which is false about the chains that do. A provisional case
  // should cost its own funnel and nothing else.
  const drawable = useMemo(
    () =>
      cases
        .map((kase) => ({ kase, s: summariseCase(kase.stages) }))
        .filter((x): x is { kase: DeskCase; s: CaseSummary } => x.s !== null),
    [cases],
  );

  // One scene drives the others, so the two silhouettes are always compared
  // from the same angle. A per-funnel orientation would let a reader see one
  // case front-on and the other edge-on and believe the difference is data.
  const syncFrom = useCallback((index: number, yaw: number, pitch: number) => {
    scenes.current.forEach((s, i) => {
      if (i !== index) s?.setRotation(yaw, pitch);
    });
  }, []);

  const toggleSpin = useCallback((on: boolean) => {
    setSpin(on);
    scenes.current.forEach((s) => s?.setSpin(on));
  }, []);

  if (drawable.length === 0) {
    return (
      <p style={{ marginTop: 16, fontSize: 12.5, color: "var(--text-muted)" }}>
        No chain in this section carries ranked stages, so there is no flow to
        draw. That is the taxonomy&apos;s state, not an empty industry.
      </p>
    );
  }

  return (
    <>
      <VizFrame
        caption={
          <>
            Stage growth comparison {MID} ring = stage equal-weight median
            revenue growth (TTM YoY) {MID} dot = one company at its own TTM
            growth
          </>
        }
        controls={
          <VizButton pressed={spin} onClick={() => toggleSpin(!spin)}>
            Auto-rotate
          </VizButton>
        }
        readout={
          hover ? (
            <>
              <span>
                <b style={{ color: "var(--text-primary)" }}>
                  {hover.member.ticker}
                </b>
              </span>
              <span>{hover.stage}</span>
              <span>
                revenue growth (TTM YoY, %){" "}
                <b style={{ color: "var(--text-primary)" }}>
                  {hover.member.rev_yoy == null
                    ? "TTM growth unavailable"
                    : sgn(hover.member.rev_yoy)}
                </b>
              </span>
              {hover.member.gross_margin != null ? (
                <span>
                  reported gross margin (latest quarter, %){" "}
                  <b style={{ color: "var(--text-primary)" }}>
                    {pct(hover.member.gross_margin)}
                  </b>
                </span>
              ) : null}
              <span>
                valuation vs own history{" "}
                <b style={{ color: "var(--text-primary)" }}>
                  {valuationPhrase(hover.member.spot_percentile)}
                </b>
              </span>
              {hover.member.reported_currency ? (
                <span style={{ color: "var(--warning)" }}>
                  files in {hover.member.reported_currency}
                </span>
              ) : null}
            </>
          ) : (
            <span>
              Hover a company. Drag either funnel {DASH} both rotate together.
            </span>
          )
        }
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${drawable.length}, minmax(0, 1fr))`,
          }}
        >
          {drawable.map(({ kase, s }, i) => (
            <Funnel
              key={kase.slug}
              index={i}
              kase={kase}
              summary={s}
              spin={spin}
              onHover={setHover}
              onRotate={syncFrom}
              onSpinChange={toggleSpin}
              register={register}
            />
          ))}
        </div>
      </VizFrame>

      <Note>
        The radius is a truncated display mapping over 0% to +80% TTM growth:
        a stage or company outside that range is drawn at the rim, and
        a company with no TTM growth sits on its stage&apos;s own ring as a
        hollow mark rather than at the centre. Negative, missing and
        off-scale values are all in the stage table below. The rings are
        stacked in the taxonomy&apos;s rank order, which is an ordering of
        stages and not a traced flow of money between them.
      </Note>
    </>
  );
}

function Funnel({
  index,
  kase,
  summary,
  spin,
  onHover,
  onRotate,
  onSpinChange,
  register,
}: {
  index: number;
  kase: DeskCase;
  summary: CaseSummary;
  spin: boolean;
  onHover: (t: HoverTarget | null) => void;
  onRotate: (index: number, yaw: number, pitch: number) => void;
  onSpinChange: (on: boolean) => void;
  /** Stable registrar from the parent — see the note on its definition. */
  register: (index: number, handle: SceneHandle<HoverTarget> | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const paletteRef = useRef<DeskPalette | null>(null);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, s: SceneHandle<HoverTarget>["state"]) => {
      const c = paletteRef.current ?? readPalette();
      const accent = getComputedStyle(document.documentElement)
        .getPropertyValue(caseToken(index))
        .trim();
      const ordered = summary.downstreamFirst;
      const n = ordered.length;
      // Depth-sorted painter list. Stage labels carry z = -Infinity so they
      // always draw last, in a fixed left gutter that never rotates away.
      const items: { z: number; paint: () => void }[] = [];

      ordered.forEach((stage, i) => {
        const y = 0.88 - (i / (n - 1)) * 1.76;
        const R = radius(stage.median_rev_yoy);
        const ring: { u: number; v: number }[] = [];
        for (let t = 0; t <= 56; t++) {
          const th = (t / 56) * Math.PI * 2;
          ring.push(s.project(Math.cos(th) * R, y, Math.sin(th) * R));
        }
        const mid = s.project(0, y, 0);
        items.push({
          z: mid.z,
          paint: () => {
            ctx.beginPath();
            ctx.moveTo(ring[0].u, ring[0].v);
            for (let t = 1; t < ring.length; t++)
              ctx.lineTo(ring[t].u, ring[t].v);
            ctx.closePath();
            ctx.fillStyle = alpha(accent, 0.08);
            ctx.fill();
            ctx.strokeStyle = alpha(accent, 0.6);
            ctx.lineWidth = 1.4;
            ctx.stroke();
          },
        });

        if (i < n - 1) {
          const y2 = 0.88 - ((i + 1) / (n - 1)) * 1.76;
          const m2 = s.project(0, y2, 0);
          items.push({
            z: mid.z + 0.002,
            paint: () => {
              ctx.strokeStyle = alpha(accent, 0.3);
              ctx.lineWidth = 1;
              ctx.setLineDash([3, 3]);
              ctx.beginPath();
              ctx.moveTo(mid.u, mid.v);
              ctx.lineTo(m2.u, m2.v);
              ctx.stroke();
              ctx.setLineDash([]);
            },
          });
        }

        stage.members.forEach((member, j) => {
          const th = (j / stage.members.length) * Math.PI * 2 + i * 0.4;
          // A non-reporting name sits on its STAGE'S ring, not at the centre:
          // it is in the chain and excluded from the median, never imputed.
          const nr = member.rev_yoy == null ? R : radius(member.rev_yoy);
          const q = s.project(Math.cos(th) * nr, y, Math.sin(th) * nr);
          const target: HoverTarget = {
            member,
            stage: stageLabel(stage.layer),
          };
          items.push({
            z: q.z,
            paint: () => {
              const hot = s.hover?.member.ticker === member.ticker;
              const rr = (member.rev_yoy == null ? 3.4 : 4.6) * q.k;
              ctx.beginPath();
              ctx.arc(q.u, q.v, rr, 0, Math.PI * 2);
              if (member.rev_yoy == null) {
                ctx.strokeStyle = c.warn;
                ctx.lineWidth = 1.6;
                ctx.setLineDash([2, 2]);
                ctx.stroke();
                ctx.setLineDash([]);
              } else {
                ctx.fillStyle = hot ? c.ink : alpha(accent, 0.9);
                ctx.fill();
              }
              if (hot) {
                ctx.font = `600 12px ${MONO}, monospace`;
                ctx.textAlign = "center";
                ctx.textBaseline = "bottom";
                ctx.fillStyle = c.ink;
                ctx.fillText(member.ticker, q.u, q.v - rr - 5);
              }
              s.hit.push({ u: q.u, v: q.v, r: rr + 2, data: target });
            },
          });
        });

        items.push({
          z: -Infinity,
          paint: () => {
            ctx.font = `600 11px var(--font-sans), sans-serif`;
            ctx.textAlign = "left";
            ctx.textBaseline = "alphabetic";
            ctx.fillStyle = c.body;
            ctx.fillText(stageLabel(stage.layer), 12, mid.v - 1);
            ctx.font = `11px ${MONO}, monospace`;
            ctx.fillStyle = accent;
            ctx.fillText(
              `${sgn(stage.median_rev_yoy, 0)}  ${stage.reporting}/${stage.total}`,
              12,
              mid.v + 13,
            );
          },
        });
      });

      items.sort((a, b) => b.z - a.z);
      for (const item of items) item.paint();

      ctx.font = `10px ${MONO}, monospace`;
      ctx.fillStyle = c.faint;
      ctx.textAlign = "left";
      ctx.textBaseline = "alphabetic";
      ctx.fillText("customer", 12, 20);
      ctx.fillText("upstream", 12, s.H - 10);
    },
    [index, summary],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    paletteRef.current = readPalette();
    const scene = createScene<HoverTarget>(canvas, {
      yaw: 0.5,
      pitch: 0.42,
      zoom: 0.35,
      dist: 5.2,
      cxf: 0.63,
      spin,
      draw,
      onHover,
      onSpinChange,
      onRotate: (yaw, pitch) => onRotate(index, yaw, pitch),
    });
    register(index, scene);
    const repaint = () => {
      paletteRef.current = readPalette();
      scene.draw();
    };
    const off = onThemeChange(repaint);
    let timer: ReturnType<typeof setTimeout>;
    const onResize = () => {
      clearTimeout(timer);
      timer = setTimeout(() => scene.resize(), 120);
    };
    window.addEventListener("resize", onResize);
    return () => {
      off();
      clearTimeout(timer);
      window.removeEventListener("resize", onResize);
      scene.destroy();
      register(index, null);
    };
    // `spin` is the INITIAL value only; later changes travel through
    // `setSpin` on the handle, so re-creating the scene on it would restart
    // the rotation and desync the pair.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draw, index, onHover, onRotate, onSpinChange, register]);

  const accentVar = `var(${caseToken(index)})`;
  return (
    <div
      style={{
        minWidth: 0,
        borderRight: index === 0 ? "1px solid var(--border-dim)" : "none",
      }}
    >
      <div
        style={{
          padding: "10px 14px 11px",
          borderBottom: "1px solid var(--border-dim)",
          borderTop: `2px solid ${accentVar}`,
        }}
      >
        <div
          style={{
            ...labelStyle,
            color: "var(--text-primary)",
            letterSpacing: 1.2,
          }}
        >
          {kase.label}
        </div>
        <div
          style={{
            marginTop: 4,
            fontFamily: MONO,
            fontSize: 11,
            color: "var(--text-secondary)",
          }}
        >
          customer group {sgn(summary.customer.median_rev_yoy, 0)} {MID}{" "}
          upstream group {sgn(summary.upstream.median_rev_yoy, 0)} {MID} TTM
          YoY medians
        </div>
      </div>
      <canvas
        ref={canvasRef}
        height={HEIGHT}
        style={{
          display: "block",
          width: "100%",
          height: HEIGHT,
          cursor: "grab",
          touchAction: "none",
        }}
      />
    </div>
  );
}
