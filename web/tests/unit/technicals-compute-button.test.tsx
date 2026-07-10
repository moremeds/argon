import { render, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TechnicalsEmptyState } from "@/components/stock/panels/TechnicalsEmptyState";
import { api, type TechnicalsResponse } from "@/lib/api";

describe("TechnicalsEmptyState", () => {
  it("renders a Compute now button", () => {
    const { getByRole } = render(
      <TechnicalsEmptyState ticker="IWM" onComputed={() => {}} />,
    );
    expect(getByRole("button", { name: /compute now/i })).toBeTruthy();
  });

  it("calls the refresh fetcher and fires onComputed with the ready payload", async () => {
    const ready = {
      ticker: "IWM",
      backfill_status: "ready",
      series: [],
      detail: {},
    } as unknown as TechnicalsResponse;
    const spy = vi.spyOn(api, "technicalsRefresh").mockResolvedValue(ready);
    const onComputed = vi.fn();
    const { getByRole } = render(
      <TechnicalsEmptyState ticker="IWM" onComputed={onComputed} />,
    );
    fireEvent.click(getByRole("button", { name: /compute now/i }));
    await waitFor(() => expect(onComputed).toHaveBeenCalledWith(ready));
    expect(spy).toHaveBeenCalledWith("IWM");
  });

  it("shows a note (not onComputed) when compute comes back empty", async () => {
    vi.spyOn(api, "technicalsRefresh").mockResolvedValue({
      ticker: "IWM",
      backfill_status: "empty",
    } as unknown as TechnicalsResponse);
    const onComputed = vi.fn();
    const { getByRole, findByText } = render(
      <TechnicalsEmptyState ticker="IWM" onComputed={onComputed} />,
    );
    fireEvent.click(getByRole("button", { name: /compute now/i }));
    await findByText(/thin history or apex unreachable/i);
    expect(onComputed).not.toHaveBeenCalled();
  });
});
