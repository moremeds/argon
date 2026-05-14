import Link from "next/link";
import { SetupBadge } from "@/components/watchlist/SetupBadge";
import {
  fmtDateTimeWithZone,
  fmtDecimal,
  fmtSigned,
} from "@/lib/formatters";

type Props = {
  ticker: string;
  spot: number | null;
  iv_atm: number | null;
  spotQuotedAt: string | null;
  scannedAt: string | null;
  setupType: string | null;
  setupDirection: string | null;
  setupScore: number | null;
};

export function DetailHeader(p: Props) {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "12px 16px",
        background: "var(--bg-panel)",
        borderBottom: "1px solid var(--border-dim)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <Link
          href="/"
          style={{ color: "var(--text-muted)", fontSize: 12 }}
        >
          ← back
        </Link>
        <h1 style={{ fontFamily: "var(--font-mono)", fontSize: 24, margin: 0 }}>
          {p.ticker}
        </h1>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 18 }}>
          ${fmtDecimal(p.spot, 2)}
        </span>
        <SetupBadge type={p.setupType} direction={p.setupDirection} />
        {p.setupScore != null && (
          <span
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            score {fmtSigned(p.setupScore, 2)}
          </span>
        )}
      </div>
      <div
        style={{
          fontSize: 10,
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          textAlign: "right",
        }}
      >
        <div>
          spot: {fmtDateTimeWithZone(p.spotQuotedAt)}
        </div>
        <div>
          analytics: {fmtDateTimeWithZone(p.scannedAt)}
        </div>
      </div>
    </header>
  );
}
