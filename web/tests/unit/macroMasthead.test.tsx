import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

let pathname = "/macro/rates";
let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useSearchParams: () => search,
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: React.ComponentProps<"a">) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { MacroMasthead } from "@/components/macro/MacroMasthead";

describe("MacroMasthead", () => {
  it("renders the complete artifact shell above the tab strip", () => {
    pathname = "/macro/rates";
    search = new URLSearchParams();
    const { container } = render(
      <MacroMasthead
        snapshotStatus="complete"
        snapshotAsOf="2026-08-25T23:40:00Z"
        sourceLabel="macmini · option_wizard production snapshot"
        today="2026-08-29"
      />,
    );

    expect(container.firstElementChild?.className).toBe("appbar");
    expect(screen.getByText("ARGON").closest(".brand")?.textContent).toBe(
      "ARGON — MACRO",
    );
    expect(screen.getByText(/chain snapshot: complete/i)).toBeTruthy();
    expect(screen.getByText(/2026-08-26 07:40 UTC\+8/)).toBeTruthy();
    const replayMenu = screen.getByTestId("macro-replay-menu");
    expect(replayMenu.tagName).toBe("DETAILS");
    expect((replayMenu as HTMLDetailsElement).open).toBe(false);
    expect(screen.getByText(/Macro Phase 2 Integration Proposal/i)).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Macro Desk / Fed → Inflation → USD → Gold",
    );
    expect(container.querySelectorAll(".legend-strip")).toHaveLength(1);
    expect(container.querySelectorAll(".pmq .q")).toHaveLength(7);
  });

  it("keeps an unavailable snapshot visibly unavailable", () => {
    pathname = "/macro/rates";
    search = new URLSearchParams();
    const { container } = render(
      <MacroMasthead
        snapshotStatus="unavailable"
        snapshotAsOf={null}
        sourceLabel="argon · macro API snapshot"
        today="2026-08-29"
      />,
    );
    expect(screen.getByText(/chain snapshot: unavailable/i)).toBeTruthy();
    expect(container.querySelectorAll(".mast-meta .chip")[1]?.textContent).toMatch(
      /as_of unavailable/i,
    );
  });
});
