"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Pin } from "lucide-react";
import { api } from "@/lib/api";

export function PinButton({
  ticker,
  pinned,
}: {
  ticker: string;
  pinned: boolean;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  const toggle = async () => {
    if (pending) return;
    setPending(true);
    try {
      await api.patchTicker(ticker, { pinned: !pinned });
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
      aria-label={pinned ? `Unpin ${ticker}` : `Pin ${ticker}`}
      aria-pressed={pinned}
      title={pinned ? "Unpin" : "Pin to top of sector"}
      style={{
        background: "transparent",
        border: 0,
        cursor: pending ? "wait" : "pointer",
        padding: 4,
        marginRight: 4,
        color: pinned ? "var(--warning)" : "var(--text-muted)",
        opacity: pending ? 0.5 : 1,
        display: "inline-flex",
        alignItems: "center",
      }}
    >
      <Pin size={14} fill={pinned ? "currentColor" : "none"} />
    </button>
  );
}
