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
        style={{
          padding: 16,
          background: "var(--bg-panel)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-dim)",
        }}
      >
        <form
          onSubmit={submit}
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            minWidth: 280,
          }}
        >
          <input
            required
            placeholder="TICKER"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            style={{ fontFamily: "var(--font-mono)", padding: 4 }}
          />
          <select value={sector} onChange={(e) => setSector(e.target.value)}>
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
          />
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: 8,
            }}
          >
            <button type="button" onClick={() => ref.current?.close()}>
              Cancel
            </button>
            <button type="submit">Add</button>
          </div>
        </form>
      </dialog>
    </>
  );
}
