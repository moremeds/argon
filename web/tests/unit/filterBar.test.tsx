import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterBar } from "@/components/watchlist/FilterBar";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("FilterBar", () => {
  it("shows setup formula explanation in a compact popover", () => {
    render(<FilterBar current={{}} />);

    expect(screen.getByText("Setup")).toBeDefined();
    expect(screen.queryByText(/Flow direction/)).toBeNull();

    const trigger = screen.getByLabelText("Setup formula explanation");
    const hoverRegion = trigger.parentElement!;
    fireEvent.mouseEnter(hoverRegion);

    expect(screen.getByText(/Flow direction/)).toBeDefined();
    expect(screen.getByText(/net premium = net call premium/)).toBeDefined();
    expect(screen.getByText(/abs\(net premium\) >= \$5M/)).toBeDefined();
    expect(screen.getByText(/flow imbalance = abs\(net premium\)/)).toBeDefined();
    expect(screen.getByText(/F-MULTI = Type C base/)).toBeDefined();
    expect(screen.getByText(/IV rank is context/)).toBeDefined();

    fireEvent.mouseLeave(hoverRegion);

    expect(screen.queryByText(/Flow direction/)).toBeNull();
  });
});
