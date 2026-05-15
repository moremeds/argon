"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { components } from "@/lib/types";

type Status = "idle" | "queued" | "running" | "done" | "failed";
type QueueStatus = components["schemas"]["QueueStatus"];

export function RescanButton({
  ticker,
  initialJob,
}: {
  ticker: string;
  initialJob?: QueueStatus | null;
}) {
  const router = useRouter();
  const [jobId, setJobId] = useState<string | null>(initialJob?.job_id ?? null);
  const [status, setStatus] = useState<Status>(
    (initialJob?.status as Status | undefined) ?? "idle",
  );

  useEffect(() => {
    if (!jobId) return;
    // Self-cancel after 60s so a zombie 'running' job (worker crashed mid-scan)
    // doesn't keep polling forever and refreshing the page.
    const startedAt = Date.now();
    const t = setInterval(async () => {
      if (Date.now() - startedAt > 60_000) {
        clearInterval(t);
        setStatus("failed");
        return;
      }
      try {
        const r = await api.job(jobId);
        setStatus(r.status as Status);
        if (r.status === "done" || r.status === "failed") {
          clearInterval(t);
          if (r.status === "done") router.refresh();
        }
      } catch (e) {
        console.error(e);
      }
    }, 1000);
    return () => clearInterval(t);
  }, [jobId, router]);

  return (
    <button
      onClick={async (e) => {
        e.preventDefault();
        e.stopPropagation();
        setStatus("queued");
        try {
          const r = await api.rescan(ticker);
          setStatus(r.status as Status);
          setJobId(r.job_id);
        } catch (err) {
          console.error(err);
          setStatus("failed");
        }
      }}
      disabled={status === "queued" || status === "running"}
      style={{
        fontSize: 10,
        fontFamily: "var(--font-mono)",
        padding: "2px 6px",
        background: "transparent",
        color: "var(--text-secondary)",
        border: "1px solid var(--border-dim)",
        borderRadius: 2,
        cursor: "pointer",
      }}
    >
      {status === "idle"
        ? "rescan"
        : status === "queued"
          ? "queued…"
          : status === "running"
            ? "running…"
            : status === "done"
              ? "✓ done"
              : "✗ failed"}
    </button>
  );
}
