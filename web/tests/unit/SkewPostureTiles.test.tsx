import { describe, expect, it } from "vitest";

import { deviationColor } from "@/components/stock/panels/SkewPostureTiles";

describe("deviationColor", () => {
  it("maps RICH/CHEAP/NORMAL to tokens", () => {
    expect(deviationColor("RICH")).toBe("var(--warning)");
    expect(deviationColor("CHEAP")).toBe("var(--positive)");
    expect(deviationColor("NORMAL")).toBe("var(--text-primary)");
  });
});
