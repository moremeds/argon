import { BoardRead } from "@/components/macro/domain/BoardPanel";

import { statusLabel, toFiniteNumber } from "../format";
import type { Positioning } from "../types";

function pct(value: unknown): number | null {
  const n = toFiniteNumber(value, Number.NaN);
  return Number.isFinite(n) ? n : null;
}

export function PositioningSection({
  positioning,
}: {
  positioning: Positioning;
}) {
  const row = positioning.details?.[0];
  if (!row) {
    return (
      <div className="note-refuse">
        <b>{statusLabel(positioning.status)}</b> CFTC TFF detail is unavailable.
      </div>
    );
  }
  const readings = [
    ["Asset Mgr net %OI", pct(row.asset_mgr_net_pct_oi), ""],
    ["Dealer net %OI", pct(row.dealer_net_pct_oi), "blue"],
    ["Lev Money net %OI", pct(row.lev_money_net_pct_oi), "crit"],
  ] as const;
  return (
    <>
      {readings.map(([label, value, tone]) => (
        <div className="meter" key={label}>
          <span className="lbl">{label}</span>
          <div className="track">
            <span className="mid" />
            {value != null ? (
              <span
                className={`pin${tone ? ` ${tone}` : ""}`}
                style={{ left: `${Math.max(0, Math.min(100, 50 + value))}%` }}
              />
            ) : null}
          </div>
          <span className="val">
            {value == null ? "n/a" : `${value > 0 ? "+" : ""}${value.toFixed(1)}%`}
          </span>
        </div>
      ))}
      <BoardRead>
        {positioning.positioning_read ??
          "CFTC TFF Treasury futures positioning is unavailable."}
      </BoardRead>
      <p className="cap">
        {row.contract_name} · observation {row.obs_date ?? "n/a"} · release{" "}
        {row.release_date ?? "n/a"}
      </p>
    </>
  );
}
