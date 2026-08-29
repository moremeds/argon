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
import { Sidebar } from "@/components/shared/Sidebar";

describe("AppShell", () => {
  it("renders the Argon sidebar on normal routes", () => {
    pathname = "/";

    render(<AppShell>Dashboard content</AppShell>);

    expect(screen.getByText("ARGON")).toBeTruthy();
    expect(screen.getByRole("main").textContent).toContain("Dashboard content");
  });

  it("keeps the Argon sidebar and shifts an uncompressed macro canvas beside it", () => {
    pathname = "/macro/rates";

    const { container } = render(<AppShell>Rates content</AppShell>);

    expect(screen.getByText("ARGON")).toBeTruthy();
    expect(container.firstElementChild?.className).toContain("macroShell");
    expect(screen.getByRole("main").className).toContain("macroMain");
    expect(container.firstElementChild?.textContent).toContain("Rates content");
  });

  it("lists ONE macro entry, and highlights it for every tab under it", () => {
    // The sidebar collapse. Gold, Rates and Macro were three peers; `/gold` and `/rates`
    // both 308 into the desk now, so the two removed entries would have been links to
    // redirects. The plan's ordering rule is that a peer may only be removed once its
    // destination tab is registered — tabs 02 and 05 both are, in this PR and the last.
    pathname = "/macro/gold";

    render(<Sidebar />);

    expect(screen.queryByRole("link", { name: /^Gold$/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /^Rates$/ })).toBeNull();
    const macro = screen.getByRole("link", { name: /Macro/ });
    // `startsWith` is what makes one entry cover nine tabs.
    expect(macro.className).toContain("linkActive");
  });
});
