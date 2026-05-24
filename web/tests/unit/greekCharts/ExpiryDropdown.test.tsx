import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ExpiryDropdown } from "@/components/stock/panels/greeks/ExpiryDropdown";

describe("ExpiryDropdown", () => {
  it("renders one option per expiry with dte annotation", () => {
    render(
      <ExpiryDropdown
        options={[
          { value: "2026-05-30", label: "2026-05-30 (9d)" },
          { value: "2026-06-20", label: "2026-06-20 (30d)" },
        ]}
        value="2026-05-30"
        onChange={() => {}}
      />,
    );
    const opts = screen.getAllByRole("option");
    expect(opts).toHaveLength(2);
    expect(opts[0].textContent).toContain("2026-05-30");
    expect(opts[0].textContent).toContain("9d");
    expect(opts[0].getAttribute("aria-selected")).toBe("true");
    expect(opts[1].getAttribute("aria-selected")).toBe("false");
  });

  it("fires onChange with the new value", () => {
    const handle = vi.fn();
    render(
      <ExpiryDropdown
        options={[
          { value: "a", label: "A" },
          { value: "b", label: "B" },
        ]}
        value="a"
        onChange={handle}
      />,
    );
    fireEvent.click(screen.getByRole("option", { name: "B" }));
    expect(handle).toHaveBeenCalledWith("b");
  });
});
