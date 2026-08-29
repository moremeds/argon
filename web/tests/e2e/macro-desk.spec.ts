import { expect, test, type Page } from "@playwright/test";

/**
 * The macro desk shell, in a real browser.
 *
 * This file closes the gap §9 of `docs/superpowers/plans/2026-08-27-macro-desk-page-port.md`
 * recorded: sweeping every `page.goto(` under `web/tests/e2e/` found NO spec that
 * navigates to `/macro`. The closest were `/rates` and `/gold`, and only API requests
 * reached `/api/macro/*` — so the desk's own routes had no browser coverage at all while
 * the port was about to start moving them.
 *
 * What it holds, in order of how expensive the regression would be:
 *
 *  1. The registry identity at the HTTP level. `tests/unit/macroTabBar.test.tsx` already
 *     asserts it at the RENDER level — one link per `VALID_TABS` entry and nothing else.
 *     That test cannot know whether those hrefs resolve, because it never leaves jsdom.
 *     This one navigates each rendered link and checks the route exists. §8's rule is
 *     "no PR may ship a link to a route that does not exist"; a render-level assertion
 *     proves the bar and the registry agree, and only a navigation proves the registry
 *     and the router agree.
 *  2. The route guard's other direction — an unregistered slug 404s rather than
 *     rendering an empty shell.
 *  3. `/macro` redirects into tab 00 and the four domain cards are still reachable. This
 *     is the one that looks redundant and is not. Through P2-P4 it asserted the opposite
 *     — that `/macro` still rendered the cards itself — because §8 required
 *     `app/macro/page.tsx` be left ALONE until P5, precisely so `/macro` never 404'd
 *     while the bar grew from one tab to nine. P5 is the PR that may flip it, and the
 *     assertion flips WITH it rather than being deleted: the thing being protected was
 *     never "this page renders cards", it was "`/macro` is never a dead end and the cards
 *     are never orphaned", which is exactly what the new form checks.
 *
 * Deliberately NOT here: the `/rates` and `/gold` redirects, owned by
 * `rates-redirect.spec.ts` (P3) and `gold-redirect.spec.ts` (P6). What each slice DOES
 * change here is the walk's subject — the registry grew from one tab to three in P3 and to
 * six in P6, so the non-vacuity anchor below names all six rather than `notes` alone.
 */

/** Console-error collector, matching `gold-page.spec.ts:10-13` and `:44`. */
function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  return errors;
}

/** The favicon 404 is chrome noise, not the page's doing — same filter as `gold-page.spec.ts:44`. */
function realErrors(errors: string[]): string[] {
  return errors.filter((message) => !/favicon/i.test(message));
}

test.describe("macro desk shell", () => {
  test("every tab stays fully visible with no horizontal scroll", async ({
    page,
  }) => {
    const routes = [
      "overview",
      "fed",
      "rates",
      "inflation",
      "usd",
      "gold",
      "energy",
      "factors",
      "notes",
    ];

    for (const width of [1280, 1440, 1660]) {
      await page.setViewportSize({ width, height: 900 });
      for (const route of routes) {
        await page.goto(`/macro/${route}`);
        await page.waitForLoadState("networkidle");

        const overflow = await page.evaluate(() => {
          const visible = (element: Element) =>
            element instanceof HTMLElement &&
            element.getClientRects().length > 0 &&
            !element.closest(".sr-only, details:not([open]) > :not(summary)");
          return [...document.querySelectorAll("*")]
            .filter(visible)
            .filter((element) => element.scrollWidth > element.clientWidth + 1)
            .map((element) => ({
              tag: element.tagName,
              className: element.getAttribute("class") ?? "",
              testId: element.getAttribute("data-testid") ?? "",
              clientWidth: element.clientWidth,
              scrollWidth: element.scrollWidth,
            }));
        });

        expect(overflow, `${route} overflowed at ${width}px`).toEqual([]);
      }
    }
  });

  test("operator copy contains no implementation identifiers or review badges", async ({
    page,
  }) => {
    const routes = [
      "overview",
      "fed",
      "rates",
      "inflation",
      "usd",
      "gold",
      "energy",
      "factors",
      "notes",
    ];

    for (const route of routes) {
      await page.goto(`/macro/${route}`);
      await page.waitForLoadState("networkidle");

      const presentation = await page.evaluate(() => {
        const main = document.querySelector("main.macro-desk-main");
        const walker = document.createTreeWalker(
          main ?? document.body,
          NodeFilter.SHOW_TEXT,
          {
            acceptNode(node) {
              const parent = node.parentElement;
              if (!parent || !node.textContent?.trim())
                return NodeFilter.FILTER_REJECT;
              if (
                parent.closest(
                  "details:not([open]), .sr-only, script, style",
                ) || parent.getClientRects().length === 0
              )
                return NodeFilter.FILTER_REJECT;
              return NodeFilter.FILTER_ACCEPT;
            },
          },
        );
        let text = "";
        while (walker.nextNode()) text += ` ${walker.currentNode.textContent}`;
        return {
          text: text.replace(/\s+/g, " ").trim(),
          standfirstLengths: [...(main?.querySelectorAll(".sec-sub") ?? [])]
            .filter((element) => element.getClientRects().length > 0)
            .map((element) => (element.textContent ?? "").trim().length),
          visibleQuestionChips: [...
            (main?.querySelectorAll(".tag.q") ?? []),
          ].filter((element) => element.getClientRects().length > 0).length,
        };
      });

      expect(
        presentation.text.match(/\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b/g) ?? [],
        `${route} exposes variable-shaped copy`,
      ).toEqual([]);
      expect(presentation.visibleQuestionChips).toBe(0);
      for (const length of presentation.standfirstLengths) {
        expect(length, `${route} standfirst is too long`).toBeLessThanOrEqual(
          240,
        );
      }
    }
  });

  test("every panel declares an honest binding basis", async ({ page }) => {
    const routes = [
      "overview",
      "fed",
      "rates",
      "inflation",
      "usd",
      "gold",
      "energy",
      "factors",
      "notes",
    ];
    const allowed = new Set(["REAL", "COMPUTED", "PLANNED", "REFERENCE"]);

    for (const route of routes) {
      await page.goto(`/macro/${route}`);
      await page.waitForLoadState("networkidle");

      const panels = await page
        .locator('[data-testid^="board-panel-"]')
        .evaluateAll((nodes) =>
          nodes.map((node) => ({
            id: node.getAttribute("data-testid"),
            basis: node.getAttribute("data-basis"),
          })),
        );
      expect(panels.length, `${route} has no classified panels`).toBeGreaterThan(0);
      for (const panel of panels) {
        expect(
          allowed.has(panel.basis ?? ""),
          `${route} ${panel.id} has invalid basis ${panel.basis}`,
        ).toBe(true);
      }
    }

    await page.goto("/macro/energy");
    await expect(page.getByTestId("board-panel-energy-inventory")).toHaveAttribute(
      "data-basis",
      "REFERENCE",
    );
    await page.goto("/macro/notes");
    for (const panel of await page.locator('[data-testid^="board-panel-"]').all()) {
      await expect(panel).toHaveAttribute("data-basis", "REFERENCE");
    }
  });

  test("tab 08 renders under the desk's tab bar and stays selectable", async ({
    page,
  }) => {
    const consoleErrors = collectConsoleErrors(page);

    const response = await page.goto("/macro/notes");
    expect(response?.status()).toBe(200);
    await page.waitForLoadState("networkidle");

    // The tab's own content, by the testid `DesignNotes` carries.
    await expect(page.getByTestId("macro-design-notes")).toBeVisible();
    // level 2, not 1: every tab on this desk opens with the board's `.sec-title`, whose
    // heading is an <h2> — the <h1> belongs to the desk, not to one tab inside it.
    await expect(
      page.getByRole("heading", { name: "Method", level: 2 }),
    ).toBeVisible();

    // The shell around it. The bar lives in `app/macro/layout.tsx`, so its absence here
    // would mean the tab rendered outside the desk rather than inside it.
    await expect(page.getByTestId("macro-tab-bar")).toBeVisible();

    // The approved board includes tab 08 in the strip. It remains operator-facing copy,
    // but the pixel port keeps the board's complete navigation hierarchy.
    await expect(page.getByTestId("macro-tab-notes")).toHaveCount(1);
    await expect(
      page.locator('[data-testid="macro-tab-bar"] a[aria-current="page"]'),
    ).toHaveCount(1);

    expect(realErrors(consoleErrors)).toEqual([]);
  });

  test("every link the tab bar renders resolves to a route that exists", async ({
    page,
  }) => {
    await page.goto("/macro/notes");
    await page.waitForLoadState("networkidle");

    const links = page.locator('[data-testid="macro-tab-bar"] a');
    const hrefs = await links.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("href") ?? ""),
    );

    // A bar that rendered nothing would make every assertion below vacuously true, and
    // this spec would then "pass" through the exact outage it exists to catch. The three
    // tabs registered today are named individually for the same reason: `length > 0`
    // alone would survive a registry that silently lost two of them.
    //
    // Deliberately a FLOOR and a containment, not an exact list in board order — that
    // identity is already held at render level by `tests/unit/macroTabBar.test.tsx`
    // ("renders exactly one link per registry entry" + "orders the bar by board
    // ordinal"). Pinning the full list again here would make every future tab
    // registration edit this file for nothing, and the walk below already sweeps
    // whatever the registry grew.
    expect(hrefs.length).toBeGreaterThanOrEqual(5);
    expect(hrefs).toEqual(
      expect.arrayContaining([
        "/macro/fed",
        "/macro/rates",
        "/macro/inflation",
        "/macro/usd",
        "/macro/gold",
      ]),
    );
    expect(hrefs).toContain("/macro/notes");
    for (const href of hrefs) {
      expect(href).toMatch(/^\/macro\/[^/]+$/);
    }

    for (const href of hrefs) {
      const response = await page.goto(href);
      expect(
        response,
        `${href} produced no response — the bar links somewhere unreachable`,
      ).not.toBeNull();
      // Asserted as "not 404" rather than "is 200" on purpose: later tabs fetch 1-3 live
      // endpoints each, and a dead publisher must be allowed to cost that tab its data
      // without failing THIS gate, which is about the route existing. A 404 is the one
      // status that means the registry and the router disagree.
      expect(
        response?.status(),
        `${href} is linked from the tab bar but 404s`,
      ).not.toBe(404);

      // ...and it landed inside the desk, not on some other page that happens to answer.
      await expect(page.getByTestId("macro-tab-bar")).toBeVisible();
    }
  });

  test("a slug the registry does not know says so, and renders no tab", async ({
    page,
  }) => {
    await page.goto("/macro/definitely-not-a-tab");
    await page.waitForLoadState("networkidle");

    // `app/macro/[tab]/page.tsx` calls `notFound()` on any slug absent from `VALID_TABS`,
    // and `app/macro/[tab]/not-found.tsx` is what that throw renders.
    //
    // ON THE STATUS CODE, measured 2026-08-28 rather than assumed. This assertion used to
    // read `expect(response?.status()).toBe(404)`. It was written in P2 and never run;
    // run for the first time in P3 it failed, because the route answers **200**. The
    // cause is not this desk: `notFound()` cannot set a status once a `force-dynamic`
    // route has begun streaming, and the response has begun by the time `await params`
    // resolves. argon's pre-existing `/stock/[ticker]/[tab]` uses the identical
    // `await params` → `notFound()` shape and answers 200 for an unknown tab too, so this
    // is repo-wide framework behaviour, not a regression. Verified against BOTH servers
    // (`next start` and the `output: "standalone"` build) and with `loading.tsx` removed —
    // 200 in every combination. A true 404 needs the check to run before the stream
    // starts, i.e. in `middleware.ts`, which is a change to every route in the app and is
    // therefore not P3's to make.
    //
    // So this test asserts the two things that ARE true and that actually protect the
    // operator: the desk says the tab does not exist, and no tab content rendered. Both
    // fail loudly if the registry guard breaks. The status gap is recorded above rather
    // than deleted, because an expectation that was quietly dropped is indistinguishable
    // from one that was never held.
    await expect(page.getByText("No such macro tab.")).toBeVisible();

    // Before `not-found.tsx` existed, `notFound()` had no boundary inside the desk and the
    // route sat on the loading fallback forever — a page that reads as hung rather than as
    // missing. That is the inverse of what the registry protects against, so it gets its
    // own assertion: the fallback must be GONE, not merely joined by the refusal.
    await expect(page.getByText("Loading macro desk tab")).toHaveCount(0);

    // Still `notes` alone now that three tabs are registered, and on purpose: tabs 01
    // and 02 render `DeskEmptyState` when the rates API has no snapshot, so every anchor
    // they carry is data-dependent and would make this assertion pass for the wrong
    // reason. `macro-design-notes` is static prose — present in EVERY data state — which
    // makes it the one sentinel that can only be absent because no tab rendered.
    await expect(page.getByTestId("macro-design-notes")).toHaveCount(0);
  });

  test("/macro lands on tab 00, with the four domain cards intact", async ({
    page,
  }) => {
    const consoleErrors = collectConsoleErrors(page);

    // The flip P5 owns. `app/macro/page.tsx` is now `redirect("/macro/overview")`, and it
    // is safe only because `overview` is registered in `VALID_TABS` in the same commit —
    // §8's "no PR may ship a link to a route that does not exist", pointed at the desk's
    // own root.
    await page.goto("/macro");
    await page.waitForLoadState("networkidle");
    expect(new URL(page.url()).pathname).toBe("/macro/overview");

    // NOTHING WAS ORPHANED BY THE FLIP. The four cards that used to live at `/macro` are
    // rendered by tab 00, and this is the assertion that would fail if a later PR moved
    // the redirect without moving them.
    for (const domain of ["inflation", "policy_rates", "usd", "gold"]) {
      await expect(page.getByTestId(`macro-domain-${domain}`)).toBeVisible();
    }

    // ...and the desk's root is now a real tab, so the bar marks it current. Through
    // P2-P4 the assertion here was the opposite (`aria-current` count 0), because
    // `/macro` was not itself a registered tab.
    const bar = page.getByTestId("macro-tab-bar");
    await expect(bar).toBeVisible();
    await expect(page.getByTestId("macro-tab-overview")).toHaveAttribute(
      "aria-current",
      "page",
    );

    expect(realErrors(consoleErrors)).toEqual([]);
  });

  test("tab 00 re-presents the other tabs and computes nothing of its own", async ({
    page,
  }) => {
    // Plan §8's scope bound, at the browser. The panels are named individually because
    // "the page rendered" is exactly the assertion that would survive tab 00 quietly
    // losing three of its four panels.
    await page.goto("/macro/overview");
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("macro-overview")).toBeVisible();
    await expect(page.getByTestId("macro-chain-rail")).toBeVisible();
    for (const panel of ["cross-domain", "contradictions", "transmission"]) {
      await expect(page.getByTestId(`board-panel-${panel}`)).toBeVisible();
    }

    // Five publishers, five transmission-health rows. This is the tab's own definition of
    // itself: `/api/macro/snapshot` plus the four domain states, and nothing else.
    for (const id of ["snapshot", "inflation", "policy_rates", "usd", "gold"]) {
      await expect(page.getByTestId(`macro-health-${id}`)).toBeVisible();
    }

    // The runtime posture ban, whole-body on this tab. Unlike tab 02, tab 00 has no
    // quarantine carve-out: §10-I's ruling names it explicitly — the stance word may print
    // only where the model produced it, which is inside `RatesScorecard`, and tab 00
    // fetches neither endpoint that carries `duration_stance`. "No composite" is allowed
    // because it is the board's explicit refusal, not a computed score.
    const body = (
      await page.locator("main.macro-desk-main").innerText()
    ).toLowerCase();
    for (const banned of [
      /\bbuy\b/,
      /\bsell\b/,
      /duration stance/,
      /position size/,
      /predicted return/,
      /master score/,
    ]) {
      expect(body, `tab 00 body matched ${banned}`).not.toMatch(banned);
    }
    expect(body).toContain("no composite");
    // Non-vacuity: a body that failed to render would pass every ban above.
    expect(body).toContain("daily loop");
  });

  test("tab 00's replay date actually reaches all five publishers", async ({
    page,
  }) => {
    // The one thing the unit tests cannot check: that `?as_of=` is wired through
    // `api.macroDomainState` / `api.macroContextSnapshot` to the real API.
    //
    // 2000-01-01 is chosen so the outcome is deterministic on ANY database: no macro state
    // can predate it, so every one of the five reads must 404 and every verdict must be
    // `unanswered`. And the test DISCRIMINATES rather than merely passing — if the
    // parameter were dropped, the API would answer with today's states, whose `as_of` sits
    // after the instant asked for, and the desk would render the wrong-instant refusal
    // instead. Both outcomes are visible; only one is correct.
    await page.goto("/macro/overview?as_of=2000-01-01");
    await page.waitForLoadState("networkidle");

    await page.getByTestId("macro-replay-menu").locator("summary").click();
    const control = page.getByTestId("macro-replay-control");
    await expect(control).toBeVisible();
    await expect(control).toHaveAttribute("data-replay-clock", "instant");

    const status = page.getByTestId("macro-replay-status");
    await expect(status).toBeVisible();
    await expect(status).toHaveAttribute("data-replay-state", "unanswered");
    await expect(page.getByTestId("macro-overview-wrong-instant")).toHaveCount(0);

    // `unanswered` is a publisher's own honest answer, not an API defect, so the tab is
    // NOT blanked — the panels still say which of the five answered. Blanking here would
    // destroy the only thing tab 00 is for.
    await expect(page.getByTestId("board-panel-transmission")).toBeVisible();
    await expect(page.getByTestId("macro-chain-rail")).toBeVisible();
    await expect(page.getByTestId("macro-health-snapshot")).toHaveAttribute(
      "data-answered",
      "never computed",
    );

    // `/api/gold/gauge` publishes a history rather than taking `as_of`. The overview may
    // use that persisted history, but it must bound it to the requested instant; otherwise
    // this 2000 replay draws today's anchor under a historical heading.
    await expect(
      page
        .getByTestId("board-panel-anchor-decay")
        .locator('svg[role="img"]'),
    ).toHaveCount(0);
  });
});

/**
 * The board's acceptance test, at the level where it failed.
 *
 * "The seven questions are the acceptance test: every panel must answer at least one, or
 * it gets deleted." The port shipped without carrying that rule anywhere, so tabs 03 and
 * 04 reached production with one generic card each where the board specifies four panels
 * and two. Unit tests pin the panels against a frozen payload; this walks the live desk,
 * because what went wrong was nobody looking at the running page.
 */
test.describe("board conformance", () => {
  const EXPECTED: Record<string, string[]> = {
    inflation: [
      "confidence-arithmetic",
      "confidence-repair",
      "realized-inflation",
      "inflation-expectations",
    ],
    usd: ["dollar-pair", "upstream-citation"],
    factors: ["factor-vector", "factor-delivery", "factor-refusal"],
    energy: ["energy-inventory", "energy-route"],
  };

  for (const [slug, panels] of Object.entries(EXPECTED)) {
    test(`/macro/${slug} renders every panel the board specifies`, async ({
      page,
    }) => {
      await page.goto(`/macro/${slug}`);
      await page.waitForLoadState("networkidle");
      for (const id of panels) {
        await expect(page.getByTestId(`board-panel-${id}`)).toBeVisible();
      }
    });
  }

  test("every panel on the desk names a board question", async ({ page }) => {
    // The tuple type makes an untagged `BoardPanel` a compile error and gold's bands
    // carry the attribute by hand. Neither reaches the rendered page on its own, so the
    // rule is checked where a reviewer would check it.
    for (const slug of ["inflation", "usd", "gold", "factors", "energy"]) {
      await page.goto(`/macro/${slug}`);
      await page.waitForLoadState("networkidle");
      const tagged = page.locator("[data-questions]");
      const count = await tagged.count();
      // A page with no tagged panel would make the loop below vacuously true, which is
      // the exact outage this exists to catch.
      expect(count, `/macro/${slug} rendered no tagged panel`).toBeGreaterThan(
        0,
      );
      for (const value of await tagged.evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute("data-questions") ?? ""),
      )) {
        expect(value, `/macro/${slug} has an untagged panel`).toMatch(
          /^Q[1-7]( Q[1-7])*$/,
        );
      }
    }
  });

  test("the confidence chain reproduces the number it sits beside", async ({
    page,
  }) => {
    // Against the live engine, not a fixture: if the terms ever stop multiplying to the
    // published confidence the panel is required to say so in the negative colour, and
    // this asserts that today it does not have to.
    await page.goto("/macro/inflation");
    await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("confidence-reconciliation")).toContainText(
      /reproduces the published/i,
    );
  });
});
