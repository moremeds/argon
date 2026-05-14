"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

const SECTORS = [
  "Technology",
  "Financials",
  "Healthcare",
  "Consumer Discretionary",
  "Communication Services",
  "Energy",
  "Industrials",
  "Consumer Staples",
  "ETF",
];

export function AddTickerDialog() {
  const ref = useRef<HTMLDialogElement>(null);
  const router = useRouter();
  const [ticker, setTicker] = useState("");
  const [sector, setSector] = useState(SECTORS[0]);
  const [notes, setNotes] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    await api.addTicker({ ticker: ticker.toUpperCase(), sector, notes });
    ref.current?.close();
    setTicker("");
    setNotes("");
    router.refresh();
  };

  const close = () => ref.current?.close();

  return (
    <>
      <button
        onClick={() => ref.current?.showModal()}
        style={{
          padding: "4px 10px",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          background: "var(--accent-bg)",
          color: "var(--accent-text)",
          border: 0,
          borderRadius: 3,
          cursor: "pointer",
        }}
      >
        + Ticker
      </button>
      <dialog
        ref={ref}
        aria-label="Add ticker"
        onClick={(e) => {
          if (e.target === e.currentTarget) close();
        }}
        style={{
          padding: 0,
          background: "var(--bg-panel)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
          boxShadow: "0 24px 64px rgba(0, 0, 0, 0.36)",
        }}
      >
        <form
          onSubmit={submit}
          onClick={(e) => e.stopPropagation()}
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 12,
            minWidth: 320,
            padding: 16,
          }}
        >
          <div
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              fontWeight: 700,
              letterSpacing: 1,
              textTransform: "uppercase",
            }}
          >
            Add Ticker
          </div>
          <input
            required
            placeholder="TICKER"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            style={{
              fontFamily: "var(--font-mono)",
              padding: "8px 10px",
              background: "var(--bg-base)",
              color: "var(--text-primary)",
              border: "1px solid var(--border-dim)",
              borderRadius: 3,
            }}
          />
          <select
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            style={{
              fontFamily: "var(--font-mono)",
              padding: "8px 10px",
              background: "var(--bg-base)",
              color: "var(--text-primary)",
              border: "1px solid var(--border-dim)",
              borderRadius: 3,
            }}
          >
            {SECTORS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <input
            placeholder="notes (optional)"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            style={{
              fontFamily: "var(--font-mono)",
              padding: "8px 10px",
              background: "var(--bg-base)",
              color: "var(--text-primary)",
              border: "1px solid var(--border-dim)",
              borderRadius: 3,
            }}
          />
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: 8,
            }}
          >
            <button
              type="button"
              onClick={close}
              style={{
                padding: "6px 10px",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                background: "transparent",
                color: "var(--text-secondary)",
                border: "1px solid var(--border-dim)",
                borderRadius: 3,
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              style={{
                padding: "6px 12px",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                background: "var(--accent-bg)",
                color: "var(--accent-text)",
                border: 0,
                borderRadius: 3,
                cursor: "pointer",
              }}
            >
              Add
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
