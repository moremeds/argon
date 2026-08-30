import { expect, test, type Page } from "@playwright/test";

/**
 * The rates desk under MC2 — now two tabs of the macro desk — in a real browser against
 * the real API.
 *
 * `/rates` 308s to `/macro/rates` (`next.config.mjs`), and the page it used to serve is
 * two pages now:
 *
 *   - `/macro/fed`   — `FedDesk`: the policy / rates STATE, the four published policy
 *                      paths, and the two publishers that plot (SEP dots, dealer path).
 *   - `/macro/rates` — `CurveDesk`: the traded curve and what moved it, with the legacy
 *                      rule scorecard quarantined inside "What this tab refuses".
 *
 * So every test below names the tab that owns its subject, through one of the two helpers.
 * A single shared helper is exactly what broke when the split landed: the state block and
 * the policy paths moved to `/macro/fed`, and the redirect kept delivering them to the
 * curve tab, where they no longer exist.
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

/** Tab 01 — Fed · Policy. Owns the state, the four lanes, and both path plots. */
async function fedTab(page: Page) {
  await page.goto("/macro/fed");
  await page.waitForLoadState("networkidle");
}

/** Tab 02 — Rates · Curve. Owns the traded curve and the quarantined legacy scorecard. */
async function curveTab(page: Page) {
  await page.goto("/macro/rates");
  await page.waitForLoadState("networkidle");
}

/**
 * Both desks render `DeskEmptyState` when no snapshot exists, and it draws NO tiers and
 * NO sections — so a structural assertion about either has no subject in that state.
 * This is the one skip both hierarchy tests need, and it is the pre-existing one.
 */
const NO_SNAPSHOT = /Rates (snapshot not computed|API unavailable)/;

test.describe("fed tab — evidence-first state", () => {
  test("shows a stored state or says none was computed, never a neutral stand-in", async ({
    page,
  }) => {
    await fedTab(page);
    if (
      (await page
        .getByRole("heading", {
          name: NO_SNAPSHOT,
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

  test("a state that exists never repeats its own title as an eyebrow", async ({
    page,
  }) => {
    await fedTab(page);
    const block = page.getByTestId("rates-state-block");
    if ((await block.count()) === 0) {
      test.skip(true, "no stored state in this environment");
    }
    // "Policy / Rates State" is the section heading. Printing it again one line
    // below spent the most valuable line on the page saying nothing new.
    const repeated = block.locator("text=/^policy \\/ rates state/i");
    await expect(repeated).toHaveCount(0);
  });
});

test.describe("curve tab — the quarantined legacy scorecard", () => {
  test("the legacy scorecard is labelled experimental and takes no stance without a score", async ({
    page,
  }) => {
    await curveTab(page);
    if ((await page.getByTestId("rates-scorecard").count()) === 0) {
      test.skip(true, "no rates snapshot in this environment");
    }

    // The scorecard survived the split, DEMOTED: §7 keeps it as the only thing an
    // operator can hold the Fed tab's state up against, but moves it inside the
    // refusal panel so nobody reads a number this desk does not answer with as the
    // answer. Asserting the containment is what stops a later PR from quietly
    // promoting it back into the desk's own chrome — the testids alone cannot tell
    // the difference between quarantined and reinstated.
    await expect(
      page.locator("#refuses").getByTestId("rates-scorecard"),
    ).toBeHidden();
    await page
      .locator("#refuses details")
      .getByText("Experimental legacy scorecard")
      .click();
    await expect(
      page.locator("#refuses").getByTestId("rates-scorecard"),
    ).toBeVisible();
    await expect(page.locator("#refuses")).toContainText(
      /what this tab refuses/i,
    );

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

test.describe("fed tab — policy paths", () => {
  test("renders four lanes and never merges them", async ({ page }) => {
    await fedTab(page);
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
    await fedTab(page);
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
    await fedTab(page);
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

/**
 * Information hierarchy, once per tab.
 *
 * This was ONE test asserting five tiers in one exact order, back when the desk was one
 * page. There is no five-tier page any more, and the honest replacement is not a softer
 * assertion — "at least one tier" would pass on a flat page with a stray heading, which
 * is the defect the original existed to catch. It is TWO exact assertions, because each
 * tab now has its own tier list and each list is short enough to write down.
 *
 * The split is also where the ordering claim gets its teeth back: the Fed tab must put
 * the verdict before the publishers that feed it, and the curve tab must put the traded
 * curve before the mechanics and the mechanics before the legacy score. Neither claim
 * survives being folded into one list.
 */
test.describe("desk information hierarchy", () => {
  test("the fed tab follows the board's exact panel order", async ({
    page,
  }) => {
    await fedTab(page);
    if ((await page.getByRole("heading", { name: NO_SNAPSHOT }).count()) > 0) {
      test.skip(true, "no rates snapshot in this environment");
    }

    const order = await page
      .locator("main [role='region'].panel")
      .evaluateAll((nodes) => nodes.map((node) => node.id));
    expect(order).toEqual([
      "paths",
      "market-implied",
      "dealer-plot",
      "sep-plot",
      "state",
      "policy",
      "events",
      "refuses",
    ]);
  });

  test("the curve tab follows the board's exact panel order", async ({
    page,
  }) => {
    await curveTab(page);
    if ((await page.getByRole("heading", { name: NO_SNAPSHOT }).count()) > 0) {
      test.skip(true, "no rates snapshot in this environment");
    }

    const order = await page
      .locator("main [role='region'].panel")
      .evaluateAll((nodes) => nodes.map((node) => node.id));
    expect(order).toEqual([
      "curve",
      "decomp",
      "decomp-cleveland",
      "decomp-attribution",
      "substate-supply",
      "substate-positioning",
      "substate-plumbing",
      "auctions",
      "refuses",
    ]);
  });
});

test.describe("fed tab — policy path plots", () => {
  test("the SEP block plots dots and still refuses to name a participant", async ({
    page,
  }) => {
    await fedTab(page);
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
    await fedTab(page);
    const block = page.locator("#dealer-plot");
    await expect(block).toBeVisible();

    if ((await block.getByTestId("dealer-path-missing").count()) > 0) {
      await expect(block.getByTestId("dealer-path-missing")).not.toBeEmpty();
      test.skip(true, "no dealer survey ingested in this environment");
    }

    // Exactly one CURRENT median. Earlier surveys are drawn beside it as their own
    // dated releases, so counting every polyline would have pinned the chart to the
    // one-survey design it replaced.
    await expect(block.getByTestId("dealer-path-median")).toHaveCount(1);
    // Either form is correct; what is refused is a plot that never says how many
    // dealers stand behind the far end of the path.
    await expect(block.getByTestId("dealer-path-note")).toContainText(
      /n=\d+ at every horizon|n varies by horizon, \d+–\d+/,
    );

    // Every prior series must be a SEPARATE dated release, never merged into the
    // current one -- the same rule that keeps the four publishers apart.
    const priors = block.getByTestId("dealer-path-median-prior");
    if ((await priors.count()) > 0) {
      await expect(block).toContainText(/remain separate releases/i);
      await expect(block).toContainText(/never averaged against the SEP/i);
      await expect(block).toContainText(/earlier survey/i);
    }
  });

  test("the two publishers are plotted in separate blocks, never on one axis", async ({
    page,
  }) => {
    // Structural, not textual: one <svg> each, in their own sections. A shared frame
    // would read as a comparison this desk refuses to draw.
    await fedTab(page);

    await expect(page.locator("#sep-plot svg")).toHaveCount(1);
    await expect(page.locator("#dealer-plot svg")).toHaveCount(1);
    await expect(page.locator("#sep-plot #dealer-plot")).toHaveCount(0);
  });
});

/**
 * The three things §7 settled, as an outer guard.
 *
 * `SummaryStances` / `StanceCard` / `stanceDescription` are deleted and
 * `snapshot.synthesis` is no longer rendered — both because a refusal describes and
 * never prescribes (§9 invariant 7), and the stance cards printed the literal words
 * `BUY` and `SELL` in a watermark. This is the same ban `gold-page.spec.ts:38-41`
 * enforces on the gold desk, applied to the two tabs that inherited the rates page.
 *
 * These are the two tests in this file that need NO data: an empty desk has no stance
 * cards and no synthesis either, so they hold in every state rather than skipping.
 */
test.describe("the desk prescribes nothing", () => {
  test("the fed tab never says BUY or SELL", async ({ page }) => {
    await fedTab(page);

    const body = (await page.textContent("body")) ?? "";
    expect(body.toLowerCase()).not.toMatch(/\bbuy\b/);
    expect(body.toLowerCase()).not.toMatch(/\bsell\b/);

    // The two components that carried those words, by the anchors they rendered.
    await expect(page.getByTestId("legacy-stance-grid")).toHaveCount(0);
    await expect(page.locator("#synthesis")).toHaveCount(0);
  });

  test("the curve tab never says BUY or SELL outside the quarantine", async ({
    page,
  }) => {
    await curveTab(page);

    // WHY THIS IS SCOPED AND THE FED TAB'S IS NOT. `RatesScorecard` survived the split
    // (§7: kept, demoted into "What this tab refuses"), and its `duration_stance` is a
    // `Literal["BUY", "SELL", "NEUTRAL", "UNKNOWN"]` — `rates/scorecard.py:225-227`
    // returns the first two whenever the composite clears ±0.25 with enough coverage,
    // and `RatesScorecard.tsx:57-59` prints it verbatim as "<stance> duration". So a
    // whole-body ban here is not a strict gate, it is a gate that fires on legitimate
    // data the settlement deliberately kept. The honest form is the settlement's own
    // sentence: the desk's CHROME prescribes nothing, and the one artifact that still
    // carries a stance is fenced inside `#refuses` and labelled a legacy artifact.
    //
    // A missing `#refuses` makes this assertion STRICTER (nothing is removed), not
    // weaker, so the carve-out cannot evaporate the check — and the anchor below
    // proves it did not swallow the page either.
    const outsideQuarantine = await page.evaluate(() => {
      const clone = document.body.cloneNode(true) as HTMLElement;
      clone.querySelector("#refuses")?.remove();
      return clone.textContent ?? "";
    });

    // Non-vacuity: something outside the quarantine must survive the carve-out, or this
    // assertion passes on an empty string. It used to be the "US Rates Factor Desk"
    // lockup, which the board replaced with its own `.sec-title` — and the replacement
    // is not a drop-in, because the populated tab says "Rates · Curve" while the empty
    // state still says the old name in `DeskEmptyState`'s eyebrow. The desk's TAB BAR is
    // the anchor that holds in both: it lives in `app/macro/layout.tsx`, renders the same
    // registry label either way, and is never inside `#refuses`.
    expect(outsideQuarantine).toContain("Rates · Curve");
    expect(outsideQuarantine.toLowerCase()).not.toMatch(/\bbuy\b/);
    expect(outsideQuarantine.toLowerCase()).not.toMatch(/\bsell\b/);

    // The two components that carried those words, by the anchors they rendered.
    // Neither is inside the quarantine, so these are unscoped.
    await expect(page.getByTestId("legacy-stance-grid")).toHaveCount(0);
    await expect(page.locator("#synthesis")).toHaveCount(0);
  });
});
