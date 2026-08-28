import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

let pathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

vi.mock("@/components/shared/HealthPanel", () => ({
  HealthPanel: () => <div>Health</div>,
}));

import { AppShell } from "@/components/shared/AppShell";

describe("AppShell", () => {
  it("renders the Argon sidebar on normal routes", () => {
    pathname = "/";

    render(<AppShell>Dashboard content</AppShell>);

    expect(screen.getByText("ARGON")).toBeTruthy();
    expect(screen.getByRole("main").textContent).toContain("Dashboard content");
  });

  it("renders a macro desk tab inside the normal Argon shell", () => {
    // Was `/rates`, which is now a 308 into this tab. Re-pointed rather than deleted: the
    // assertion is that a desk route still gets the standard shell, and that is as true
    // of `/macro/rates` as it was of `/rates`.
    pathname = "/macro/rates";

    render(<AppShell>Rates content</AppShell>);

    expect(screen.getByText("ARGON")).toBeTruthy();
    const main = screen.getByRole("main");
    expect(main.textContent).toContain("Rates content");
    expect(main.className).toContain("main");
  });

  it("lists ONE macro entry, and highlights it for every tab under it", () => {
    // The sidebar collapse. Gold, Rates and Macro were three peers; `/gold` and `/rates`
    // both 308 into the desk now, so the two removed entries would have been links to
    // redirects. The plan's ordering rule is that a peer may only be removed once its
    // destination tab is registered — tabs 02 and 05 both are, in this PR and the last.
    pathname = "/macro/gold";

    render(<AppShell>Gold content</AppShell>);

    expect(screen.queryByRole("link", { name: /^Gold$/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /^Rates$/ })).toBeNull();
    const macro = screen.getByRole("link", { name: /Macro/ });
    // `startsWith` is what makes one entry cover nine tabs.
    expect(macro.className).toContain("linkActive");
  });
});
