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

  it("renders /rates inside the normal Argon shell", () => {
    pathname = "/rates";

    render(<AppShell>Rates content</AppShell>);

    expect(screen.getByText("ARGON")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Rates/ })).toBeTruthy();
    const main = screen.getByRole("main");
    expect(main.textContent).toContain("Rates content");
    expect(main.className).toContain("main");
  });
});
