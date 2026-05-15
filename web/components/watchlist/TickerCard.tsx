"use client";
import Link from "next/link";
import { useState } from "react";
import type { components } from "@/lib/types";
import { StockNotReadyDialog } from "@/components/stock/StockNotReadyDialog";
import { SetupBadge } from "./SetupBadge";
import { SparklineRow } from "./SparklineRow";
import { AggressionGauge } from "./AggressionGauge";
import { GammaBlock } from "./GammaBlock";
import { SkewBlock } from "./SkewBlock";
import { PositioningBlock } from "./PositioningBlock";
import {
  fmtPct,
  fmtDecimal,
  fmtDateTimeWithZone,
  toNum,
} from "@/lib/formatters";
import { bucketFreshness } from "@/lib/freshness";
import { RescanButton } from "@/components/shared/RescanButton";

type Card = components["schemas"]["WatchlistCard"];
type Props = { card: Card; sparkline: number[] };

const linkReset = {
  color: "var(--text-primary)",
  textDecoration: "none",
};

export function TickerCard({ card, sparkline }: Props) {
  const [showNotReady, setShowNotReady] = useState(false);
  const fresh = bucketFreshness(card.scanned_at);
  const dot =
    fresh === "fresh"
      ? "var(--positive)"
      : fresh === "stale"
        ? "var(--warning)"
        : "var(--negative)";
  const isReady = card.scanned_at != null;
  const queueLabel =
    card.queue == null
      ? null
      : card.queue.status === "running"
        ? "running"
        : `${card.queue.status} #${card.queue.queue_position}`;

  const detailContent = (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 6,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: dot,
              display: "inline-block",
            }}
          />
          <span style={{ fontSize: 16, fontWeight: 700 }}>{card.ticker}</span>
          <span
            style={{
              fontSize: 13,
              color: "var(--text-secondary)",
              fontWeight: 500,
            }}
          >
            {toNum(card.spot) != null
              ? `$${fmtDecimal(toNum(card.spot), 2)}`
              : "—"}
          </span>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 16, fontWeight: 700 }}>
            {fmtPct(toNum(card.iv_atm), 1)}
          </div>
          <div style={{ fontSize: 9, color: "var(--text-muted)" }}>
            IVR {fmtDecimal(toNum(card.iv_rank), 0)}
          </div>
        </div>
      </div>

      <SetupBadge
        type={card.setup?.type ?? null}
        direction={card.setup?.direction ?? null}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto",
          gap: 8,
          alignItems: "center",
          margin: "8px 0",
        }}
      >
        <SparklineRow
          closes={sparkline}
          ret_1d={toNum(card.returns?.d1)}
          ret_1w={toNum(card.returns?.w1)}
          ret_30d={toNum(card.returns?.d30)}
        />
        <AggressionGauge value={toNum(card.aggression_pct)} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 8 }}>
        <GammaBlock
          flip_distance={toNum(card.gamma.flip_distance)}
          flip_price={toNum(card.gamma.flip_price)}
          per_1pct_move={toNum(card.gamma.per_1pct_move)}
          max_strike={toNum(card.gamma.max_strike)}
          expiring_pct={toNum(card.gamma.expiring_pct)}
          expiring_date={card.gamma.expiring_date ?? null}
        />
        <SkewBlock rr25d_30dte={toNum(card.skew.rr25d_30dte)} />
        <PositioningBlock
          call_oi={card.positioning.call_oi ?? null}
          put_oi={card.positioning.put_oi ?? null}
          pcr_oi={toNum(card.positioning.pcr_oi)}
          pcr_vol={toNum(card.positioning.pcr_vol)}
          pcr_delta_30d={toNum(card.positioning.pcr_delta_30d)}
        />
      </div>
    </>
  );

  return (
    <div
      style={{
        padding: 12,
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        color: "var(--text-primary)",
        fontFamily: "var(--font-mono)",
      }}
    >
      {isReady ? (
        <Link
          href={`/stock/${card.ticker}/market-structure`}
          aria-label={`${card.ticker} detail`}
          style={{ ...linkReset, display: "block" }}
        >
          {detailContent}
        </Link>
      ) : (
        <button
          type="button"
          aria-label={`${card.ticker} detail`}
          onClick={() => setShowNotReady(true)}
          style={{
            ...linkReset,
            display: "block",
            width: "100%",
            padding: 0,
            background: "transparent",
            border: 0,
            textAlign: "left",
            font: "inherit",
            cursor: "pointer",
          }}
        >
          {detailContent}
        </button>
      )}

      <div
        style={{
          marginTop: 8,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div
          style={{
            fontSize: 8,
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            lineHeight: 1.25,
          }}
          suppressHydrationWarning
        >
          <div>spot {fmtDateTimeWithZone(card.spot_quoted_at)}</div>
          <div>
            analytics{" "}
            {card.scanned_at ? fmtDateTimeWithZone(card.scanned_at) : "not scanned"}
          </div>
          {queueLabel && (
            <div style={{ color: "var(--warning)" }}>{queueLabel}</div>
          )}
        </div>
        <RescanButton ticker={card.ticker} initialJob={card.queue ?? null} />
      </div>
      {showNotReady && (
        <StockNotReadyDialog
          ticker={card.ticker}
          onClose={() => setShowNotReady(false)}
        />
      )}
    </div>
  );
}
