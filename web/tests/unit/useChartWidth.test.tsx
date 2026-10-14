import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useChartWidth } from "@/lib/useChartWidth";

function Probe({ fallback }: { fallback: number }) {
  const [ref, width] = useChartWidth(fallback);
  return <div ref={ref} data-testid="box" data-width={width} />;
}

describe("useChartWidth", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("keeps the fallback width when ResizeObserver is undefined (jsdom)", () => {
    vi.stubGlobal("ResizeObserver", undefined);
    render(<Probe fallback={620} />);
    expect(screen.getByTestId("box").dataset.width).toBe("620");
  });

  it("adopts the measured width rounded to whole px, ignoring 0", () => {
    let notify: ((width: number) => void) | undefined;
    const observed: Element[] = [];
    class FakeResizeObserver {
      constructor(cb: ResizeObserverCallback) {
        notify = (width: number) =>
          cb(
            [{ contentRect: { width } } as ResizeObserverEntry],
            this as unknown as ResizeObserver,
          );
      }
      observe(el: Element) {
        observed.push(el);
      }
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);

    render(<Probe fallback={620} />);
    const box = screen.getByTestId("box");
    expect(observed).toHaveLength(1);
    // jsdom's getBoundingClientRect is 0 — ignored, so the fallback stands.
    expect(box.dataset.width).toBe("620");

    act(() => notify!(481.6));
    expect(box.dataset.width).toBe("482");
    act(() => notify!(0));
    expect(box.dataset.width).toBe("482");
  });
});
