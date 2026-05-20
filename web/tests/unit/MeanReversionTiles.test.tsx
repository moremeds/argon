/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MeanReversionTiles } from "@/components/regime/MeanReversionTiles";

describe("MeanReversionTiles", () => {
  it("renders three tiles with values", () => {
    render(
      <MeanReversionTiles vrp={5.2} vixZscore={1.1} vixVix3mRatio={0.92} />,
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
  });

  it("renders em-dash for null inputs", () => {
    render(
      <MeanReversionTiles vrp={null} vixZscore={null} vixVix3mRatio={null} />,
    );
    expect(screen.getByTestId("meanrev-tile-VRP").textContent).toContain("—");
  });
});
