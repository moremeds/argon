import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

let pathname = "/macro/notes";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
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
import { VALID_TABS, macroTabHref } from "@/components/macro/tabs";

describe("MacroTabBar", () => {
  it("renders exactly one link per registry entry, and nothing else", () => {
    pathname = "/macro/notes";
    render(<MacroTabBar />);
    const links = screen.getAllByRole("link");

    // Both directions of the identity: no rendered link that the registry does not
    // know (which would be a link to a route that 404s), and no registry entry the
    // bar failed to render (which would be an unreachable tab).
    expect(links).toHaveLength(VALID_TABS.length);
    expect(links.map((a) => a.getAttribute("href")).sort()).toEqual(
      VALID_TABS.map((tab) => macroTabHref(tab.slug)).sort(),
    );
    for (const tab of VALID_TABS) {
      expect(screen.getByTestId(`macro-tab-${tab.slug}`)).toHaveProperty(
        "textContent",
        tab.label,
      );
    }
  });

  it("prefetches nothing", () => {
    pathname = "/macro/notes";
    render(<MacroTabBar />);
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("data-prefetch")).toBe("false");
    }
  });

  it("marks the current tab with aria-current, not a tablist role", () => {
    pathname = "/macro/notes";
    render(<MacroTabBar />);

    const nav = screen.getByTestId("macro-tab-bar");
    expect(nav.tagName).toBe("NAV");
    expect(nav.getAttribute("aria-label")).toBe("Macro desk tabs");
    // A link-based bar is not a tablist: the panels are separate documents. Honest
    // markup over a role that promises a widget which does not exist.
    expect(nav.getAttribute("role")).toBeNull();
    expect(nav.querySelector('[role="tab"]')).toBeNull();

    const active = screen.getByTestId("macro-tab-notes");
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
    pathname = "/macro/notes/anything-nested";
    render(<MacroTabBar />);
    expect(
      screen.getByTestId("macro-tab-notes").getAttribute("aria-current"),
    ).toBe("page");
  });

  it("orders the bar by board ordinal, not by registration order", () => {
    pathname = "/macro/notes";
    render(<MacroTabBar />);
    const rendered = screen
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    const byOrdinal = [...VALID_TABS]
      .sort((a, b) => a.ordinal.localeCompare(b.ordinal))
      .map((tab) => macroTabHref(tab.slug));
    expect(rendered).toEqual(byOrdinal);
  });

  it("carries the shared tab-strip classes rather than a private copy", () => {
    pathname = "/macro/notes";
    render(<MacroTabBar />);
    // The metrics live in .ticker-tabs/.ticker-tab; .macro-* carries only the two
    // deltas a link-based bar needs (wrap, text-decoration).
    expect(screen.getByTestId("macro-tab-bar").className).toBe(
      "ticker-tabs macro-tabs",
    );
    expect(screen.getByTestId("macro-tab-notes").className).toContain(
      "ticker-tab",
    );
    expect(screen.getByTestId("macro-tab-notes").className).toContain(
      "macro-tab",
    );
  });
});
