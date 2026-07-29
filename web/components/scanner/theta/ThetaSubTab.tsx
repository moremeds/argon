"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { components } from "@/lib/types";

type Candidate = components["schemas"]["ThetaHarvesterCandidate"];

const QUOTE_LIMIT = 8; // matches the API's IB line budget; see routers/scanner.py

export function verdictLabel(verdict: string): string {
  if (verdict === "THETA_HARVEST") return "TRUE THETA";
  if (verdict === "DIRECTIONAL_DISGUISE") return "DIRECTIONAL";
  if (verdict === "WATCHLIST") return "WATCH";
  return verdict;
}

export function formatDelta(d: number): string {
  // Position delta is per share; x100 is the per-contract share equivalent the
  // operator actually hedges. toFixed keeps the sign of a negative that rounds
  // to zero ("-0.0 sh"), so add 0 to normalise -0 on the one column whose whole
  // point is "this is flat".
  const sh = Number((d * 100).toFixed(1)) + 0;
  return `${sh > 0 ? "+" : ""}${sh.toFixed(1)} sh`;
}

export function formatTheta(theta: number): string {
  // Per contract, per day. Positive is the short position collecting decay.
  const v = theta * 100;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}/day`;
}

export function formatCredit(
  theo: number | null,
  ib: number | null | undefined,
): string {
  // The theo/IB suffix is load-bearing: the theoretical mark is the markout
  // basis and the IB quote is a live NBBO. A bare number would let a reader
  // treat a model price as a fill.
  if (ib != null) return `$${ib.toFixed(2)} IB`;
  if (theo != null) return `$${theo.toFixed(2)} theo`;
  return "—";
}

const GATE_KEYS: { key: keyof Candidate; label: string }[] = [
  { key: "gate_delta_near_zero", label: "DELTA" },
  { key: "gate_iv_rich_vs_rv", label: "IV RICH" },
  { key: "gate_dealer_support", label: "DEALER" },
  { key: "gate_theta_positive", label: "THETA" },
];

const COLUMNS: { label: string; hint: string }[] = [
  { label: "Ticker", hint: "Underlying symbol" },
  { label: "Structure", hint: "Short strangle legs, and which gates passed" },
  {
    label: "Score",
    hint: "Weighted vol-edge / delta-neutrality / range-bound score. Ranks within a session; it is not an expected return.",
  },
  {
    label: "Theta",
    hint: "Position theta per contract per day (BS, from grid IV)",
  },
  {
    label: "Net Delta",
    hint: "Position delta in share equivalents per contract",
  },
  {
    label: "IV/RV",
    hint: "ATM IV minus 20-day realised vol, in vol points, and their ratio",
  },
  {
    label: "Dealer",
    hint: "Dealer gamma support at spot. Non-critical by default — making it critical INVERTS the score's ranking.",
  },
  {
    label: "Range",
    hint: "How range-bound the last 21 sessions were (1.00 = fully)",
  },
  { label: "DTE", hint: "Calendar days to expiry" },
  {
    label: "Credit",
    hint: "Entry credit. 'theo' is the Black-Scholes markout basis; 'IB' is a live NBBO midpoint.",
  },
  { label: "Status", hint: "Verdict after all six gates" },
];

/** Filters applied client-side over the loaded session — no refetch. */
function useFiltered(
  rows: Candidate[],
  ticker: string,
  dteMin: string,
  dteMax: string,
  minCredit: string,
) {
  return useMemo(() => {
    const t = ticker.trim().toUpperCase();
    const lo = Number(dteMin);
    const hi = Number(dteMax);
    const cr = Number(minCredit);
    return rows.filter((c) => {
      if (t && !c.ticker.includes(t)) return false;
      if (Number.isFinite(lo) && dteMin !== "" && c.dte < lo) return false;
      if (Number.isFinite(hi) && dteMax !== "" && c.dte > hi) return false;
      if (Number.isFinite(cr) && minCredit !== "" && c.entry_credit_theo < cr) {
        return false;
      }
      return true;
    });
  }, [rows, ticker, dteMin, dteMax, minCredit]);
}

export default function ThetaSubTab({
  initial,
}: {
  // Server-rendered by the route, which already fetches this for the tab badge.
  // Seeding from it removes both the fetch-on-mount (a setState inside an
  // effect, which the lint rule rejects) and the duplicate request.
  initial?: { as_of: string | null; candidates: Candidate[] };
}) {
  const [rows, setRows] = useState<Candidate[]>(initial?.candidates ?? []);
  const [asOf, setAsOf] = useState<string | null>(initial?.as_of ?? null);
  const [busy, setBusy] = useState<"" | "scan" | "quote">("");
  const [error, setError] = useState<string | null>(null);

  const [ticker, setTicker] = useState("");
  const [dteMin, setDteMin] = useState("7");
  const [dteMax, setDteMax] = useState("45");
  const [minCredit, setMinCredit] = useState("0");
  const [clock, setClock] = useState("");

  // Rendered only after mount: a server-rendered wall clock would not match the
  // client's first paint and React would flag the hydration mismatch.
  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString("en-GB"));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const visible = useFiltered(rows, ticker, dteMin, dteMax, minCredit);
  const harvestCount = visible.filter(
    (c) => c.verdict === "THETA_HARVEST",
  ).length;

  const load = useCallback(async () => {
    try {
      const data = await api.thetaHarvester();
      setRows(data.candidates);
      setAsOf(data.as_of);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    }
  }, []);

  async function rescan() {
    setBusy("scan");
    try {
      await api.thetaHarvesterRescan();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "rescan failed");
    } finally {
      setBusy("");
    }
  }

  async function quote() {
    setBusy("quote");
    try {
      await api.thetaHarvesterQuote(QUOTE_LIMIT);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "quote failed");
    } finally {
      setBusy("");
    }
  }

  return (
    <div data-testid="theta-subtab">
      {/* The table COMMENT saying "research artifact, not a trade proposal" is
          invisible to whoever is looking at this screen, and a row labelled
          TRUE THETA beside a live IB credit reads as a recommendation. Two
          separate claims are made here on purpose: the structure is undefined
          risk (a rule violation), AND the score has no demonstrated edge (an
          empirical finding). Dropping either one leaves a misreading available. */}
      <div
        data-testid="theta-research-warning"
        style={{
          border: "1px solid var(--warn, #a86)",
          background: "var(--warn-bg, rgba(170,136,102,0.08))",
          padding: "8px 12px",
          marginBottom: 12,
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          lineHeight: 1.6,
        }}
      >
        <div style={{ letterSpacing: "0.05em" }}>
          RESEARCH ONLY — NOT AN ARGON TRADE PROPOSAL{" "}
          <span
            title={
              "Measured 2025-12-26 → 2026-07-27, 145 sessions, 16,134 candidates.\n\n" +
              "The ranking works: cross-sectional IC +0.075 (t 6.35) — higher-scored candidates did do better than lower-scored ones.\n\n" +
              "The trades still lose: held to expiry, the selected set was negative, and so was the control arm of every candidate with no score applied (monthly mean -0.8%, Sharpe -1.67). Ordering a losing set does not make it a winning one.\n\n" +
              "Full sweep and method: docs/research/2026-07-28-theta-harvester-weight-sweep.md"
            }
            style={{ cursor: "help", color: "var(--text-muted)" }}
          >
            (?)
          </span>
        </div>
        {/* Tailwind's preflight resets `list-style: none` globally, so the
            markers have to be asked for explicitly or the bullets render as
            three unlabelled lines. */}
        <ul style={{ margin: "6px 0 0", paddingLeft: 18, listStyle: "disc" }}>
          <li>
            These are naked short strangles — <strong>undefined risk</strong> on
            both sides. A big move either way has no capped loss.
          </li>
          <li>
            Nothing here is sized or executable. Credits are model marks or IB
            midpoints, not fills.
          </li>
          <li>
            The score <strong>ranks</strong> candidates well within a session,
            but the ones it picks still lost money held to expiry —{" "}
            <strong>no demonstrated edge</strong> after costs.
          </li>
        </ul>
      </div>

      <div className="theta-panel">
        <div className="theta-panel-bar">
          <span className="theta-panel-title">
            ✳ Theta Harvester
            <span
              className="theta-subtle"
              title="Short strangles ranked off the persisted option-surface grid. Zero UW cost — every column is computed from the warm store."
              style={{ cursor: "help" }}
            >
              (?)
            </span>
          </span>

          <span className="theta-clock" suppressHydrationWarning>
            {clock || "--:--:--"}
          </span>

          <span
            className="theta-count"
            title="Candidates passing every critical gate, after the filters below"
          >
            {harvestCount} TRUE THETA
          </span>

          <label className="theta-field">
            <input
              className="theta-input theta-input--ticker"
              placeholder="⌕ TICKER"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              aria-label="Filter by ticker"
            />
          </label>

          <span className="theta-field">
            DTE
            <input
              className="theta-input"
              value={dteMin}
              onChange={(e) => setDteMin(e.target.value)}
              aria-label="Minimum DTE"
            />
            –
            <input
              className="theta-input"
              value={dteMax}
              onChange={(e) => setDteMax(e.target.value)}
              aria-label="Maximum DTE"
            />
          </span>

          <span className="theta-field">
            Min Cr
            <input
              className="theta-input"
              value={minCredit}
              onChange={(e) => setMinCredit(e.target.value)}
              aria-label="Minimum credit"
            />
          </span>

          <button
            type="button"
            className="theta-action"
            onClick={rescan}
            disabled={busy !== ""}
            // Labelled RESCAN, not SCAN NDX: this re-runs the watchlist sweep.
            // It does not scan the Nasdaq-100.
            title="Re-run the scan across the watchlist and reload"
          >
            ↻ {busy === "scan" ? "Scanning…" : "Rescan"}
          </button>

          <button
            type="button"
            className="theta-action"
            onClick={quote}
            disabled={busy !== "" || !visible.length}
            title={`Fetch live IB NBBO for the top ${QUOTE_LIMIT} candidates. Serial, and bounded by the shared IB line budget.`}
          >
            {busy === "quote" ? "Quoting…" : `Quote ${QUOTE_LIMIT} (IB)`}
          </button>

          <span className="theta-subtle" style={{ marginLeft: "auto" }}>
            {asOf ? `AS OF ${asOf}` : "NO DATA"} · {visible.length}/
            {rows.length}
          </span>
        </div>

        {error ? (
          <p style={{ color: "var(--negative)", padding: "12px 18px" }}>
            {error}
          </p>
        ) : null}

        {visible.length === 0 ? (
          <div className="theta-empty">
            {rows.length === 0
              ? "No candidates for this session."
              : "No candidates match the current filters."}
          </div>
        ) : (
          <div className="theta-scroll">
            <table className="theta-table">
              <thead>
                <tr>
                  {COLUMNS.map((c) => (
                    <th key={c.label} title={c.hint}>
                      {c.label} <span className="theta-subtle">(?)</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((c) => (
                  <tr key={`${c.ticker}-${c.as_of}`}>
                    <td>{c.ticker}</td>
                    <td>
                      {`SHORT ${c.put_strike}P / ${c.call_strike}C`}
                      <div className="theta-chips">
                        {GATE_KEYS.map((g) => (
                          <span
                            key={g.label}
                            className={`theta-chip ${c[g.key] ? "" : "theta-chip--off"}`}
                          >
                            {g.label}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>{c.score.toFixed(1)}</td>
                    <td>{formatTheta(c.theta)}</td>
                    <td>{formatDelta(c.net_delta)}</td>
                    <td>
                      {c.iv_rv_edge != null
                        ? `${c.iv_rv_edge > 0 ? "+" : ""}${c.iv_rv_edge.toFixed(1)} pt`
                        : "—"}
                      <div className="theta-subtle">
                        {c.iv_rv_ratio != null
                          ? `${c.iv_rv_ratio.toFixed(2)}x`
                          : ""}
                      </div>
                    </td>
                    <td>{c.dealer_support ?? "—"}</td>
                    <td>
                      {c.range_score != null
                        ? `RANGE ${(c.range_score * 100).toFixed(0)}%`
                        : "—"}
                    </td>
                    <td>{c.dte}</td>
                    <td>{formatCredit(c.entry_credit_theo, c.credit_ib)}</td>
                    <td>
                      <span
                        className={`theta-status ${
                          c.verdict === "THETA_HARVEST"
                            ? "theta-status--harvest"
                            : ""
                        }`}
                      >
                        {verdictLabel(c.verdict)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
