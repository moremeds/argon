"use client";

import { useCallback, useState } from "react";
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
  // toFixed keeps the sign of a negative that rounds to zero, so a delta of
  // -0.0001 renders as "-0.000" — which reads as a formatting bug on the one
  // column whose whole point is "this is flat". Adding 0 normalises -0 to 0.
  return (Number(d.toFixed(3)) + 0).toFixed(3);
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
          fontSize: 12,
          lineHeight: 1.6,
        }}
      >
        RESEARCH MEASUREMENT ONLY — naked short strangle, undefined risk on both
        sides. Not an Argon trade proposal, not sized, not executable. Credits
        shown are model marks or IB midpoints, not fills.
        <br />
        The score <strong>ranks</strong> candidates within a session (IC +0.075,
        145 sessions) but the set it selects is <strong>not profitable</strong>{" "}
        on its own — no demonstrated edge after costs. Held-to-expiry short
        strangles LOST money over the measured window. See{" "}
        <code>docs/research/2026-07-28-theta-harvester-weight-sweep.md</code>.
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginBottom: 12,
        }}
      >
        <span
          style={{ color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}
        >
          {asOf ? `AS OF ${asOf}` : "NO DATA"} · {rows.length} candidates
        </span>
        <button type="button" onClick={rescan} disabled={busy !== ""}>
          {busy === "scan" ? "Scanning…" : "Rescan"}
        </button>
        <button
          type="button"
          onClick={quote}
          disabled={busy !== "" || !rows.length}
        >
          {busy === "quote" ? "Quoting…" : `Quote top ${QUOTE_LIMIT} (IB)`}
        </button>
      </div>

      {error ? <p style={{ color: "var(--negative)" }}>{error}</p> : null}

      <table
        style={{ width: "100%", fontFamily: "var(--font-mono)", fontSize: 13 }}
      >
        <thead>
          <tr style={{ textAlign: "left", color: "var(--text-muted)" }}>
            <th>Ticker</th>
            <th>Structure</th>
            <th>Score</th>
            <th>Theta $/day</th>
            <th>Net Δ</th>
            <th>IV−RV</th>
            <th>Dealer</th>
            <th>Range</th>
            <th>DTE</th>
            <th>Credit</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={`${c.ticker}-${c.as_of}`}>
              <td>{c.ticker}</td>
              <td>
                {`SHORT ${c.put_strike}P / ${c.call_strike}C`}
                <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
                  {GATE_KEYS.map((g) => (
                    <span
                      key={g.label}
                      style={{
                        fontSize: 10,
                        color: c[g.key]
                          ? "var(--positive)"
                          : "var(--text-muted)",
                      }}
                    >
                      {g.label}
                    </span>
                  ))}
                </div>
              </td>
              <td>{c.score.toFixed(0)}</td>
              <td>{(c.theta * 100).toFixed(2)}</td>
              <td>{formatDelta(c.net_delta)}</td>
              <td>
                {c.iv_rv_edge != null ? `${c.iv_rv_edge.toFixed(1)}pt` : "—"}
              </td>
              <td>{c.dealer_support ?? "—"}</td>
              <td>{c.range_score != null ? c.range_score.toFixed(2) : "—"}</td>
              <td>{c.dte}</td>
              <td>{formatCredit(c.entry_credit_theo, c.credit_ib)}</td>
              <td>{verdictLabel(c.verdict)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
