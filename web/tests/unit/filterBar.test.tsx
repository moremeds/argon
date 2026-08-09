import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FilterBar } from "@/components/watchlist/FilterBar";
import {
  buildSectorGroups,
  groupForChain,
} from "@/components/watchlist/sectorGroups";
import type { WatchlistChainInfo } from "@/lib/api";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));

beforeEach(() => {
  push.mockClear();
});

/** Shaped like a real /api/watchlist/chains payload, counts included. */
const CHAINS: WatchlistChainInfo[] = [
  {
    layer: "IDX",
    layer_name: "Index & Macro",
    focus: "Index & Macro",
    chain: "Beta",
    count: 4,
  },
  {
    layer: "IDX",
    layer_name: "Index & Macro",
    focus: "Index & Macro",
    chain: "Macro",
    count: 3,
  },
  {
    layer: "X",
    layer_name: "Cross-cutting",
    focus: "AI",
    chain: "M7",
    count: 7,
  },
  {
    layer: "L1",
    layer_name: "Chip & System",
    focus: "AI",
    chain: "Computer/GPU",
    count: 7,
  },
  {
    layer: "L1",
    layer_name: "Chip & System",
    focus: "AI",
    chain: "Foundry",
    count: 4,
  },
  {
    layer: "L5",
    layer_name: "Model & Tooling",
    focus: "AI",
    chain: "Foundation-Model-Proxy",
    count: 5,
  },
  // Zero members — must not render a button that filters to an empty grid.
  {
    layer: "L3",
    layer_name: "Datacenter Infrastructure",
    focus: "AI",
    chain: "EPC/Construction",
    count: 0,
  },
];

const groups = buildSectorGroups(CHAINS);

describe("buildSectorGroups", () => {
  it("drops chains with no members", () => {
    const all = groups.flatMap((g) => g.items);
    expect(all).toContain("Computer/GPU");
    expect(all).not.toContain("EPC/Construction");
  });

  it("leads with Index and M7 regardless of payload order", () => {
    expect(groups.map((g) => g.label).slice(0, 2)).toEqual(["Index", "M7"]);
  });

  it("surfaces the Model layer once its chain has members", () => {
    const model = groups.find((g) => g.label === "Model");
    expect(model?.items).toEqual(["Foundation-Model-Proxy"]);
  });

  it("treats a single self-named chain as a leaf", () => {
    expect(groups.find((g) => g.label === "M7")?.leaf).toBe(true);
    expect(groups.find((g) => g.label === "Chip")?.leaf).toBe(false);
  });
});

describe("groupForChain", () => {
  it("maps a chain back to its layer", () => {
    expect(groupForChain(groups, "Computer/GPU")?.label).toBe("Chip");
    expect(groupForChain(groups, "Foundation-Model-Proxy")?.label).toBe(
      "Model",
    );
  });

  it("treats absent and All as unfiltered", () => {
    expect(groupForChain(groups, undefined)).toBeUndefined();
    expect(groupForChain(groups, "All")).toBeUndefined();
  });
});

describe("FilterBar", () => {
  it("shows setup formula explanation in a compact popover", () => {
    render(<FilterBar current={{}} groups={groups} />);

    expect(screen.getByText("Setup")).toBeDefined();
    expect(screen.queryByText(/Flow direction/)).toBeNull();

    const trigger = screen.getByLabelText("Setup formula explanation");
    const hoverRegion = trigger.parentElement!;
    fireEvent.mouseEnter(hoverRegion);

    expect(screen.getByText(/Flow direction/)).toBeDefined();
    expect(screen.getByText(/F-MULTI = Type C base/)).toBeDefined();

    fireEvent.mouseLeave(hoverRegion);
    expect(screen.queryByText(/Flow direction/)).toBeNull();
  });

  it("opens a layer's chain row without applying a filter", () => {
    render(<FilterBar current={{}} groups={groups} />);

    expect(screen.getByText("Beta")).toBeDefined();
    expect(screen.queryByText("Computer/GPU")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Chip" }));

    expect(screen.getByText("Computer/GPU")).toBeDefined();
    expect(screen.queryByText("Beta")).toBeNull();
    expect(push).not.toHaveBeenCalled(); // browsing is not filtering
  });

  it("filters on ?chain= not ?sector=", () => {
    render(<FilterBar current={{}} groups={groups} />);
    fireEvent.click(screen.getByText("Beta"));
    expect(push).toHaveBeenCalledWith("/?chain=Beta");
  });

  it("filters directly from the rail for leaf groups", () => {
    render(<FilterBar current={{}} groups={groups} />);
    fireEvent.click(screen.getByRole("button", { name: "M7" }));
    expect(push).toHaveBeenCalledWith("/?chain=M7");
  });

  it("opens the group holding the active chain on load", () => {
    render(
      <FilterBar
        current={{ chain: "Foundation-Model-Proxy" }}
        groups={groups}
      />,
    );

    expect(
      screen
        .getByRole("button", { name: "Model" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("renders member counts when supplied", () => {
    render(
      <FilterBar current={{}} groups={groups} counts={{ Beta: 4, Macro: 3 }} />,
    );
    expect(screen.getByText("Beta 4")).toBeDefined();
  });

  it("renders nothing when the rail is empty rather than crashing", () => {
    const { container } = render(<FilterBar current={{}} groups={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
