/* @vitest-environment jsdom */
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ScanAllButton } from "@/components/shared/ScanAllButton";
import { api } from "@/lib/api";

const { router } = vi.hoisted(() => ({ router: { refresh: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/lib/api", () => ({
  api: { job: vi.fn(), rescanAll: vi.fn() },
}));

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.mocked(api.rescanAll).mockResolvedValue([{ job_id: "mock-job" }] as never);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function startScan() {
  render(<ScanAllButton />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /^scan all$/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm scan all/i }));
  });
}

async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

it("gives up after 10 minutes of a job that never finishes", async () => {
  vi.mocked(api.job).mockResolvedValue({
    job_id: "mock-job",
    status: "running",
  } as never);
  await startScan();
  for (let i = 0; i < 301; i++) await tick(2000);
  // 300 polls fit inside 600 s; the 301st tick is past the deadline and must bail.
  expect(vi.mocked(api.job).mock.calls.length).toBeLessThanOrEqual(300);
  expect(screen.getByRole("button", { name: /failed/i })).toBeTruthy();
  expect(router.refresh).toHaveBeenCalledOnce();
  const calls = vi.mocked(api.job).mock.calls.length;
  await tick(10_000);
  expect(vi.mocked(api.job).mock.calls.length).toBe(calls); // no polling after bail
});

it("keeps polling when the status GET fails instead of reporting success", async () => {
  vi.mocked(api.job).mockRejectedValue(
    new Error("mock status transport unavailable"),
  );
  await startScan();
  await tick(2000);
  expect(screen.queryByRole("button", { name: /scanned/ })).toBeNull();
  expect(screen.getByRole("button", { name: /scanning 0\/1/ })).toBeTruthy();
  expect(router.refresh).not.toHaveBeenCalled();
  await tick(2000);
  expect(api.job).toHaveBeenCalledTimes(2); // still polling the same id
});

it("ends failed, not done, when status GETs fail for the whole deadline", async () => {
  vi.mocked(api.job).mockRejectedValue(new Error("down"));
  await startScan();
  for (let i = 0; i < 301; i++) await tick(2000);
  expect(screen.getByRole("button", { name: /failed/i })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /scanned/ })).toBeNull();
});
