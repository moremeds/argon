"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

type Status = "idle" | "queued" | "running" | "done" | "failed";

export function RescanButton({ ticker }: { ticker: string }) {
  const router = useRouter();
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("idle");

  useEffect(() => {
    if (!jobId) return;
    const t = setInterval(async () => {
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
        const r = await api.rescan(ticker);
        setJobId(r.job_id);
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
