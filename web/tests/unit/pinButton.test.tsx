/* @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PinButton } from "@/components/watchlist/PinButton";
import { api } from "@/lib/api";

const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

vi.mock("@/lib/api", () => ({
  api: {
    patchTicker: vi.fn(),
  },
}));

beforeEach(() => {
  vi.mocked(api.patchTicker).mockResolvedValue({ ok: true, ticker: "AAPL" });
  refresh.mockReset();
});

afterEach(() => {
  vi.mocked(api.patchTicker).mockReset();
});

describe("PinButton", () => {
  it("renders 'Pin <ticker>' label and aria-pressed=false when unpinned", () => {
    render(<PinButton ticker="AAPL" pinned={false} />);
    const btn = screen.getByRole("button", { name: "Pin AAPL" });
    expect(btn.getAttribute("aria-pressed")).toBe("false");
  });

  it("renders 'Unpin <ticker>' label and aria-pressed=true when pinned", () => {
    render(<PinButton ticker="AAPL" pinned={true} />);
    const btn = screen.getByRole("button", { name: "Unpin AAPL" });
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });

  it("calls patchTicker with toggled value and refreshes router on click", async () => {
    render(<PinButton ticker="AAPL" pinned={false} />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => {
      expect(api.patchTicker).toHaveBeenCalledWith("AAPL", { pinned: true });
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("toggles in the unpin direction when already pinned", async () => {
    render(<PinButton ticker="AAPL" pinned={true} />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => {
      expect(api.patchTicker).toHaveBeenCalledWith("AAPL", { pinned: false });
    });
  });

  it("does not refresh when the request fails", async () => {
    vi.mocked(api.patchTicker).mockRejectedValueOnce(new Error("boom"));
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(<PinButton ticker="AAPL" pinned={false} />);
    fireEvent.click(screen.getByRole("button"));

    await waitFor(() => {
      expect(api.patchTicker).toHaveBeenCalled();
    });
    expect(refresh).not.toHaveBeenCalled();
    errSpy.mockRestore();
  });
});
