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
        className="uw-dialog uw-dialog-compact"
        onClick={(e) => {
          if (e.target === e.currentTarget) close();
        }}
      >
        <form
          onSubmit={submit}
          onClick={(e) => e.stopPropagation()}
          className="uw-dialog-panel"
        >
          <div className="uw-dialog-title">Add Ticker</div>
          <input
            required
            placeholder="TICKER"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            className="uw-dialog-field"
          />
          <select
            value={sector}
            onChange={(e) => setSector(e.target.value)}
            className="uw-dialog-field"
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
            className="uw-dialog-field"
          />
          <div className="uw-dialog-actions">
            <button
              type="button"
              onClick={close}
              className="uw-dialog-button uw-dialog-button-secondary"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="uw-dialog-button uw-dialog-button-primary"
            >
              Add
            </button>
          </div>
        </form>
      </dialog>
    </>
  );
}
