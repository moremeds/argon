import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let pathname = "/macro/fed";
let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useSearchParams: () => search,
}));

// Mocked so the test can observe `prefetch`, which next/link deliberately does not
// render into the DOM. It is the one prop on this bar whose regression is invisible
// in a snapshot and expensive in production.
vi.mock("next/link", () => ({
  default: ({
    href,
    prefetch,
    children,
    ...rest
  }: {
    href: string;
    prefetch?: boolean;
    children: React.ReactNode;
  } & Record<string, unknown>) => (
    <a href={href} data-prefetch={String(prefetch)} {...rest}>
      {children}
    </a>
  ),
}));

import { MacroTabBar } from "@/components/macro/MacroTabBar";
import {
  VALID_TABS,
  macroTabHref,
  macroTabsForBar,
} from "@/components/macro/tabs";

// What the strip is EXPECTED to show. Not `VALID_TABS`: tab 08 is registered and
// reachable at /macro/notes, and is deliberately absent from the strip because the
// board's t8 says it does not ship on the final page. The subset relation between the
// two is asserted below rather than assumed.
const BAR = macroTabsForBar();

describe("MacroTabBar", () => {
  beforeEach(() => {
    pathname = "/macro/fed";
    search = new URLSearchParams();
  });

  it("renders exactly one link per registry entry, and nothing else", () => {
    pathname = "/macro/fed";
    render(<MacroTabBar />);
    const links = screen.getAllByRole("link");

    // Both directions of the identity: no rendered link that the registry does not
    // know (which would be a link to a route that 404s), and no registry entry the
    // bar failed to render (which would be an unreachable tab).
    expect(links).toHaveLength(BAR.length);
    expect(links.map((a) => a.getAttribute("href")).sort()).toEqual(
      BAR.map((tab) => macroTabHref(tab.slug)).sort(),
    );
    for (const tab of BAR) {
      expect(screen.getByTestId(`macro-tab-${tab.slug}`)).toHaveProperty(
        "textContent",
        tab.label,
      );
    }
  });

  it("hides the operator-only tab without unregistering it", () => {
    // The board's t8: "This tab is for you (the operator) and does not ship on the final
    // page." Deleting the registry entry would have satisfied that and lost the route;
    // leaving it in the strip was the shipped state and ignored it. So it stays
    // registered — /macro/notes still resolves — and stays out of the bar.
    render(<MacroTabBar />);
    expect(screen.queryByTestId("macro-tab-notes")).toBeNull();
    expect(VALID_TABS.some((tab) => tab.slug === "notes")).toBe(true);
  });

  it("renders a SUBSET of the registry, never anything outside it", () => {
    // The registry invariant, restated for a bar that no longer shows every entry: the
    // bar may show fewer tabs than exist, and must never show one that does not.
    render(<MacroTabBar />);
    const registered = new Set(VALID_TABS.map((tab) => macroTabHref(tab.slug)));
    for (const link of screen.getAllByRole("link")) {
      expect(registered.has(link.getAttribute("href") ?? "")).toBe(true);
    }
  });

  it("prefetches nothing", () => {
    pathname = "/macro/fed";
    render(<MacroTabBar />);
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("data-prefetch")).toBe("false");
    }
  });

  it("marks the current tab with aria-current, not a tablist role", () => {
    pathname = "/macro/fed";
    render(<MacroTabBar />);

    const nav = screen.getByTestId("macro-tab-bar");
    expect(nav.tagName).toBe("NAV");
    expect(nav.getAttribute("aria-label")).toBe("Macro desk tabs");
    // A link-based bar is not a tablist: the panels are separate documents. Honest
    // markup over a role that promises a widget which does not exist.
    expect(nav.getAttribute("role")).toBeNull();
    expect(nav.querySelector('[role="tab"]')).toBeNull();

    const active = screen.getByTestId("macro-tab-fed");
    expect(active.getAttribute("aria-current")).toBe("page");
    expect(active.className).toContain("active");
  });

  it("marks nothing current on a route outside the registered tabs", () => {
    pathname = "/macro";
    render(<MacroTabBar />);
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("aria-current")).toBeNull();
      expect(link.className).not.toContain("active");
    }
  });

  it("keeps a tab current on its own child routes", () => {
    pathname = "/macro/fed/anything-nested";
    render(<MacroTabBar />);
    expect(
      screen.getByTestId("macro-tab-fed").getAttribute("aria-current"),
    ).toBe("page");
  });

  it("orders the bar by board ordinal, not by registration order", () => {
    pathname = "/macro/fed";
    render(<MacroTabBar />);
    const rendered = screen
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    const byOrdinal = [...BAR]
      .sort((a, b) => a.ordinal.localeCompare(b.ordinal))
      .map((tab) => macroTabHref(tab.slug));
    expect(rendered).toEqual(byOrdinal);
  });

  it("carries the shared tab-strip classes rather than a private copy", () => {
    pathname = "/macro/fed";
    render(<MacroTabBar />);
    // The metrics live in .ticker-tabs/.ticker-tab; .macro-* carries only the two
    // deltas a link-based bar needs (wrap, text-decoration).
    expect(screen.getByTestId("macro-tab-bar").className).toBe(
      "ticker-tabs macro-tabs",
    );
    expect(screen.getByTestId("macro-tab-fed").className).toContain(
      "ticker-tab",
    );
    expect(screen.getByTestId("macro-tab-fed").className).toContain(
      "macro-tab",
    );
  });

  it("carries the replay date across every tab switch", () => {
    // Without this the operator replaying 2026-08-20 on tab 01 clicks tab 02 and lands on
    // a LIVE tab believing he is still replaying — plan §3.1's "a replayed tab beside a
    // live one, with nothing on screen saying so", reintroduced by navigation after the
    // API and the banner had both closed it.
    search = new URLSearchParams("as_of=2026-08-20");
    render(<MacroTabBar />);
    for (const tab of BAR) {
      expect(
        screen.getByTestId(`macro-tab-${tab.slug}`).getAttribute("href"),
      ).toBe(`${macroTabHref(tab.slug)}?as_of=2026-08-20`);
    }
  });

  it("forwards a rejected value verbatim rather than dropping it", () => {
    // Dropping it on navigation would turn a visible refusal into a live page that looks
    // like the replay worked. The bar does not re-parse; the destination tab does.
    search = new URLSearchParams("as_of=yesterday");
    render(<MacroTabBar />);
    expect(screen.getByTestId("macro-tab-rates").getAttribute("href")).toBe(
      "/macro/rates?as_of=yesterday",
    );
  });

  it("adds nothing to the href when the desk is live", () => {
    render(<MacroTabBar />);
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href")).not.toContain("?");
    }
  });
});
