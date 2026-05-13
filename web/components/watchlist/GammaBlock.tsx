import { fmtPct, fmtDecimal, fmtMoney } from "@/lib/formatters";

type Props = {
  flip_distance: number | null;
  flip_price: number | null;
  per_1pct_move: number | null;
  max_strike: number | null;
  expiring_pct: number | null;
  expiring_date: string | null;
};

function row(label: string, value: string) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        fontSize: 10,
        fontFamily: "var(--font-mono)",
      }}
    >
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span style={{ color: "var(--text-primary)" }}>{value}</span>
    </div>
  );
}

export function GammaBlock(p: Props) {
  return (
    <div>
      <div
        style={{
          fontSize: 9,
          color: "var(--text-secondary)",
          letterSpacing: 1,
          marginBottom: 4,
        }}
      >
        GAMMA
      </div>
      {row("GEX Flip Dist", fmtPct(p.flip_distance))}
      {row(
        "GEX Flip Price",
        p.flip_price != null ? `$${fmtDecimal(p.flip_price, 2)}` : "—",
      )}
      {row("GEX/1% Move", fmtMoney(p.per_1pct_move))}
      {row(
        "Max GEX Strike",
        p.max_strike != null ? `$${fmtDecimal(p.max_strike, 0)}` : "—",
      )}
      {row(
        "GEX Expiring",
        p.expiring_pct != null && p.expiring_date
          ? `${fmtPct(p.expiring_pct, 1)} (${p.expiring_date})`
          : "—",
      )}
    </div>
  );
}
