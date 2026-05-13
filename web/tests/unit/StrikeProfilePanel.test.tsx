import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StrikeProfilePanel } from "@/components/stock/panels/StrikeProfilePanel";

const ROWS = [
  {
    expiry: "2026-06-19",
    strike: "170",
    call_volume: 100,
    put_volume: 200,
    call_oi: 1000,
    put_oi: 2000,
  },
  {
    expiry: "2026-06-19",
    strike: "180",
    call_volume: 500,
    put_volume: 100,
    call_oi: 5000,
    put_oi: 1000,
  },
  {
    expiry: "2026-06-19",
    strike: "190",
    call_volume: 300,
    put_volume: 50,
    call_oi: 3000,
    put_oi: 500,
  },
  {
    expiry: "2026-09-18",
    strike: "180",
    call_volume: 200,
    put_volume: 50,
    call_oi: 2000,
    put_oi: 500,
  },
];

describe("StrikeProfilePanel", () => {
  it("computes ITM/OTM bucket sums for calls and puts (volume variant)", () => {
    render(
      <StrikeProfilePanel
        title="VOLUME BY STRIKE"
        metric="volume"
        rows={ROWS as never}
        selectedExpiries={["2026-06-19"]}
        strikeRangePct={0.3}
        spot={180}
      />,
    );
    // Calls: ITM (strike < 180) = 170 → 100; OTM (≥180) = 500 + 300 = 800
    expect(screen.getByTestId("calls-itm").textContent).toBe("100");
    expect(screen.getByTestId("calls-otm").textContent).toBe("800");
    // Puts: ITM (strike > 180) = 190 → 50; OTM (≤180) = 200 + 100 = 300
    expect(screen.getByTestId("puts-itm").textContent).toBe("50");
    expect(screen.getByTestId("puts-otm").textContent).toBe("300");
  });

  it("uses oi columns when metric='oi'", () => {
    render(
      <StrikeProfilePanel
        title="OI BY STRIKE"
        metric="oi"
        rows={ROWS as never}
        selectedExpiries={["2026-06-19"]}
        strikeRangePct={0.3}
        spot={180}
      />,
    );
    // OTM calls OI = 5000 + 3000 = 8000
    expect(screen.getByTestId("calls-otm").textContent).toBe("8000");
  });

  it("filters by selected expiries", () => {
    render(
      <StrikeProfilePanel
        title="VOLUME BY STRIKE"
        metric="volume"
        rows={ROWS as never}
        selectedExpiries={["2026-09-18"]}
        strikeRangePct={0.3}
        spot={180}
      />,
    );
    // Only 1 row matches (strike 180 == spot → OTM for both).
    expect(screen.getByTestId("calls-otm").textContent).toBe("200");
    expect(screen.getByTestId("puts-otm").textContent).toBe("50");
    expect(screen.getByTestId("calls-itm").textContent).toBe("0");
    expect(screen.getByTestId("puts-itm").textContent).toBe("0");
  });

  it("drops strikes outside the strike-range filter", () => {
    render(
      <StrikeProfilePanel
        title="VOLUME BY STRIKE"
        metric="volume"
        rows={ROWS as never}
        selectedExpiries={["2026-06-19"]}
        strikeRangePct={0.05} // ±5% of 180 → 171..189; only strike 180 qualifies
        spot={180}
      />,
    );
    expect(screen.getByTestId("calls-otm").textContent).toBe("500");
    expect(screen.getByTestId("puts-otm").textContent).toBe("100");
  });
});
