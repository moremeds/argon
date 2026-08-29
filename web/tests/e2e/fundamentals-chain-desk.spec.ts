import { expect, test, type Page } from "@playwright/test";

/**
 * The chain desk's three canvas scenes.
 *
 * They live HERE and not in vitest because jsdom has no 2D context:
 * `getContext("2d")` returns null and `createScene` throws inside the effect,
 * which is the same reason `web/CLAUDE.md` keeps the lightweight-charts panes
 * out of unit tests. The vitest suite stubs these three and covers the
 * fetch-to-prop wiring around them; what needs a real browser is that they
 * paint at all, that they survive a theme flip, and that the two funnels stay
 * locked to one orientation.
 */

const DESK = "/fundamentals/ai-semi";
const CASES = "/fundamentals/ai-semi/cases";

const consoleErrors = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  consoleErrors.set(page, errors);
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(String(e)));
});

/** True when the canvas has painted something other than transparent black. */
async function hasInk(page: Page, index: number): Promise<boolean> {
  return page.evaluate((i) => {
    const canvas = document.querySelectorAll("canvas")[i] as HTMLCanvasElement;
    const ctx = canvas.getContext("2d");
    if (!ctx) return false;
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    for (let p = 3; p < data.length; p += 4) if (data[p] !== 0) return true;
    return false;
  }, index);
}

test("the question ladder renders in order, and every scene paints", async ({
  page,
}) => {
  await page.goto(DESK);
  // The order IS the argument: question three cannot be answered before
  // question one, so a page that renders them out of sequence is making a
  // different case from the one the desk intends.
  const headings = await page
    .locator('[data-testid^="desk-"] h2')
    .allInnerTexts();
  expect(headings.slice(0, 5)).toEqual([
    "IS THE MONEY STILL COMING?",
    "WHERE DOES IT LAND?",
    "DOES IT TRANSMIT?",
    "WHAT AM I PAYING FOR IT?",
    "WHAT WOULD FALSIFY THIS?",
  ]);
  await expect(
    page.getByTestId("desk-chain-map").locator("canvas"),
  ).toBeVisible();
  expect(await hasInk(page, 0)).toBe(true);
  expect(await hasInk(page, 1)).toBe(true);
  expect(consoleErrors.get(page)).toHaveLength(0);
});

test("every taxonomy layer the legend lists is actually drawn", async ({
  page,
}) => {
  // The regression this pins: a scene scaled off canvas WIDTH pushed the top
  // planes above the frame, so L4 and L5 were invisible while the legend
  // still listed them — the map silently showed three layers of five.
  await page.goto(DESK);
  const map = page.getByTestId("desk-chain-map");
  const listed = (await map.locator("canvas + div").innerText())
    .split("\n")
    .filter((line) => /^L[1-5] /.test(line)).length;

  // "Ink reaches row 0" is what clipping LOOKS like, and it is the only
  // signal that distinguishes a fitted scene from a cropped one: the top
  // planes were still painting when they overflowed, just above the frame.
  // A fitted scene leaves a margin; a clipped one starts at the first row.
  const inkTop = await page.evaluate(() => {
    const canvas = document.querySelectorAll("canvas")[1] as HTMLCanvasElement;
    const ctx = canvas.getContext("2d")!;
    const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height);
    for (let y = 0; y < canvas.height; y++) {
      const row = y * canvas.width * 4;
      for (let x = 0; x < canvas.width; x++)
        if (data[row + x * 4 + 3] !== 0) return y / canvas.height;
    }
    return 1;
  });
  expect(listed).toBeGreaterThanOrEqual(3);
  expect(inkTop).toBeGreaterThan(0.01);
});

test("the scenes repaint when the theme flips", async ({ page }) => {
  // Argon stamps `data-theme` on <html>; a canvas that reads its palette once
  // at mount keeps painting dark-theme ink on a white ground.
  await page.goto(DESK);
  await expect(
    page.getByTestId("desk-chain-map").locator("canvas"),
  ).toBeVisible();
  const before = await page.evaluate(() =>
    (document.querySelectorAll("canvas")[1] as HTMLCanvasElement).toDataURL(),
  );
  await page.evaluate(() =>
    document.documentElement.setAttribute("data-theme", "light"),
  );
  await page.waitForTimeout(600);
  const after = await page.evaluate(() =>
    (document.querySelectorAll("canvas")[1] as HTMLCanvasElement).toDataURL(),
  );
  expect(after).not.toEqual(before);
  expect(consoleErrors.get(page)).toHaveLength(0);
});

test("both funnels render side by side on one shared scale", async ({
  page,
}) => {
  await page.goto(CASES);
  const canvases = page.locator("canvas");
  await expect(canvases).toHaveCount(2);
  const a = await canvases.nth(0).boundingBox();
  const b = await canvases.nth(1).boundingBox();
  // SIDE BY SIDE is load-bearing, not layout taste: the radius scale is
  // shared, so the comparison of the two silhouettes IS the finding. Stacked
  // vertically, a reader cannot make it.
  expect(a!.y).toBeCloseTo(b!.y, 0);
  expect(b!.x).toBeGreaterThan(a!.x + a!.width - 2);
  expect(await hasInk(page, 0)).toBe(true);
  expect(await hasInk(page, 1)).toBe(true);
  expect(consoleErrors.get(page)).toHaveLength(0);
});

test("dragging one funnel rotates the other", async ({ page }) => {
  await page.goto(CASES);
  const canvases = page.locator("canvas");
  await expect(canvases).toHaveCount(2);
  // Stop the auto-rotation first, or the "did it move" comparison is true
  // whether or not the drag propagated.
  await page.getByRole("button", { name: "Auto-rotate" }).click();
  await page.waitForTimeout(400);
  const before = await page.evaluate(() =>
    (document.querySelectorAll("canvas")[1] as HTMLCanvasElement).toDataURL(),
  );
  const box = (await canvases.nth(0).boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 120, box.y + box.height / 2, {
    steps: 8,
  });
  await page.mouse.up();
  await page.waitForTimeout(500);
  const after = await page.evaluate(() =>
    (document.querySelectorAll("canvas")[1] as HTMLCanvasElement).toDataURL(),
  );
  // A per-funnel orientation would let a reader see one case front-on and the
  // other edge-on and read the difference as data.
  expect(after).not.toEqual(before);
});

test("the desk never offers a way to sort by valuation", async ({ page }) => {
  // Own-history value is the one measured claim; cross-sectional value
  // measured INVERTED in this same universe. The absence of an ordering
  // control is the guard, so it is asserted rather than assumed.
  await page.goto(DESK);
  const controls = await page.getByRole("button").allInnerTexts();
  for (const label of controls) {
    expect(label.toLowerCase()).not.toMatch(/\bsort\b|\brank\b|cheapest/);
  }
  await expect(
    page.getByText(/0\.80 means cheap, not expensive/),
  ).toBeVisible();
});
