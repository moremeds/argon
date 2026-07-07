import { PositioningScreenerTable } from "@/components/positioning/PositioningScreenerTable";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function PositioningPage() {
  const data = await api.positioningScreener();

  return (
    <div style={{ padding: 24, maxWidth: 1600, margin: "0 auto" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 8,
        }}
      >
        <h1
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 24,
            letterSpacing: 1,
          }}
        >
          POSITIONING
        </h1>
        {data.as_of ? (
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              letterSpacing: 1,
              color: "var(--text-muted)",
            }}
          >
            EOD · {data.as_of}
          </span>
        ) : null}
      </header>
      <p
        style={{
          color: "var(--text-muted)",
          fontSize: 12,
          marginBottom: 20,
          maxWidth: 720,
        }}
      >
        Short-interest, borrow, insider, analyst and pre-earnings positioning
        across the watchlist — sorted by squeeze risk. Read-only over the daily
        UW snapshot; click a ticker for the full card.
      </p>
      <PositioningScreenerTable rows={data.rows} />
    </div>
  );
}
