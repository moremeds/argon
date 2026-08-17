"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
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
import { PinButton } from "./PinButton";
import { HotButton } from "./HotButton";
import { useLiveSpot } from "./LiveSpotsProvider";

type Card = components["schemas"]["WatchlistCard"];
type Props = { card: Card; sparkline?: number[] };

// Nearest scrolling ancestor, or null for the viewport. IntersectionObserver
// needs this as its `root` or rootMargin means nothing (see the observer
// below). Resolved from computed style rather than a hardcoded
// closest("main") so this cannot silently revert to the broken no-op if the
// shell's scroll container ever moves; today it resolves to AppShell's <main>
// at every breakpoint.
function scrollParent(el: HTMLElement): HTMLElement | null {
  for (let p = el.parentElement; p; p = p.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(p).overflowY)) return p;
  }
  return null;
}

const linkReset = {
  color: "var(--text-primary)",
  textDecoration: "none",
};

export function TickerCard({ card, sparkline = [] }: Props) {
  const [showNotReady, setShowNotReady] = useState(false);
  const [closes, setCloses] = useState<number[]>(sparkline);
  // Live spot from the grid-wide poller (LiveSpotsProvider). Falls back to
  // the server-rendered card values when no provider is mounted or the
  // first poll hasn't landed yet.
  const live = useLiveSpot(card.ticker);
  const spot = live?.spot ?? card.spot;
  const spotQuotedAt = live?.spot_quoted_at ?? card.spot_quoted_at;

  // Gate the sparkline fetch on visibility: fetching on mount made request
  // count == watchlist size (170 requests, ~9 s of fan-out) to draw the ~4
  // sparklines actually on screen.
  const cardRef = useRef<HTMLDivElement>(null);
  // Seeded true where IntersectionObserver is absent (jsdom, older browsers)
  // to keep the old fetch-on-mount path rather than a permanently empty
  // sparkline. Gates only the fetch, never markup, so a different seed on
  // server and client cannot desync hydration.
  const [visible, setVisible] = useState(
    () => typeof IntersectionObserver === "undefined",
  );
  useEffect(() => {
    if (visible) return;
    const el = cardRef.current;
    if (!el) return;
    // ponytail: native IntersectionObserver, no library. rootMargin preloads
    // one screen ahead so a scroll lands on a drawn sparkline, not a gap.
    // `root` must be the scrolling ancestor: rootMargin expands the root's
    // bounds, never ancestor clip rects, so with root:null the 600px preload
    // is silently a no-op (verified in-browser: a card 300px below the fold
    // reports isIntersecting false with root:null, true with the scroller).
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setVisible(true);
      },
      { root: scrollParent(el), rootMargin: "600px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [visible]);

  // Sparkline OHLC is fetched client-side (was server-side as part of the
  // dashboard RSC, paying ~800 ms per page load). Skips when (a) the prop
  // pre-seeded data (used by unit tests), (b) the ticker isn't scanned, or
  // (c) the card has never been scrolled into view.
  // Note: CardGrid uses `key={t.ticker}` so TickerCard unmounts/remounts on
  // ticker change — there is no in-place ticker swap to worry about.
  useEffect(() => {
    if (!visible || closes.length > 0 || !card.scanned_at) return;
    const ac = new AbortController();
    fetch(`/api/ohlc/${card.ticker}?days=30`, {
      cache: "no-store",
      signal: ac.signal,
    })
      .then((r) =>
        r.ok ? r.json() : Promise.reject(new Error(`status ${r.status}`)),
      )
      .then((bars: Array<{ close: string | number | null }>) => {
        if (ac.signal.aborted) return;
        setCloses(bars.map((b) => Number(b.close)).reverse());
      })
      .catch(() => {
        // Empty sparkline is an acceptable degraded state.
      });
    return () => ac.abort();
  }, [visible, card.ticker, card.scanned_at, closes.length]);

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
            {toNum(spot) != null ? `$${fmtDecimal(toNum(spot), 2)}` : "—"}
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
          closes={closes}
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
      ref={cardRef}
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
          // 170 cards means 170 speculative RSC prefetches competing with the
          // grid's own fetches; the detail route is one click, not a race.
          prefetch={false}
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
          <div>spot {fmtDateTimeWithZone(spotQuotedAt)}</div>
          <div>
            analytics{" "}
            {card.scanned_at
              ? fmtDateTimeWithZone(card.scanned_at)
              : "not scanned"}
          </div>
          {queueLabel && (
            <div style={{ color: "var(--warning)" }}>{queueLabel}</div>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center" }}>
          <HotButton ticker={card.ticker} hot={card.hot ?? false} />
          <PinButton ticker={card.ticker} pinned={card.pinned} />
          <RescanButton ticker={card.ticker} initialJob={card.queue ?? null} />
        </div>
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
