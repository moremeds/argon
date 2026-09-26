/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/stock/AAPL/market-structure",
}));

// Same shape as macroTabBar.test.tsx: next/link does not render `prefetch` into
// the DOM, so the mock surfaces it as data-prefetch.
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

import { TabBar } from "@/components/stock/TabBar";

describe("stock TabBar", () => {
  it("does not prefetch any tab", () => {
    render(<TabBar ticker="AAPL" />);
    const links = screen.getAllByRole("link");
    expect(links.length).toBeGreaterThan(1);
    expect(links.map((a) => a.getAttribute("data-prefetch"))).toEqual(
      links.map(() => "false"),
    );
  });
});
