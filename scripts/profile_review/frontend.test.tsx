// Reproduction tests intentionally assert baseline defects, not desired behavior.
// All job IDs/statuses and empty spot responses are mock service data.
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ScanAllButton } from "@/components/shared/ScanAllButton";
import { LiveSpotsProvider } from "@/components/watchlist/LiveSpotsProvider";
import { api } from "@/lib/api";

const { router } = vi.hoisted(() => ({ router: { refresh: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/lib/api", () => ({ api: { job: vi.fn(), rescanAll: vi.fn(), watchlistSpots: vi.fn() } }));

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  vi.mocked(api.rescanAll).mockResolvedValue([{ job_id: "mock-job" }] as never);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

async function startScan() {
  render(<ScanAllButton />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /^scan all$/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm scan all/i }));
  });
}

it("reproduces deadline reset: still polling after 602 seconds with unchanged running ID", async () => {
  vi.mocked(api.job).mockResolvedValue({ job_id: "mock-job", status: "running" } as never);
  await startScan();
  for (let i = 0; i < 301; i++) await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(api.job).toHaveBeenCalledTimes(301);
  expect(screen.getByRole("button", { name: "scanning 0/1…" })).toBeTruthy();
  expect(router.refresh).not.toHaveBeenCalled();
  console.log(JSON.stringify({ proof: "scan-deadline-reset", simulatedElapsedMs: 602000, jobReads: 301, displayed: "scanning 0/1…" }));
});

it("reproduces rejected status GET falsely reporting scanned", async () => {
  vi.mocked(api.job).mockRejectedValue(new Error("mock status transport unavailable"));
  await startScan();
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(screen.getByRole("button", { name: "✓ scanned 1" })).toBeTruthy();
  expect(router.refresh).toHaveBeenCalledOnce();
  console.log(JSON.stringify({ proof: "scan-read-failure-false-success", rejectedReads: 1, displayed: "✓ scanned 1" }));
});

it("reproduces overlapping spot reads when response exceeds polling period", async () => {
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
  const pending: Array<(value: { spots: [] }) => void> = [];
  vi.mocked(api.watchlistSpots).mockImplementation(() => new Promise(resolve => pending.push(resolve)));
  render(<LiveSpotsProvider><span>mock empty spots</span></LiveSpotsProvider>);
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(api.watchlistSpots).toHaveBeenCalledTimes(3);
  expect(pending).toHaveLength(3);
  console.log(JSON.stringify({ proof: "spot-overlap", simulatedElapsedMs: 5000, concurrentUnresolvedReads: pending.length }));
  await act(async () => { pending.forEach(resolve => resolve({ spots: [] })); });
});
