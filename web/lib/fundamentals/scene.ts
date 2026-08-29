/**
 * A tiny hand-rolled 3D scene for canvas 2D — projection, drag, hit-test.
 *
 * WHY 3D AT ALL, AND WHY NOT A LIBRARY
 * -------------------------------------
 * A PM needs three facts about a chain at once — how fast it grows, how well
 * it is paid, and where it sits in the stack — and any two of those on a flat
 * chart hide the third. The third axis is the deliverable, not decoration.
 *
 * `web/CLAUDE.md` bans chart libraries (two documented lightweight-charts
 * exceptions, both for dated price panes). None of them projects a rotatable
 * scene, so this is ~120 lines of perspective projection rather than a third
 * exception: yaw/pitch rotation, a divide for perspective, and a nearest-hit
 * scan. No dependency, and the whole thing is readable in one screen.
 *
 * The projection is Y-up: `yaw` spins about Y, `pitch` tips the scene toward
 * the viewer, and `dist` sets how strong the perspective divide is. Hit
 * testing is 2D on the PROJECTED points, so it stays correct under rotation
 * without any inverse transform.
 */

export interface Projected {
  u: number;
  v: number;
  /** Perspective factor — multiply a radius by this so far things shrink. */
  k: number;
  /** Depth AFTER rotation. Painter's algorithm sorts on this, descending. */
  z: number;
}

export interface HitTarget<T> {
  u: number;
  v: number;
  r: number;
  data: T;
}

export interface SceneState<T> {
  yaw: number;
  pitch: number;
  /** Canvas CSS width / height in px — never the backing-store size. */
  W: number;
  H: number;
  /** World-unit -> px scale, recomputed on resize. */
  unit: number;
  spin: boolean;
  hover: T | null;
  hit: HitTarget<T>[];
  project(x: number, y: number, z: number): Projected;
}

export interface SceneOptions<T> {
  yaw: number;
  pitch: number;
  /** Perspective distance. Larger is flatter. */
  dist?: number;
  /** World-unit scale as a fraction of the smaller canvas dimension. */
  zoom?: number;
  /** Horizontal / vertical centre as a fraction of the canvas. */
  cxf?: number;
  cyf?: number;
  spin?: boolean;
  draw(ctx: CanvasRenderingContext2D, s: SceneState<T>): void;
  onHover?(data: T | null): void;
  onSpinChange?(spinning: boolean): void;
  /** Called after this scene's own rotation changes, to drive siblings. */
  onRotate?(yaw: number, pitch: number): void;
}

export interface SceneHandle<T> {
  state: SceneState<T>;
  draw(): void;
  /** Ease toward a target orientation; cancels auto-spin. */
  goTo(yaw: number, pitch: number): void;
  /** Adopt another scene's orientation without re-emitting `onRotate`. */
  setRotation(yaw: number, pitch: number): void;
  setSpin(on: boolean): void;
  setHover(data: T | null): void;
  resize(): void;
  destroy(): void;
}

const SPIN_RATE = 0.0028;
const EASE = 0.14;

export function createScene<T>(
  canvas: HTMLCanvasElement,
  opts: SceneOptions<T>,
): SceneHandle<T> {
  const context = canvas.getContext("2d");
  if (context === null) throw new Error("canvas 2d context unavailable");
  // Bound to a fresh const so the null-narrowing survives into the closures
  // below — TypeScript widens a `let`/outer binding back to `| null` inside a
  // callback, and every draw path here is a callback.
  const ctx: CanvasRenderingContext2D = context;

  const reduceMotion =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let targetYaw = opts.yaw;
  let targetPitch = opts.pitch;
  let dpr = 1;
  let frame = 0;
  let disposed = false;

  const state: SceneState<T> = {
    yaw: opts.yaw,
    pitch: opts.pitch,
    W: 0,
    H: 0,
    unit: 0,
    spin: reduceMotion ? false : !!opts.spin,
    hover: null,
    hit: [],
    project(x, y, z) {
      const cy = Math.cos(state.yaw);
      const sy = Math.sin(state.yaw);
      const rx = x * cy - z * sy;
      const rz = x * sy + z * cy;
      const cp = Math.cos(state.pitch);
      const sp = Math.sin(state.pitch);
      const ry = y * cp - rz * sp;
      const depth = y * sp + rz * cp;
      const dist = opts.dist ?? 3.6;
      // The divide IS the perspective. `dist + depth` can never reach zero for
      // a scene bounded by |depth| < 1.5 and dist >= 3.
      const k = dist / (dist + depth);
      return {
        u: state.W * (opts.cxf ?? 0.5) + rx * k * state.unit,
        v: state.H * (opts.cyf ?? 0.5) - ry * k * state.unit,
        k,
        z: depth,
      };
    },
  };

  function measure() {
    dpr = Math.min(2, window.devicePixelRatio || 1);
    state.W = canvas.clientWidth || 640;
    state.H = canvas.clientHeight || 400;
    canvas.width = Math.round(state.W * dpr);
    canvas.height = Math.round(state.H * dpr);
    // The SMALLER dimension, not the width. A scene scaled off width alone
    // clips top and bottom the moment the canvas is wider than it is tall,
    // which is every desktop layout: the chain map's L4 and L5 planes drew
    // above the frame, so two of five taxonomy layers were invisible while
    // the legend still listed them. And the bound is tighter than the world
    // extent suggests — perspective magnifies the FAR corner of a plane
    // (k > 1 behind the centre), so a plane at y = 0.85 reaches ~1.7 units
    // up the screen, not 0.85. The zoom constants are set against that.
    state.unit = Math.min(state.W, state.H) * (opts.zoom ?? 0.3);
  }

  function draw() {
    if (disposed) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, state.W, state.H);
    // Rebuilt every frame: a hit target is a PROJECTED position, so a stale
    // one would answer for an orientation the reader can no longer see.
    state.hit = [];
    opts.draw(ctx, state);
  }

  function tick() {
    frame = 0;
    let moving = false;
    if (state.spin) {
      state.yaw += SPIN_RATE;
      targetYaw = state.yaw;
      moving = true;
      opts.onRotate?.(state.yaw, state.pitch);
    } else {
      const dy = targetYaw - state.yaw;
      const dp = targetPitch - state.pitch;
      if (Math.abs(dy) > 1e-4 || Math.abs(dp) > 1e-4) {
        state.yaw += dy * EASE;
        state.pitch += dp * EASE;
        moving = true;
      }
    }
    draw();
    if (moving) run();
  }

  function run() {
    if (!frame && !disposed) frame = requestAnimationFrame(tick);
  }

  let drag: { x: number; y: number } | null = null;

  function onPointerDown(e: PointerEvent) {
    drag = { x: e.clientX, y: e.clientY };
    if (state.spin) {
      state.spin = false;
      opts.onSpinChange?.(false);
    }
    canvas.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e: PointerEvent) {
    if (drag) {
      state.yaw += (e.clientX - drag.x) * 0.009;
      // Pitch is clamped: past ~1.35rad the planes collapse edge-on and the
      // scene reads as a smear rather than as depth.
      state.pitch = Math.max(
        -0.1,
        Math.min(1.35, state.pitch + (e.clientY - drag.y) * 0.006),
      );
      targetYaw = state.yaw;
      targetPitch = state.pitch;
      drag = { x: e.clientX, y: e.clientY };
      opts.onRotate?.(state.yaw, state.pitch);
      run();
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    let best: T | null = null;
    let bestDist = Infinity;
    for (const h of state.hit) {
      const d = Math.hypot(h.u - mx, h.v - my);
      if (d < h.r + 7 && d < bestDist) {
        bestDist = d;
        best = h.data;
      }
    }
    if (best !== state.hover) {
      state.hover = best;
      opts.onHover?.(best);
      run();
    }
  }

  function endDrag(e: PointerEvent) {
    if (!drag) return;
    drag = null;
    try {
      canvas.releasePointerCapture(e.pointerId);
    } catch {
      // The pointer may already be released (capture lost on leave); the
      // throw carries no information the caller can act on.
    }
  }

  function onPointerLeave() {
    if (state.hover !== null) {
      state.hover = null;
      opts.onHover?.(null);
      run();
    }
  }

  canvas.addEventListener("pointerdown", onPointerDown);
  canvas.addEventListener("pointermove", onPointerMove);
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener("pointerleave", onPointerLeave);

  measure();
  draw();
  if (state.spin) run();

  return {
    state,
    draw,
    goTo(yaw, pitch) {
      targetYaw = yaw;
      targetPitch = pitch;
      state.spin = false;
      run();
    },
    setRotation(yaw, pitch) {
      state.yaw = yaw;
      state.pitch = pitch;
      targetYaw = yaw;
      targetPitch = pitch;
      draw();
    },
    setSpin(on) {
      state.spin = reduceMotion ? false : on;
      if (state.spin) run();
      else draw();
    },
    setHover(data) {
      state.hover = data;
      draw();
    },
    resize() {
      measure();
      draw();
    },
    destroy() {
      disposed = true;
      if (frame) cancelAnimationFrame(frame);
      canvas.removeEventListener("pointerdown", onPointerDown);
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerup", endDrag);
      canvas.removeEventListener("pointercancel", endDrag);
      canvas.removeEventListener("pointerleave", onPointerLeave);
    },
  };
}
