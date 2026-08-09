"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronDown } from "lucide-react";
import { api } from "@/lib/api";
import { sectorRowsFromChains } from "./sectorGroups";
import type { WatchlistChainInfo } from "@/lib/api";

function SectorMenu({
  value,
  onChange,
  rows,
}: {
  value: string;
  onChange: (sector: string) => void;
  rows: { label: string; items: string[] }[];
}) {
  const [open, setOpen] = useState(false);

  return (
    <div
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
      style={{ position: "relative" }}
    >
      <button
        type="button"
        aria-label={`Sector ${value}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((next) => !next)}
        className="uw-dialog-field"
        style={{
          width: "100%",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          textAlign: "left",
          cursor: "pointer",
        }}
      >
        <span>{value}</span>
        <ChevronDown
          size={14}
          aria-hidden="true"
          style={{
            color: "var(--text-secondary)",
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 120ms ease",
          }}
        />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Sector"
          tabIndex={-1}
          style={{
            marginTop: 6,
            maxHeight: 320,
            overflowY: "auto",
            padding: 6,
            background: "var(--bg-panel)",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            boxShadow: "0 18px 40px rgba(0, 0, 0, 0.45)",
          }}
        >
          {rows.map((row) => {
            const sectors = row.items.filter((item) => item !== "All");
            if (sectors.length === 0) return null;

            return (
              <div key={row.label}>
                <div
                  style={{
                    padding: "8px 8px 5px",
                    color: "var(--text-muted)",
                    fontFamily: "var(--font-mono)",
                    fontSize: 10,
                    letterSpacing: 1,
                    textTransform: "uppercase",
                  }}
                >
                  {row.label}
                </div>
                {sectors.map((sector) => {
                  const selected = sector === value;
                  return (
                    <button
                      key={sector}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        onChange(sector);
                        setOpen(false);
                      }}
                      style={{
                        width: "100%",
                        display: "grid",
                        gridTemplateColumns: "18px 1fr",
                        gap: 6,
                        alignItems: "center",
                        padding: "7px 8px",
                        background: selected ? "var(--accent-bg)" : "transparent",
                        color: selected
                          ? "var(--accent-text)"
                          : "var(--text-primary)",
                        border: 0,
                        borderRadius: 3,
                        fontFamily: "var(--font-mono)",
                        fontSize: 12,
                        textAlign: "left",
                        cursor: "pointer",
                      }}
                    >
                      <span>
                        {selected && <Check size={13} aria-hidden="true" />}
                      </span>
                      <span>{sector}</span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function AddTickerDialog({
  chains = [],
}: {
  // The dialog still writes the single `watchlist.sector` column, so it needs
  // the chain list as a flat picker. Passed in rather than fetched so the
  // header does not fire a second request on every dashboard render.
  chains?: WatchlistChainInfo[];
}) {
  const rows = sectorRowsFromChains(chains);
  const ref = useRef<HTMLDialogElement>(null);
  const router = useRouter();
  const [ticker, setTicker] = useState("");
  const [sector, setSector] = useState("");
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
          <SectorMenu rows={rows} value={sector} onChange={setSector} />
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
