import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FilterBar } from "@/components/watchlist/FilterBar";
import { groupForSector } from "@/components/watchlist/sectorGroups";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));

beforeEach(() => {
  push.mockClear();
});

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

  it("opens a layer's chain row without applying a filter", () => {
    render(<FilterBar current={{}} />);

    // Index is open by default, so its chains are the ones on screen.
    expect(screen.getByText("Beta")).toBeDefined();
    expect(screen.queryByText("Semi-Logic")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Chip" }));

    expect(screen.getByText("Semi-Logic")).toBeDefined();
    expect(screen.queryByText("Beta")).toBeNull();
    // Browsing a layer is not filtering by it.
    expect(push).not.toHaveBeenCalled();
  });

  it("filters directly from the rail for leaf groups", () => {
    render(<FilterBar current={{}} />);

    fireEvent.click(screen.getByRole("button", { name: "M7" }));

    expect(push).toHaveBeenCalledWith("/?sector=M7");
  });

  it("opens the group holding the active sector on load", () => {
    render(<FilterBar current={{ sector: "Semi-Cap" }} />);

    // Chip's chains are visible even though nothing was clicked...
    expect(screen.getByText("Semi-Logic")).toBeDefined();
    // ...and the rail marks Chip as holding the filter.
    expect(
      screen.getByRole("button", { name: "Chip" }).getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("toggles a chain off when it is already the active filter", () => {
    render(<FilterBar current={{ sector: "Beta" }} />);

    fireEvent.click(screen.getByText("Beta"));

    expect(push).toHaveBeenCalledWith("/?");
  });
});

describe("groupForSector", () => {
  it("maps a chain tag back to its layer", () => {
    expect(groupForSector("Semi-Cap")?.key).toBe("chip");
    expect(groupForSector("NeoCloud")?.key).toBe("cloud");
    expect(groupForSector("Healthcare")?.key).toBe("defensive");
  });

  it("treats absent and All as unfiltered", () => {
    expect(groupForSector(undefined)).toBeUndefined();
    expect(groupForSector("All")).toBeUndefined();
  });
});
