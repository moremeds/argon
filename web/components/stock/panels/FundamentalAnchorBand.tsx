import type { components } from "@/lib/types";

type Anchors = components["schemas"]["FundamentalAnchors"];

const LEVELS = [
  ["buy_below", "buy below"],
  ["observe_low", "observe low"],
  ["observe_mid", "observe mid"],
  ["observe_high", "observe high"],
  ["risk_above", "risk above"],
] as const;

const METHOD_LABEL: Record<string, string> = {
  sales_to_ev: "revenue / enterprise value",
  ebitda_to_ev: "EBITDA / enterprise value",
  fcf_yield: "free cash flow / market cap",
};

const money = (v: number) =>
  v >= 1000 ? v.toFixed(0) : v >= 100 ? v.toFixed(1) : v.toFixed(2);

/**
 * The price band from a name's own valuation history, with spot marked.
 *
 * Three constraints this component exists to respect:
 *
 * - **A refusal renders, and says why.** All five levels null with reasons
 *   populated is a REFUSED band, not a missing one — TSM's statements are in TWD
 *   against a USD ADR quote, and stating that is more useful than an empty box.
 * - **A null level is a gap, never a boundary.** It is drawn as a dash in the
 *   ladder and skipped by the rail, because rendering it as 0 would place a
 *   "buy below $0" on screen.
 * - **No red/green ramp across the band.** The levels are locational, not a
 *   recommendation strength, and the one measured claim is a 2q rank IC — not
 *   an entry signal. Spot gets the only accent on the rail.
 */
export function FundamentalAnchorBand({ a }: { a: Anchors }) {
  const points = LEVELS.map(([key, label]) => ({
    key,
    label,
    value: a[key] as number | null,
  }));
  const known = points.filter((p) => p.value != null) as {
    key: string;
    label: string;
    value: number;
  }[];

  if (known.length === 0) {
    return (
      <section style={{ marginTop: 20 }}>
        <Header a={a} />
        <div
          style={{
            fontSize: 12,
            color: "var(--text-muted)",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            padding: "10px 12px",
          }}
        >
          <strong style={{ color: "var(--warning)" }}>No band.</strong>
          {` ${a.confidence_reasons.join("; ") || "reason not recorded"}`}
        </div>
      </section>
    );
  }

  // The rail spans the known levels and spot, so a spot outside the band still
  // lands on screen instead of being clipped at an edge and reading as "at the
  // boundary" — which is the opposite of what an out-of-band price means.
  const spot = a.spot ?? null;
  const vals = [...known.map((p) => p.value), ...(spot != null ? [spot] : [])];
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || 1;
  // Inset so the extreme value — usually spot, when price has left the band —
  // does not land at 0% or 100% with its label half off-screen. A clipped spot
  // marker reads as "at the edge of the band", which is the opposite of what an
  // out-of-band price means.
  const INSET = 6;
  const pos = (v: number) => INSET + ((v - lo) / span) * (100 - 2 * INSET);

  return (
    <section style={{ marginTop: 20 }}>
      <Header a={a} />

      <div style={{ position: "relative", height: 46, marginBottom: 6 }}>
        <div
          style={{
            position: "absolute",
            top: 20,
            left: 0,
            right: 0,
            height: 2,
            background: "var(--border-dim)",
          }}
        />
        {known.map((p) => (
          <div
            key={p.key}
            style={{
              position: "absolute",
              left: `${pos(p.value)}%`,
              top: 14,
              width: 1,
              height: 14,
              background: "var(--text-muted)",
            }}
            title={`${p.label} ${money(p.value)}`}
          />
        ))}
        {spot != null ? (
          <div
            style={{
              position: "absolute",
              left: `${pos(spot)}%`,
              top: 4,
              transform: "translateX(-50%)",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--accent-bg)",
                whiteSpace: "nowrap",
              }}
            >
              {money(spot)}
            </span>
            <span
              style={{
                width: 2,
                height: 20,
                background: "var(--accent-bg)",
                marginTop: 2,
              }}
            />
          </div>
        ) : null}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(5, 1fr)",
          gap: 6,
          fontFamily: "var(--font-mono)",
          fontSize: 11,
        }}
      >
        {points.map((p) => (
          <div key={p.key} style={{ textAlign: "center" }}>
            <div style={{ color: "var(--text-muted)", fontSize: 9 }}>
              {p.label}
            </div>
            <div>{p.value == null ? "—" : money(p.value)}</div>
          </div>
        ))}
      </div>

      {a.confidence_reasons.length > 0 ? (
        <ul
          style={{
            margin: "10px 0 0",
            paddingLeft: 16,
            fontSize: 11,
            color: "var(--text-muted)",
          }}
        >
          {a.confidence_reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function Header({ a }: { a: Anchors }) {
  const pct = a.spot_percentile;
  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 8,
        }}
      >
        <h3 style={{ fontSize: 13, margin: 0 }}>Valuation band</h3>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-muted)",
          }}
        >
          {a.company_type} · {METHOD_LABEL[a.method] ?? a.method} ·{" "}
          {a.history_quarters}q · {a.confidence} · {a.as_of}
        </span>
      </div>
      <p
        style={{
          fontSize: 11,
          color: "var(--text-muted)",
          margin: "0 0 10px",
          lineHeight: 1.5,
        }}
      >
        {pct != null ? (
          <>
            {"Cheaper than "}
            <strong>{`${Math.round(pct * 100)}%`}</strong>
            {` of this company’s own history on ${
              METHOD_LABEL[a.method] ?? a.method
            }. `}
          </>
        ) : null}
        {"Levels are percentiles of its "}
        <strong>own</strong>
        {" past, not a ranking against other companies — measured " +
          "within-ticker, where ranking names against each other on value " +
          "is inverted."}
      </p>
    </>
  );
}
