import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ExpiryDropdown } from "@/components/stock/panels/greeks/ExpiryDropdown";

describe("ExpiryDropdown", () => {
  it("renders one <option> per expiry with dte annotation", () => {
    const { container } = render(
      <ExpiryDropdown
        options={[
          { value: "2026-05-30", label: "2026-05-30 (9d)" },
          { value: "2026-06-20", label: "2026-06-20 (30d)" },
        ]}
        value="2026-05-30"
        onChange={() => {}}
      />,
    );
    const opts = container.querySelectorAll("option");
    expect(opts).toHaveLength(2);
    expect(opts[0].textContent).toContain("2026-05-30");
    expect(opts[0].textContent).toContain("9d");
  });

  it("fires onChange with the new value", () => {
    const handle = vi.fn();
    const { container } = render(
      <ExpiryDropdown
        options={[
          { value: "a", label: "A" },
          { value: "b", label: "B" },
        ]}
        value="a"
        onChange={handle}
      />,
    );
    const select = container.querySelector("select")!;
    fireEvent.change(select, { target: { value: "b" } });
    expect(handle).toHaveBeenCalledWith("b");
  });
});
