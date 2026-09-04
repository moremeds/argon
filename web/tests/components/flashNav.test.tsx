import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

let pathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

vi.mock("@/components/shared/HealthPanel", () => ({
  HealthPanel: () => <div>Health</div>,
}));

import { NAV, Sidebar } from "@/components/shared/Sidebar";

/**
 * Flash sits directly under Dashboard — the operator's call. Asserted by
 * position because "somewhere in the list" is how a promoted surface quietly
 * demotes itself. No entry carries a subtitle any more: "agent news flash"
 * moved to the page's own topbar, where the reader is already looking at
 * Flash, instead of explaining a room from the corridor.
 */
describe("Flash nav entry", () => {
  it("is the second entry, under Dashboard", () => {
    expect(NAV[0].label).toBe("Dashboard");
    expect(NAV[1].label).toBe("Flash");
    expect(NAV[1].href).toBe("/flash");
    expect(NAV.every((entry) => !("sub" in entry))).toBe(true);
  });

  it("marks the current route", () => {
    pathname = "/flash";
    render(<Sidebar />);

    const link = screen.getByRole("link", { name: /Flash/ });
    expect(link.getAttribute("href")).toBe("/flash");
    expect(link.getAttribute("aria-current")).toBe("page");
    expect(screen.queryByText("agent news flash")).toBeNull();
  });

  it("does not mark Flash current from another route", () => {
    pathname = "/scanner";
    render(<Sidebar />);

    const link = screen.getByRole("link", { name: /Flash/ });
    expect(link.getAttribute("aria-current")).toBeNull();
  });
});
