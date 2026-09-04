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
 * Flash sits directly under Dashboard — the operator's call, and the only
 * entry in the nav that carries a subtitle. Asserted by position because
 * "somewhere in the list" is how a promoted surface quietly demotes itself.
 */
describe("Flash nav entry", () => {
  it("is the second entry, under Dashboard", () => {
    expect(NAV[0].label).toBe("Dashboard");
    expect(NAV[1].label).toBe("Flash");
    expect(NAV[1].href).toBe("/flash");
    expect(NAV[1].sub).toBe("agent news flash");
  });

  it("marks the current route and shows the subtitle", () => {
    pathname = "/flash";
    render(<Sidebar />);

    const link = screen.getByRole("link", { name: /Flash/ });
    expect(link.getAttribute("href")).toBe("/flash");
    expect(link.getAttribute("aria-current")).toBe("page");
    expect(screen.getByText("agent news flash")).toBeTruthy();
  });

  it("does not mark Flash current from another route", () => {
    pathname = "/scanner";
    render(<Sidebar />);

    const link = screen.getByRole("link", { name: /Flash/ });
    expect(link.getAttribute("aria-current")).toBeNull();
  });
});
