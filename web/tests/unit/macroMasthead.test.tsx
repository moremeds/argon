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
import { MacroFooter } from "@/components/macro/MacroFooter";

describe("MacroMasthead", () => {
  it("renders a compact operator header above the tab strip", () => {
    pathname = "/macro/rates";
    search = new URLSearchParams();
    const { container } = render(
      <MacroMasthead
        snapshotStatus="complete"
        snapshotAsOf="2026-08-25T23:40:00Z"
        today="2026-08-29"
      />,
    );

    expect(container.firstElementChild?.className).toBe("appbar");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Macro");
    expect(screen.getByText("Inflation → Policy → Dollar → Gold")).toBeTruthy();
    expect(screen.getByText(/live chain complete/i)).toBeTruthy();
    expect(screen.getByText(/2026-08-26 07:40 UTC\+8/)).toBeTruthy();
    const replayMenu = screen.getByTestId("macro-replay-menu");
    expect(replayMenu.tagName).toBe("DETAILS");
    expect((replayMenu as HTMLDetailsElement).open).toBe(false);
    expect(screen.queryByText(/Integration Proposal/i)).toBeNull();
    expect(container.querySelectorAll(".legend-strip, .pmq")).toHaveLength(0);
  });

  it("keeps an unavailable snapshot visibly unavailable", () => {
    pathname = "/macro/rates";
    search = new URLSearchParams();
    const { container } = render(
      <MacroMasthead
        snapshotStatus="unavailable"
        snapshotAsOf={null}
        today="2026-08-29"
      />,
    );
    expect(screen.getByText(/live chain unavailable/i)).toBeTruthy();
    expect(
      container.querySelectorAll(".mast-meta .chip")[1]?.textContent,
    ).toMatch(/as_of unavailable/i);
  });

  it("labels the layout footer as live even beside a replayed tab", () => {
    render(<MacroFooter snapshotAsOf="2026-08-25T23:40:00Z" />);

    expect(screen.getByText(/Live snapshot 2026-08-25T23:40:00Z/)).toBeTruthy();
  });
});
