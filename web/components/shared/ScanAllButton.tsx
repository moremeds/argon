"use client";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

type Phase = "idle" | "enqueueing" | "polling" | "done" | "failed";

export function ScanAllButton() {
  const ref = useRef<HTMLDialogElement>(null);
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [pendingIds, setPendingIds] = useState<string[]>([]);
  const [total, setTotal] = useState(0);

  // Wall-clock deadline for the whole scan. Lives in a ref because the
  // effect below re-runs on every setPendingIds; a `const startedAt` inside
  // it reset the 10-minute limit every 2 s, so a zombie job polled forever.
  const deadlineAt = useRef<number | null>(null);

  useEffect(() => {
    if (phase !== "polling" || pendingIds.length === 0) return;
    if (deadlineAt.current === null) deadlineAt.current = Date.now() + 600_000;
    const t = setInterval(async () => {
      if (deadlineAt.current !== null && Date.now() > deadlineAt.current) {
        clearInterval(t);
        deadlineAt.current = null;
        setPhase("failed");
        router.refresh();
        return;
      }
      try {
        const results = await Promise.all(
          pendingIds.map((id) =>
            api
              .job(id)
              .catch(() => ({ job_id: id, status: "unknown" as const })),
          ),
        );
        // A rejected status read is NOT a finished job: keep it pending and
        // retry next tick. Only "done"/"failed" retire an id.
        const stillPending = results
          .filter((r) => r.status !== "done" && r.status !== "failed")
          .map((r) => r.job_id);
        setPendingIds(stillPending);
        if (stillPending.length === 0) {
          clearInterval(t);
          deadlineAt.current = null;
          const anyFailed = results.some((r) => r.status === "failed");
          setPhase(anyFailed ? "failed" : "done");
          router.refresh();
        }
      } catch (e) {
        console.error(e);
      }
    }, 2000);
    return () => clearInterval(t);
  }, [phase, pendingIds, router]);

  const start = async () => {
    ref.current?.close();
    setPhase("enqueueing");
    try {
      const jobs = await api.rescanAll();
      const ids = jobs.map((j) => j.job_id);
      setTotal(ids.length);
      setPendingIds(ids);
      setPhase(ids.length === 0 ? "done" : "polling");
    } catch (e) {
      console.error(e);
      setPhase("failed");
    }
  };

  const label =
    phase === "idle"
      ? "Scan all"
      : phase === "enqueueing"
        ? "queuing…"
        : phase === "polling"
          ? `scanning ${total - pendingIds.length}/${total}…`
          : phase === "done"
            ? `✓ scanned ${total}`
            : "✗ failed";

  return (
    <>
      <button
        onClick={() => ref.current?.showModal()}
        disabled={phase === "enqueueing" || phase === "polling"}
        style={{
          padding: "4px 10px",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          background: "transparent",
          color: "var(--text-secondary)",
          border: "1px solid var(--border-dim)",
          borderRadius: 3,
          cursor: phase === "polling" ? "wait" : "pointer",
        }}
      >
        {label}
      </button>
      <dialog
        ref={ref}
        aria-label="Scan all confirmation"
        className="uw-dialog"
        onClick={(e) => {
          if (e.target === e.currentTarget) ref.current?.close();
        }}
      >
        <div className="uw-dialog-panel" onClick={(e) => e.stopPropagation()}>
          <div className="uw-dialog-title">Scan All</div>
          <div className="uw-dialog-copy">
            Run a deep UW rescan for every active watchlist ticker. This can use
            a large number of provider requests.
          </div>
          <div className="uw-dialog-actions">
            <button
              type="button"
              className="uw-dialog-button uw-dialog-button-secondary"
              onClick={() => ref.current?.close()}
            >
              Cancel
            </button>
            <button
              type="button"
              className="uw-dialog-button uw-dialog-button-primary"
              aria-label="Confirm scan all"
              onClick={start}
            >
              Scan all
            </button>
          </div>
        </div>
      </dialog>
    </>
  );
}
