/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MeanReversionTiles } from "@/components/regime/MeanReversionTiles";

describe("MeanReversionTiles", () => {
  it("renders four tiles with values (including VIX Δ 3d)", () => {
    render(
      <MeanReversionTiles
        vrp={5.2}
        vixZscore={1.1}
        vixVix3mRatio={0.92}
        vixDelta3d={0.8}
      />,
    );
    expect(screen.getByTestId("meanrev-row")).not.toBeNull();
    expect(screen.getByTestId("meanrev-tile-VRP").textContent).toContain(
      "5.20",
    );
    expect(
      screen.getByTestId("meanrev-tile-VIX Z (30d)").textContent,
    ).toContain("1.10");
    expect(
      screen.getByTestId("meanrev-tile-VIX / VIX3M").textContent,
    ).toContain("0.920");
    // Positive delta renders with a leading "+" so direction is visible.
    expect(screen.getByTestId("meanrev-tile-VIX Δ (3d)").textContent).toContain(
      "+0.80",
    );
  });

  it("renders em-dash for null inputs", () => {
    render(
      <MeanReversionTiles
        vrp={null}
        vixZscore={null}
        vixVix3mRatio={null}
        vixDelta3d={null}
      />,
    );
    expect(screen.getByTestId("meanrev-tile-VRP").textContent).toContain("—");
    expect(screen.getByTestId("meanrev-tile-VIX Δ (3d)").textContent).toContain(
      "—",
    );
  });

  it("renders negative VIX delta with sign", () => {
    render(
      <MeanReversionTiles
        vrp={5.2}
        vixZscore={1.1}
        vixVix3mRatio={0.92}
        vixDelta3d={-1.5}
      />,
    );
    expect(screen.getByTestId("meanrev-tile-VIX Δ (3d)").textContent).toContain(
      "-1.50",
    );
  });
});
