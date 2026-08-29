"use client";

/**
 * Question 2 — where does the money land?
 *
 * A PM needs three things about a chain at once: how fast it is growing, how
 * well it is paid, and where it sits in the stack. Any two of those on a flat
 * chart hide the third, so the map is dimensional and draggable: growth runs
 * left to right, gross margin runs into the depth, and the five taxonomy
 * layers are the stacked planes.
 *
 * WHY THERE ARE NO ARROWS BETWEEN THESE NODES
 * ---------------------------------------------
 * A link from one chain to another is a supply relationship, and the desk will
 * only draw one it can evidence. Barely any membership carries a magnitude a
 * company actually disclosed — the figure is computed and printed in the note
 * below rather than asserted. That is not enough to draw a network, so this
 * screen PLACES the chains and stops. Flow is modelled only where the taxonomy
 * defines ranked stages, which is what the case funnels are for.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ChainMetricCell, DeskLimitsResponse } from "@/lib/api";
import {
  DASH,
  LAYER_KEYS,
  LAYER_LABELS,
  LAYER_TOKENS,
  MID,
  RARR,
  TIMES,
  alpha,
  chainPoints,
  correlation,
  median,
  onThemeChange,
  pct,
  readPalette,
  sgn,
  type ChainPoint,
  type DeskPalette,
} from "@/lib/fundamentals/desk";
import { createScene, type SceneHandle } from "@/lib/fundamentals/scene";

import { Finding, MONO, Note, Num, VizButton, VizFrame } from "./DeskSection";

const HEIGHT = 470;

/** Camera presets. The first three FLATTEN the scene onto one pair of axes,
 *  which is the point: each one is a claim you can check by looking. */
const VIEWS: [string, number, number][] = [
  ["Growth × layer", 0, 0.06],
  ["Margin × layer", Math.PI / 2, 0.06],
  ["Growth × margin", 0, 1.3],
  ["Free rotate", 0.62, 0.38],
];

interface Placed extends ChainPoint {
  x: number;
  y: number;
  z: number;
  r: number;
}

/** Map each chain into the unit cube. Both axes are min-max scaled across the
 *  chains actually placed, so the cloud fills the box whatever the spread. */
function place(points: ChainPoint[]): Placed[] {
  const revs = points.map((p) => p.revYoy as number);
  const gms = points.map((p) => p.grossMargin as number);
  const rlo = Math.min(...revs);
  const rhi = Math.max(...revs);
  const glo = Math.min(...gms);
  const ghi = Math.max(...gms);
  const span = (v: number, lo: number, hi: number) =>
    hi === lo ? 0 : ((v - lo) / (hi - lo)) * 1.8 - 0.9;
  return points.map((p) => ({
    ...p,
    x: span(p.revYoy as number, rlo, rhi),
    z: span(p.grossMargin as number, glo, ghi),
    y: (p.layerIndex / 4) * 1.7 - 0.85,
    // Area, not radius, tracks member count — a radius-linear bubble
    // exaggerates a big chain by its square.
    r: 5 + Math.sqrt(p.members) * 3.1,
  }));
}

export function ChainMapPanel({
  cells,
  limits,
}: {
  cells: ChainMetricCell[];
  limits: DeskLimitsResponse | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sceneRef = useRef<SceneHandle<Placed> | null>(null);
  // The palette is an external system the canvas reads, never render input.
  const paletteRef = useRef<DeskPalette | null>(null);
  const [hover, setHover] = useState<Placed | null>(null);
  const [view, setView] = useState(3);

  const chains = useMemo(() => place(chainPoints(cells)), [cells]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D, s: SceneHandle<Placed>["state"]) => {
      const c = paletteRef.current ?? readPalette();

      for (let li = 0; li < 5; li++) {
        const y = (li / 4) * 1.7 - 0.85;
        const corners = [
          s.project(-1, y, -1),
          s.project(1, y, -1),
          s.project(1, y, 1),
          s.project(-1, y, 1),
        ];
        ctx.beginPath();
        ctx.moveTo(corners[0].u, corners[0].v);
        for (let i = 1; i < 4; i++) ctx.lineTo(corners[i].u, corners[i].v);
        ctx.closePath();
        ctx.fillStyle = alpha(c.faint, 0.07);
        ctx.fill();
        ctx.strokeStyle = alpha(c.layer[li], 0.42);
        ctx.lineWidth = 1;
        ctx.stroke();
        const label = s.project(-1.05, y, 1.05);
        ctx.font = `600 10.5px ${MONO}, monospace`;
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        ctx.fillStyle = c.layer[li];
        ctx.fillText(LAYER_KEYS[li], label.u, label.v);
      }

      // Both axis labels are anchored to projected world points, so a rotation
      // can swing them past the frame edge. Clamp to their own measured width.
      const ax = s.project(1.05, -0.85, -1);
      const az = s.project(-1, -0.85, 1.05);
      ctx.font = `10px ${MONO}, monospace`;
      ctx.fillStyle = c.faint;
      ctx.textBaseline = "top";
      const gl = `growth ${RARR}`;
      const ml = `gross margin ${RARR}`;
      ctx.textAlign = "left";
      ctx.fillText(
        gl,
        Math.min(ax.u + 4, s.W - ctx.measureText(gl).width - 4),
        ax.v + 4,
      );
      ctx.textAlign = "right";
      ctx.fillText(
        ml,
        Math.max(az.u - 4, ctx.measureText(ml).width + 4),
        az.v + 4,
      );

      // Painter's algorithm: far first, so a near node overlaps a far one.
      const projected = chains
        .map((p) => ({ p, q: s.project(p.x, p.y, p.z) }))
        .sort((a, b) => b.q.z - a.q.z);
      for (const { p, q } of projected) {
        const r = p.r * q.k;
        const hot = s.hover?.chain === p.chain;
        const foot = s.project(p.x, -0.85, p.z);
        ctx.strokeStyle = alpha(c.layer[p.layerIndex], hot ? 0.55 : 0.2);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(q.u, q.v);
        ctx.lineTo(foot.u, foot.v);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(q.u, q.v, r, 0, Math.PI * 2);
        ctx.fillStyle = alpha(c.layer[p.layerIndex], hot ? 0.95 : 0.6);
        ctx.fill();
        ctx.strokeStyle = hot ? c.ink : alpha(c.layer[p.layerIndex], 0.95);
        ctx.lineWidth = hot ? 2 : 1.2;
        ctx.stroke();
        if (hot) {
          ctx.font = `600 12.5px var(--font-sans), sans-serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "bottom";
          ctx.fillStyle = c.ink;
          ctx.fillText(p.chain, q.u, q.v - r - 6);
        }
        s.hit.push({ u: q.u, v: q.v, r, data: p });
      }
    },
    // `chains` closes over the draw, so a new placement rebuilds the scene
    // below. That is correct rather than wasteful: a scene still painting the
    // previous placement would be showing last request's answer.
    [chains],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    paletteRef.current = readPalette();
    const scene = createScene<Placed>(canvas, {
      yaw: VIEWS[3][1],
      pitch: VIEWS[3][2],
      // 0.27 rather than a rounder number: the plane's FAR corner is
      // magnified by perspective (k ~ 1.29 at this pitch) and reaches ~1.31
      // world units up the screen, so the top plane clips at anything above
      // ~0.28 on a 470px canvas. An e2e test asserts the margin survives.
      zoom: 0.27,
      dist: 4.4,
      draw,
      onHover: setHover,
    });
    sceneRef.current = scene;
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
      sceneRef.current = null;
    };
  }, [draw]);

  const layerMedians = useMemo(
    () =>
      LAYER_KEYS.map((L) =>
        median(
          chains.filter((c) => c.layer === L).map((c) => c.revYoy as number),
        ),
      ),
    [chains],
  );

  const spreads = useMemo(
    () =>
      LAYER_KEYS.map((L) => {
        const vals = chains
          .filter((c) => c.layer === L)
          .map((c) => c.revYoy as number);
        return {
          layer: L,
          spread: vals.length ? Math.max(...vals) - Math.min(...vals) : 0,
        };
      }).sort((a, b) => b.spread - a.spread),
    [chains],
  );

  const known = layerMedians.filter((m): m is number => m !== null);
  const between = known.length ? Math.max(...known) - Math.min(...known) : 0;
  const widest = spreads[0];
  const inWidest = chains
    .filter((c) => c.layer === widest?.layer)
    .sort((a, b) => (b.revYoy as number) - (a.revYoy as number));

  const corr = useMemo(
    () =>
      correlation(
        chains.map((c) => [c.revYoy as number, c.grossMargin as number]),
      ),
    [chains],
  );
  const byMargin = [...chains].sort(
    (a, b) => (b.grossMargin as number) - (a.grossMargin as number),
  );

  // `null` when /limits never answered — NOT a zero-filled tally. Reducing an
  // absent response over `?? []` yields `{members: 0, magnitude: 0}`, and the
  // Note below spends those numbers on an affirmative sentence: "of 0 chain
  // memberships, 0 carry a magnitude". That is a claim about the taxonomy
  // manufactured out of an HTTP failure, and the refusal it justifies (no
  // arrows) would then rest on evidence the desk never actually read.
  const exposure = limits
    ? limits.exposure_coverage.reduce(
        (a, e) => ({
          members: a.members + e.members,
          magnitude: a.magnitude + e.with_magnitude,
        }),
        { members: 0, magnitude: 0 },
      )
    : null;

  if (chains.length === 0) {
    return (
      <Note>
        No chain in this section carries both a growth and a margin median, so
        there is nothing to place. The map is empty because the desk holds no
        position for these chains, not because the chains are empty.
      </Note>
    );
  }

  return (
    <>
      <VizFrame
        caption={
          <>
            Chain map {MID} {chains.length} chains {MID} area ∝ member count{" "}
            {MID} colour = layer
          </>
        }
        controls={VIEWS.map(([label, yaw, pitch], i) => (
          <VizButton
            key={label}
            pressed={view === i}
            onClick={() => {
              setView(i);
              sceneRef.current?.goTo(yaw, pitch);
            }}
          >
            {label}
          </VizButton>
        ))}
        readout={
          hover ? (
            <>
              <span>
                <b style={{ color: "var(--text-primary)" }}>{hover.chain}</b>
              </span>
              <span>
                {LAYER_LABELS[hover.layer] ?? hover.layer} ({hover.layer})
              </span>
              <span>
                growth{" "}
                <b style={{ color: "var(--text-primary)" }}>
                  {sgn(hover.revYoy)}
                </b>
              </span>
              <span>
                gross margin{" "}
                <b style={{ color: "var(--text-primary)" }}>
                  {pct(hover.grossMargin)}
                </b>
              </span>
              <span>
                <b style={{ color: "var(--text-primary)" }}>
                  {hover.reporting}
                </b>{" "}
                of{" "}
                <b style={{ color: "var(--text-primary)" }}>{hover.members}</b>{" "}
                reported
              </span>
            </>
          ) : (
            <span>Hover a chain {DASH} or drag the map to rotate it.</span>
          )
        }
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) 232px",
          }}
        >
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
          <Legend
            chains={chains}
            hover={hover}
            onHover={(p) => {
              setHover(p);
              sceneRef.current?.setHover(p);
            }}
          />
        </div>
      </VizFrame>

      {widest &&
      inWidest.length > 1 &&
      between > 0 &&
      widest.spread > between ? (
        <Finding label="Finding — the layer explains less than the chain does">
          Flatten it to <em>Growth {TIMES} layer</em> and the five planes
          overlap heavily. The gap between the fastest and slowest layer median
          is <Num>{(between * 100).toFixed(1)}pp</Num>. Inside{" "}
          <strong style={{ color: "var(--text-secondary)" }}>
            {widest.layer}
          </strong>{" "}
          alone it is <Num>{(widest.spread * 100).toFixed(1)}pp</Num> {DASH}{" "}
          {inWidest[0].chain} at <Num>{sgn(inWidest[0].revYoy)}</Num> down to{" "}
          {inWidest[inWidest.length - 1].chain} at{" "}
          <Num>{sgn(inWidest[inWidest.length - 1].revYoy)}</Num> {DASH} same
          layer, each name at its own latest filed quarter. Knowing a company
          sits upstream tells you roughly{" "}
          <Num>
            {(widest.spread / between).toFixed(1)}
            {TIMES}
          </Num>{" "}
          less than knowing which chain it is in. That is the argument for
          running this desk at chain grain instead of sector grain.
        </Finding>
      ) : null}

      {corr ? (
        <Finding
          tone="warn"
          label={
            Math.abs(corr.t) < 2
              ? "Finding — growth and margin are close to unrelated"
              : "Finding — growth and margin move together in this panel"
          }
        >
          Flatten it to <em>Growth {TIMES} margin</em> and the cloud{" "}
          {Math.abs(corr.t) < 2 ? "has no tilt" : "tilts"}:{" "}
          <Num>r = {corr.r.toFixed(3)}</Num> across {corr.n} chains,{" "}
          <Num>t = {corr.t.toFixed(2)}</Num> {DASH}{" "}
          {Math.abs(corr.t) < 2
            ? "indistinguishable from none"
            : "a relationship this panel can see"}
          . {byMargin[0].chain} earns <Num>{pct(byMargin[0].grossMargin)}</Num>{" "}
          and grows <Num>{sgn(byMargin[0].revYoy)}</Num>;{" "}
          {byMargin[byMargin.length - 1].chain} earns{" "}
          <Num>{pct(byMargin[byMargin.length - 1].grossMargin)}</Num> and grows{" "}
          <Num>{sgn(byMargin[byMargin.length - 1].revYoy)}</Num>. Being close to
          the AI dollar and being paid well for it are separate questions, and
          the desk refuses to blend them into one score.
        </Finding>
      ) : null}

      <Note>
        <strong style={{ color: "var(--text-secondary)" }}>
          Why there are no arrows between these nodes.
        </strong>{" "}
        A link from one chain to another is a supply relationship, and the desk
        will only draw one it can evidence.{" "}
        {exposure ? (
          <>
            Of <Num>{exposure.members}</Num> chain memberships in the taxonomy,{" "}
            <Num>{exposure.magnitude}</Num> carry a magnitude a company actually
            disclosed. That is not enough to draw a network, so this screen
            places the chains and stops.
          </>
        ) : (
          <>
            The evidence tally that would say how much of the taxonomy carries a
            disclosed magnitude did not load, so the count is withheld rather
            than guessed {DASH} but the refusal stands either way: arrows are
            drawn from disclosures, and none were read.
          </>
        )}{" "}
        Flow is modelled only where the structure is explicit, which is what the
        case funnels are for.
      </Note>
    </>
  );
}

function Legend({
  chains,
  hover,
  onHover,
}: {
  chains: Placed[];
  hover: Placed | null;
  onHover: (p: Placed | null) => void;
}) {
  return (
    <div
      style={{
        borderLeft: "1px solid var(--border-dim)",
        maxHeight: HEIGHT,
        overflowY: "auto",
        padding: "8px 0",
      }}
    >
      {LAYER_KEYS.map((L, li) => {
        const rows = chains
          .filter((c) => c.layer === L)
          .sort((a, b) => (b.revYoy as number) - (a.revYoy as number));
        if (rows.length === 0) return null;
        return (
          <div key={L}>
            <div
              style={{
                padding: "8px 10px 4px",
                fontFamily: MONO,
                fontSize: 9.5,
                letterSpacing: 1.2,
                textTransform: "uppercase",
                color: "var(--text-muted)",
              }}
            >
              {L} {MID} {LAYER_LABELS[L]}
            </div>
            {rows.map((c) => (
              <div
                key={c.chain}
                onMouseEnter={() => onHover(c)}
                onMouseLeave={() => onHover(null)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 7,
                  padding: "3px 10px",
                  cursor: "default",
                  background:
                    hover?.chain === c.chain
                      ? "var(--bg-panel-raised)"
                      : "transparent",
                }}
              >
                <span
                  aria-hidden
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: 4,
                    flex: "0 0 auto",
                    background: `var(${LAYER_TOKENS[li]})`,
                  }}
                />
                <span
                  style={{
                    flex: 1,
                    minWidth: 0,
                    fontSize: 11,
                    color: "var(--text-secondary)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {c.chain}
                </span>
                <span
                  style={{
                    fontFamily: MONO,
                    fontSize: 10.5,
                    color: "var(--text-muted)",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {sgn(c.revYoy, 0)}
                </span>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
