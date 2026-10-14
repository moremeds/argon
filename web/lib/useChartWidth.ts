"use client";

import { useEffect, useState } from "react";

/**
 * Measured width for a width-stretched SVG chart. `.board .chart svg` is
 * `width: 100%; height: auto`, so a fixed viewBox stretches its internal
 * coordinate system — text included — by `rendered px / viewBox units`. Drawing
 * with `viewBox="0 0 <measured> <H>"` makes one user unit one CSS pixel, so the
 * designed font sizes render at face value at every column width.
 *
 * House pattern from `CanaryScoreChart`: observe the box, take an initial
 * `getBoundingClientRect` measure, disconnect on unmount. The ref is a callback
 * (state) rather than a `useRef` object so a chart whose `<svg>` mounts only
 * when its data arrives still gets measured — a mount-time read would have run
 * before the element existed and pinned the fallback forever.
 *
 * Returns `fallback` until the box is measured, and permanently when
 * `ResizeObserver` is undefined (jsdom), so SSR and vitest keep the fallback
 * geometry. Width is rounded to whole px; a 0 reading is ignored.
 */
export function useChartWidth<T extends Element = HTMLDivElement>(
  fallback: number,
): [(el: T | null) => void, number] {
  const [el, setEl] = useState<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = (w: number) => {
      const px = Math.round(w);
      if (px > 0) setWidth(px);
    };
    const ro = new ResizeObserver((entries) => {
      const e = entries[0];
      if (e) measure(e.contentRect.width);
    });
    ro.observe(el);
    measure(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, [el]);
  return [setEl, width];
}
