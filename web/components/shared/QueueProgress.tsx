"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { components } from "@/lib/types";
import { api } from "@/lib/api";

type QueueSummary = components["schemas"]["QueueSummary"];

export function QueueProgress({ queue }: { queue: QueueSummary }) {
  const router = useRouter();
  const [current, setCurrent] = useState(queue);

  useEffect(() => {
    setCurrent(queue);
  }, [queue.oldest_requested_at, queue.queued, queue.running, queue.total]);

  useEffect(() => {
    const delay = current.total > 0 ? 2500 : 5000;
    const t = setInterval(async () => {
      try {
        const next = await api.watchlist();
        setCurrent(next.queue);
        if (next.queue.total === 0) router.refresh();
      } catch (e) {
        console.error(e);
      }
    }, delay);
    return () => clearInterval(t);
  }, [current.total, router]);

  const total = current.total;
  const running = current.running;
  const queued = current.queued;
  const width = total > 0 ? Math.max(8, (running / total) * 100) : 0;

  return (
    <div
      aria-label="Rescan queue"
      style={{
        minWidth: 190,
        fontFamily: "var(--font-mono)",
        color: "var(--text-secondary)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 8,
          marginBottom: 4,
          fontSize: 10,
          whiteSpace: "nowrap",
        }}
      >
        <span>queue</span>
        <span>
          {total > 0 ? `${running} running · ${queued} queued` : "idle"}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label="Rescan queue progress"
        aria-valuemin={0}
        aria-valuenow={running}
        aria-valuemax={Math.max(total, 1)}
        style={{
          height: 4,
          background: "var(--border-dim)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${width}%`,
            background: total > 0 ? "var(--warning)" : "transparent",
          }}
        />
      </div>
    </div>
  );
}
