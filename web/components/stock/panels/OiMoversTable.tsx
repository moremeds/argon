import type { components } from "@/lib/types";
import { fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";
import { parseOccSymbol } from "@/lib/occ";

type OiRow = components["schemas"]["OiChangeRow"];

type Props = {
  rows: OiRow[];
  spot: number;
  today?: Date;
};

function dteDays(expiryIso: string, today: Date): number {
  // Both dates anchored at UTC midnight; integer day count, no time-of-day drift.
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

function flagsFor(opts: {
  type: "C" | "P";
  dte: number;
  volOi: number | null;
  askPct: number | null;
  oiDiff: number;
}): string[] {
  const f: string[] = [];
  if (opts.dte === 0) f.push("0DTE LOTTO");
  if (opts.dte > 365) f.push("LEAPS");
  if (opts.volOi != null && opts.volOi > 5) f.push("CHURN");
  // OPENING requires positive ΔOI AND ask-side flow > 60%.  Negative-ΔOI
  // rows in the clean-opening band are closing positions, not opening.
  if (
    opts.volOi != null &&
    opts.volOi >= 0.8 &&
    opts.volOi <= 1.5 &&
    opts.oiDiff > 0 &&
    opts.askPct != null &&
    opts.askPct > 60
  ) {
    const arrow = opts.type === "C" ? "↑" : "↓";
    f.push(`OPENING ${arrow}`);
  }
  return f;
}

export function OiMoversTable({ rows, spot, today = new Date() }: Props) {
  const sorted = rows
    .map((r) => {
      const occ = parseOccSymbol(r.option_symbol);
      const askDenom =
        (r.prev_ask_volume ?? 0) +
        (r.prev_bid_volume ?? 0) +
        (r.prev_mid_volume ?? 0) +
        (r.prev_neutral_volume ?? 0);
      const askPct =
        askDenom > 0 ? ((r.prev_ask_volume ?? 0) / askDenom) * 100 : null;
      const vol = r.volume ?? 0;
      const oiDiff = r.oi_diff_plain ?? 0;
      const volOi = oiDiff !== 0 ? Math.abs(vol / oiDiff) : null;
      const avgPrice = toNum(r.avg_price) ?? 0;
      const notional = vol * avgPrice * 100;
      return {
        r,
        occ,
        askPct,
        volOi,
        dte: occ ? dteDays(occ.expiry, today) : null,
        pctSpot: occ ? ((occ.strike - spot) / spot) * 100 : null,
        notional,
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
          <th>TYPE</th>
          <th>EXPIRY</th>
          <th>STRIKE</th>
          <th>DTE</th>
          <th>%SPOT</th>
          <th>ΔOI</th>
          <th>VOL/|ΔOI|</th>
          <th>NOTIONAL</th>
          <th>ASK%</th>
          <th>FLAG</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map(({ r, occ, askPct, volOi, dte, pctSpot, notional }) => {
          const flags = occ
            ? flagsFor({
                type: occ.type,
                dte: dte ?? -1,
                volOi,
                askPct,
                oiDiff: r.oi_diff_plain ?? 0,
              })
            : [];
          return (
            <tr
              key={r.option_symbol}
              style={{ borderTop: "1px solid var(--border-dim)" }}
            >
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
              <td style={{ color: volOiColor(volOi) }}>
                {volOi == null ? "—" : volOi.toFixed(2)}
              </td>
              <td>{fmtUsd(notional)}</td>
              <td>{askPct == null ? "—" : `${askPct.toFixed(1)}%`}</td>
              <td>{flags.join(" · ")}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
