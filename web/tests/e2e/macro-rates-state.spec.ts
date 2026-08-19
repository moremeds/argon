import { expect, test } from "@playwright/test";

/**
 * The /rates desk under MC2, in a real browser against the real API.
 *
 * These assertions are deliberately written to hold in *every* data state this
 * environment can be in — with a computed state or without one, with four policy
 * paths or with none. That is the point of the milestone: the failure modes it exists
 * to prevent (a neutral verdict manufactured from missing data, a merged Fed path)
 * are exactly the ones that only appear when data is absent, so a spec that skipped
 * itself on an empty database would skip the bugs.
 *
 * Where a populated variant genuinely cannot be asserted without one, the test skips
 * and says so rather than passing vacuously.
 */

async function ratesPage(page: import("@playwright/test").Page) {
  await page.goto("/rates");
  await page.waitForLoadState("networkidle");
}

test.describe("rates desk — evidence-first state", () => {
  test("shows a stored state or says none was computed, never a neutral stand-in", async ({
    page,
  }) => {
    await ratesPage(page);
    if (
      (await page
        .getByRole("heading", {
          name: /Rates (snapshot not computed|API unavailable)/,
        })
        .count()) > 0
    ) {
      test.skip(true, "no rates snapshot in this environment");
    }

    const block = page.getByTestId("rates-state-block");
    const missing = page.getByTestId("rates-state-missing");
    const hasState = (await block.count()) > 0;
    expect(hasState || (await missing.count()) > 0).toBe(true);

    if (hasState) {
      // A state that exists must name what it is, which way, and how sure.
      await expect(page.getByTestId("rates-state-label")).not.toBeEmpty();
      await expect(page.getByTestId("rates-state-direction")).not.toBeEmpty();
      await expect(page.getByTestId("rates-state-confidence")).not.toHaveText(
        "n/a",
      );
      await expect(page.getByTestId("rates-state-freshness")).toHaveText(
        /Fresh|Stale · [\d.]+h since computed/,
      );
    } else {
      await expect(missing).toContainText("Not computed");
      // The absence of a state must not read as a view about rates.
      await expect(missing).not.toContainText(/NEUTRAL|EASING|TIGHTENING/);
    }
  });

  test("the legacy scorecard is labelled experimental and takes no stance without a score", async ({
    page,
  }) => {
    await ratesPage(page);
    if ((await page.getByTestId("rates-scorecard").count()) === 0) {
      test.skip(true, "no rates snapshot in this environment");
    }

    await expect(page.getByTestId("scorecard-legacy-banner")).toContainText(
      /experimental legacy/i,
    );

    const score = await page.getByTestId("duration-score").textContent();
    if (score?.trim() === "n/a") {
      // No composite means no stance. The bug this replaces printed "NEUTRAL
      // duration" off a zero the client invented.
      await expect(page.getByTestId("duration-stance")).toContainText(
        "UNKNOWN",
      );
      await expect(page.getByTestId("scorecard-no-score")).toContainText(
        "No duration stance is taken",
      );
    }
  });
});

test.describe("rates desk — policy paths", () => {
  test("renders four lanes and never merges them", async ({ page }) => {
    await ratesPage(page);
    if ((await page.getByTestId("policy-path-comparison").count()) === 0) {
      await expect(page.getByTestId("policy-paths-missing")).toContainText(
        /unavailable/i,
      );
      test.skip(true, "no policy comparison in this environment");
    }

    const lanes = page.locator('[data-testid^="policy-path-lane-"]');
    await expect(lanes).toHaveCount(4);
    for (const kind of [
      "actual",
      "committee_projection",
      "dealer_expectations",
      "market_implied",
    ]) {
      await expect(page.getByTestId(`policy-path-lane-${kind}`)).toBeVisible();
    }
    await expect(page.getByTestId("policy-path-comparison")).toContainText(
      /never averaged/i,
    );
  });

  test("every lane either carries a source and release date or states why it is empty", async ({
    page,
  }) => {
    await ratesPage(page);
    if ((await page.getByTestId("policy-path-comparison").count()) === 0) {
      test.skip(true, "no policy comparison in this environment");
    }

    const lanes = page.locator('[data-testid^="policy-path-lane-"]');
    for (let i = 0; i < (await lanes.count()); i += 1) {
      const lane = lanes.nth(i);
      const status = await lane.getAttribute("data-path-status");
      if (status === "available") {
        await expect(lane).toContainText(/released \d{4}-\d{2}-\d{2}/);
      } else {
        // An empty lane is a sentence, not a blank or a zero.
        await expect(lane).not.toContainText(/released/);
        expect((await lane.textContent())?.trim().length ?? 0).toBeGreaterThan(
          0,
        );
      }
    }
  });

  test("an SEP lane never attributes a dot to a named participant", async ({
    page,
  }) => {
    await ratesPage(page);
    const sep = page.getByTestId("policy-path-lane-committee_projection");
    if ((await sep.count()) === 0) {
      test.skip(true, "no policy comparison in this environment");
    }
    if ((await sep.getAttribute("data-path-status")) !== "available") {
      test.skip(true, "no SEP release ingested in this environment");
    }

    await expect(page.getByTestId("sep-anonymity-note")).toContainText(
      /dots are anonymous/i,
    );
    await expect(sep).not.toContainText(/chair|powell/i);
  });
});

test.describe("rates desk — replay", () => {
  test("an instant nobody answered for is a 404, not an invented state", async ({
    request,
  }) => {
    // Through the same origin the page uses, so the Next rewrite is in the path.
    const response = await request.get("/api/macro/rates?as_of=2000-01-01");

    expect(response.status()).toBe(404);
    expect(await response.text()).toContain(
      "no policy_rates state has been computed",
    );
  });

  test("a replayed state stands only on evidence available by the instant asked for", async ({
    request,
  }) => {
    const latest = await request.get("/api/macro/rates");
    if (latest.status() === 404) {
      test.skip(true, "no policy_rates state computed in this environment");
    }
    expect(latest.status()).toBe(200);

    const body = await latest.json();
    const asOf = Date.parse(body.as_of);
    expect(Number.isNaN(asOf)).toBe(false);
    for (const item of body.evidence ?? []) {
      expect(Date.parse(item.available_at)).toBeLessThanOrEqual(asOf);
    }

    // Replaying the same instant must return the same stored answer, not a fresh
    // computation of what we would say about it today.
    const replay = await request.get(
      `/api/macro/rates?as_of_ts=${encodeURIComponent(body.as_of)}`,
    );
    expect(replay.status()).toBe(200);
    const replayed = await replay.json();
    expect(replayed.inputs_hash).toBe(body.inputs_hash);
    expect(replayed.state).toBe(body.state);
    expect(replayed.computed_at).toBe(body.computed_at);
  });

  test("a state nobody has recomputed is labelled stale rather than dressed as current", async ({
    request,
  }) => {
    const latest = await request.get("/api/macro/rates");
    if (latest.status() === 404) {
      test.skip(true, "no policy_rates state computed in this environment");
    }
    const body = await latest.json();

    // Four days after the answered instant, nothing has revisited it.
    const later = new Date(
      Date.parse(body.as_of) + 96 * 3600 * 1000,
    ).toISOString();
    const stale = await request.get(
      `/api/macro/rates?as_of_ts=${encodeURIComponent(later)}`,
    );

    expect(stale.status()).toBe(200);
    const staleBody = await stale.json();
    expect(staleBody.freshness).toBe("stale");
    expect(staleBody.age_hours).toBeGreaterThanOrEqual(96);
    // Still the honest answer to the question asked.
    expect(staleBody.state).toBe(body.state);
  });
});

test.describe("rates desk — policy path plots", () => {
  test("the SEP block plots dots and still refuses to name a participant", async ({
    page,
  }) => {
    await ratesPage(page);
    const block = page.locator("#sep-plot");
    await expect(block).toBeVisible();

    if ((await block.getByTestId("sep-dot-plot-missing").count()) > 0) {
      // An absent release is an allowed state; an absent SENTENCE is not.
      await expect(block.getByTestId("sep-dot-plot-missing")).not.toBeEmpty();
      test.skip(true, "no SEP release ingested in this environment");
    }

    await expect(block.locator("svg circle").first()).toBeVisible();
    expect(await block.locator("svg circle").count()).toBeGreaterThan(1);
    await expect(block.getByTestId("sep-plot-anonymity-note")).toContainText(
      /anonymous/i,
    );
    await expect(block).not.toContainText(/chair|powell/i);
  });

  test("the dealer block plots a path with its dispersion band", async ({
    page,
  }) => {
    await ratesPage(page);
    const block = page.locator("#dealer-plot");
    await expect(block).toBeVisible();

    if ((await block.getByTestId("dealer-path-missing").count()) > 0) {
      await expect(block.getByTestId("dealer-path-missing")).not.toBeEmpty();
      test.skip(true, "no dealer survey ingested in this environment");
    }

    await expect(block.locator("svg polyline")).toHaveCount(1);
    // Either form is correct; what is refused is a plot that never says how many
    // dealers stand behind the far end of the path.
    await expect(block.getByTestId("dealer-path-note")).toContainText(
      /n=\d+ at every horizon|n varies by horizon, \d+–\d+/,
    );
  });

  test("the two publishers are plotted in separate blocks, never on one axis", async ({
    page,
  }) => {
    // Structural, not textual: one <svg> each, in their own sections. A shared frame
    // would read as a comparison this desk refuses to draw.
    await ratesPage(page);

    await expect(page.locator("#sep-plot svg")).toHaveCount(1);
    await expect(page.locator("#dealer-plot svg")).toHaveCount(1);
    await expect(page.locator("#sep-plot #dealer-plot")).toHaveCount(0);
  });
});
