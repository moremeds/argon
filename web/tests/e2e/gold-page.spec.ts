// Prereq: `uv run python -m uw_scan.worker.gold_warmup` must have written at
// least one gold_posture_daily row before this runs — otherwise the page
// renders the "not yet computed" placeholder instead of the cockpit.
import { expect, test } from "@playwright/test";

test.describe("GOLD COMPASS /macro/gold", () => {
  test("renders the five-tier cockpit when posture has been computed", async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });

    // Re-pointed in P6: `/gold` 308s here now (`gold-redirect.spec.ts` owns the redirect
    // itself). The cockpit is unchanged — this is a presentation move, and the whole
    // value of keeping this spec is that it would fail if it were not.
    await page.goto("/macro/gold");

    // The board's t5 heading. The "GOLD COMPASS" wordmark this used to anchor on was the
    // standalone page's lockup, and on the desk it said the same word as the tab bar one
    // line above it; the board opens t5 with `Gold` and a state pill. The wordmark is
    // still drawn on `/gold/replay/<date>`, and `goldCompassLayout.test.tsx` holds both
    // halves of that — lockup standalone, board heading on the desk.
    // `exact` matters: the gauge panel's own h2 is "TRANSMISSION GAUGE · GOLD ↔ DFII10",
    // which a substring match on "Gold" also selects.
    await expect(
      page.getByRole("heading", { name: "Gold", exact: true, level: 2 }),
    ).toBeVisible();
    await expect(page.getByTestId("macro-domain-gold")).toBeVisible();

    // The five regions are aria-labelled by GoldCompassLayout. KPI strip is
    // tier 1; lens 1/2/3 follow; correlation history is the last region (it
    // also held a lens-decomposition panel until that panel's data source was
    // found to be empty by construction).
    await expect(page.getByRole("region", { name: /kpi/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /lens 1/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /lens 2/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /lens 3/i })).toBeVisible();
    await expect(
      page.getByRole("region", { name: /correlation history/i }),
    ).toBeVisible();

    // Posture language: page must NOT contain sizing imperatives. Re-asserts
    // the runtime invariant that posture-lint enforces at build time.
    const body = (await page.textContent("body")) ?? "";
    expect(body.toLowerCase()).not.toMatch(/\bbuy\b/);
    expect(body.toLowerCase()).not.toMatch(/\bsell\b/);
    expect(body.toLowerCase()).not.toMatch(/\bposition size\b/);
    expect(body.toLowerCase()).not.toMatch(/\bpredicted return\b/);

    // It landed INSIDE the desk, and the tab bar says which tab. Without this the spec
    // would pass just as happily against a standalone page that still answered here.
    await expect(page.getByTestId("macro-tab-bar")).toBeVisible();
    await expect(page.getByTestId("macro-tab-gold")).toHaveAttribute(
      "aria-current",
      "page",
    );

    // The desk's own control is the only date picker on this tab, and it asks the
    // OBSERVATION-date question rather than the point-in-time one every other tab asks.
    // Two pickers here would be two questions over one answer, and the header's own
    // picker navigates off the desk.
    const control = page.getByTestId("macro-replay-control");
    await expect(control).toBeVisible();
    await expect(control).toHaveAttribute("data-replay-clock", "obs_date");
    await expect(page.getByLabel("REPLAY")).toHaveCount(0);

    // No client-side React errors during render.
    expect(consoleErrors.filter((m) => !/favicon/i.test(m))).toEqual([]);
  });
});
