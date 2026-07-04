"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Flame } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Per-card "hot" toggle — sibling of PinButton. A hot ticker joins the
 * tight-freshness intraday full_scan subset (fast lane). The budget governor
 * caps how many hot names actually get the fast cadence; the CardGrid hot-slots
 * meter shows the count vs the soft cap.
 */
export function HotButton({ ticker, hot }: { ticker: string; hot: boolean }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  const toggle = async () => {
    if (pending) return;
    setPending(true);
    try {
      await api.patchTicker(ticker, { hot: !hot });
      router.refresh();
    } catch (err) {
      console.error(err);
    } finally {
      setPending(false);
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={pending}
      aria-label={hot ? `Unmark ${ticker} hot` : `Mark ${ticker} hot`}
      aria-pressed={hot}
      title={hot ? "Hot — fast-lane refresh (click to remove)" : "Mark hot (fast-lane intraday refresh)"}
      style={{
        background: "transparent",
        border: 0,
        cursor: pending ? "wait" : "pointer",
        padding: 4,
        marginRight: 4,
        color: hot ? "var(--accent-warm)" : "var(--text-muted)",
        opacity: pending ? 0.5 : 1,
        display: "inline-flex",
        alignItems: "center",
      }}
    >
      <Flame size={14} fill={hot ? "currentColor" : "none"} />
    </button>
  );
}
