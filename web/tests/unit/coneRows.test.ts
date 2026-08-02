import { describe, expect, it } from "vitest";

import { drawableRows } from "@/lib/regime/coneRows";

const row = (target_date: string) => ({ target_date });

describe("drawableRows", () => {
  it("keeps a normal five-horizon cone whole", () => {
    const rows = ["08-03", "08-04", "08-05", "08-06", "08-07"].map((d) =>
      row(`2026-${d}`),
    );
    expect(drawableRows(rows, "2026-07-31")).toHaveLength(5);
  });

  it("drops horizons the tape has already passed", () => {
    // Cone anchored 2026-07-30 but bars run to 08-04: the first two targets describe
    // sessions whose closes are known, so drawing a forecast there claims the past.
    const rows = ["08-03", "08-04", "08-05"].map((d) => row(`2026-${d}`));
    expect(drawableRows(rows, "2026-08-04").map((r) => r.target_date)).toEqual([
      "2026-08-05",
    ]);
  });

  it("drops a duplicate date the settle pass can produce", () => {
    // Anchor Friday 2026-07-31 with Monday 08-03 a holiday: weekday estimates are
    // 08-03..08-07, and once h=1 settles to the real Tuesday it carries 08-04 — the
    // same date h=2's unsettled estimate still holds.
    const rows = [
      row("2026-08-04"), // h=1, settled to the actual next trading day
      row("2026-08-04"), // h=2, still the weekday estimate
      row("2026-08-05"),
    ];
    expect(drawableRows(rows, "2026-07-31").map((r) => r.target_date)).toEqual([
      "2026-08-04",
      "2026-08-05",
    ]);
  });

  it("returns nothing when the whole cone is behind the tape", () => {
    const rows = ["07-28", "07-29"].map((d) => row(`2026-${d}`));
    expect(drawableRows(rows, "2026-08-04")).toEqual([]);
  });
});
