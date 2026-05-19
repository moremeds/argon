import type { components } from "@/lib/types";
import { fmtDecimal, fmtRelativeDay, fmtSigned, toNum } from "@/lib/formatters";
import { parseOccSymbol } from "@/lib/occ";

type OiRow = components["schemas"]["OiChangeRow"];

type Props = {
  rows: OiRow[];
  spot: number;
  today?: Date;
  // option_symbol → count of flow alerts firing on this contract today.
  alertIndex?: Map<string, number>;
};

const ASK_BID_DOMINANCE_THRESHOLD = 60;

function dteDays(expiryIso: string, today: Date): number {
  const e = new Date(`${expiryIso}T00:00:00Z`);
  const todayMid = new Date(
    Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()),
  );
  return Math.floor((e.getTime() - todayMid.getTime()) / 86_400_000);
}

function fmtUsd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}

function volOiColor(ratio: number | null): string {
  if (ratio == null) return "var(--text-muted)";
  if (ratio < 0.8) return "var(--text-muted)";
  if (ratio <= 1.5) return "var(--positive)";
  if (ratio <= 5) return "var(--text-primary)";
  return "var(--warning)";
}

type Intent =
  | "BUY CALL"
  | "SELL CALL"
  | "BUY PUT"
  | "SELL PUT"
  | "CLOSE LONG"
  | "CLOSE SHORT"
  | "MIXED";

// Classify the AGGRESSOR's intent. ask_volume / bid_volume / mid_volume /
// no_side_volume on OiChangeRow identify the operator who crossed the
// spread — NOT the position holder. See memory:
// project_aggressor_classification_semantics.
function classifyIntent(
  type: "C" | "P",
  oiDiff: number,
  ask: number,
  bid: number,
  mid: number,
  noSide: number,
): Intent {
  const denom = ask + bid + mid + noSide;
  if (denom <= 0) return "MIXED";
  const askPct = (ask / denom) * 100;
  const bidPct = (bid / denom) * 100;
  const askDom = askPct >= ASK_BID_DOMINANCE_THRESHOLD;
  const bidDom = bidPct >= ASK_BID_DOMINANCE_THRESHOLD;
  if (!askDom && !bidDom) return "MIXED";

  // ΔOI > 0 → contracts opening. Aggressor at ask = buyer opening;
  // aggressor at bid = seller opening (writer).
  if (oiDiff > 0) {
    if (type === "C") return askDom ? "BUY CALL" : "SELL CALL";
    return askDom ? "BUY PUT" : "SELL PUT";
  }
  // ΔOI < 0 → contracts closing. Aggressor at ask = buyer-to-close (short
  // covering); aggressor at bid = seller-to-close (long taking profit).
  if (oiDiff < 0) {
    return askDom ? "CLOSE SHORT" : "CLOSE LONG";
  }
  // ΔOI == 0 (pure churn): label by aggression direction only.
  if (type === "C") return askDom ? "BUY CALL" : "SELL CALL";
  return askDom ? "BUY PUT" : "SELL PUT";
}

function intentColor(intent: Intent): string {
  switch (intent) {
    case "BUY CALL":
    case "SELL PUT":
      return "var(--positive)"; // bullish operator
    case "BUY PUT":
    case "SELL CALL":
      return "var(--negative)"; // bearish operator
    case "CLOSE LONG":
    case "CLOSE SHORT":
      return "var(--text-muted)";
    default:
      return "var(--text-muted)";
  }
}

function metaFlagsFor(opts: { dte: number; volOi: number | null }): string[] {
  const f: string[] = [];
  if (opts.dte === 0) f.push("0DTE LOTTO");
  if (opts.dte > 365) f.push("LEAPS");
  if (opts.volOi != null && opts.volOi > 5) f.push("CHURN");
  return f;
}

export function OiMoversTable({
  rows,
  spot,
  today = new Date(),
  alertIndex,
}: Props) {
  const sorted = rows
    .map((r) => {
      const occ = parseOccSymbol(r.option_symbol);
      const vol = r.volume ?? 0;
      const oiDiff = r.oi_diff_plain ?? 0;
      const volOi = oiDiff !== 0 ? Math.abs(vol / oiDiff) : null;
      const avgPrice = toNum(r.avg_price) ?? 0;
      const notional = vol * avgPrice * 100;
      const ask = r.ask_volume ?? 0;
      const bid = r.bid_volume ?? 0;
      const mid = r.mid_volume ?? 0;
      const noSide = r.no_side_volume ?? 0;
      const intent: Intent = occ
        ? classifyIntent(occ.type, oiDiff, ask, bid, mid, noSide)
        : "MIXED";
      return {
        r,
        occ,
        intent,
        volOi,
        dte: occ ? dteDays(occ.expiry, today) : null,
        pctSpot: occ ? ((occ.strike - spot) / spot) * 100 : null,
        notional,
        alertCount: alertIndex?.get(r.option_symbol) ?? 0,
      };
    })
    .sort((a, b) => b.notional - a.notional)
    .slice(0, 10);

  return (
    <table
      style={{
        width: "100%",
        borderCollapse: "collapse",
        fontFamily: "var(--font-mono)",
        fontSize: 12,
      }}
    >
      <thead>
        <tr style={{ color: "var(--text-muted)", textAlign: "left" }}>
          <th title="Trading date the ΔOI snapshot is from. OI moves are end-of-day aggregations, not intraday.">
            AS OF
          </th>
          <th>TYPE</th>
          <th>EXPIRY</th>
          <th>STRIKE</th>
          <th>DTE</th>
          <th>%SPOT</th>
          <th>ΔOI</th>
          <th>VOL</th>
          <th title="Volume divided by absolute ΔOI. ~1.0 = clean opening flow; >5 = churn.">
            VOL÷|ΔOI|
          </th>
          <th>NOTIONAL</th>
          <th title="Aggressor intent: who crossed the spread, not who holds the position. 60/40 dominance threshold on ask vs bid.">
            INTENT
          </th>
          <th>FLAG</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map(
          ({ r, occ, intent, volOi, dte, pctSpot, notional, alertCount }) => {
            const metaFlags = metaFlagsFor({ dte: dte ?? -1, volOi });
            return (
              <tr
                key={r.option_symbol}
                style={{ borderTop: "1px solid var(--border-dim)" }}
              >
                <td
                  style={{ whiteSpace: "nowrap" }}
                  title={
                    r.last_date
                      ? `Previous snapshot date: ${r.last_date}`
                      : undefined
                  }
                >
                  <span style={{ color: "var(--text-primary)" }}>
                    {r.curr_date ?? "—"}
                  </span>
                  {r.curr_date && (
                    <span
                      style={{
                        marginLeft: 6,
                        color: "var(--text-muted)",
                        fontSize: 10,
                      }}
                    >
                      · {fmtRelativeDay(r.curr_date, today)}
                    </span>
                  )}
                </td>
                <td>{occ?.type ?? r.option_symbol}</td>
                <td>{occ?.expiry ?? "—"}</td>
                <td>{occ ? `$${occ.strike.toFixed(2)}` : "—"}</td>
                <td>{dte ?? "—"}</td>
                <td
                  style={{
                    color:
                      pctSpot == null
                        ? undefined
                        : pctSpot >= 0
                          ? "var(--positive)"
                          : "var(--negative)",
                  }}
                >
                  {pctSpot == null ? "—" : `${fmtSigned(pctSpot, 2)}%`}
                </td>
                <td>{fmtDecimal(r.oi_diff_plain, 0)}</td>
                <td>
                  {fmtDecimal(r.volume, 0)}
                  {alertCount > 0 && (
                    <span
                      title="This contract also fired one or more flow alerts today"
                      style={{
                        marginLeft: 6,
                        fontSize: 10,
                        color: "var(--accent-warm)",
                      }}
                    >
                      [{alertCount} alert{alertCount > 1 ? "s" : ""}]
                    </span>
                  )}
                </td>
                <td style={{ color: volOiColor(volOi) }}>
                  {volOi == null ? "—" : volOi.toFixed(2)}
                </td>
                <td>{fmtUsd(notional)}</td>
                <td style={{ color: intentColor(intent), fontWeight: 600 }}>
                  {intent}
                </td>
                <td>{metaFlags.join(" · ")}</td>
              </tr>
            );
          },
        )}
      </tbody>
    </table>
  );
}
