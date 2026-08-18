import type { components } from "@/lib/types";

type Anchors = components["schemas"]["FundamentalAnchors"];

const LEVELS = [
  ["buy_below", "buy below"],
  ["observe_low", "observe low"],
  ["observe_mid", "observe mid"],
  ["observe_high", "observe high"],
  ["risk_above", "risk above"],
] as const;

/**
 * Which of two stacked label rows each level is drawn in.
 *
 * Labels sit at their VALUE position on the rail, so they crowd wherever the
 * band's levels crowd — and these levels are percentiles of one distribution,
 * so they routinely bunch at one end. AAPL 2026-05-15 is typical: 247.1 / 256.3
 * / 263.2 then a gap then 299.5 / 305.3.
 *
 * Measured over the 233 live bands, as a share of panel width: all five in one
 * row leaves **90 of 233** with neighbours under 7pp apart. Alternating two rows
 * lifts the median neighbour gap from 8.6pp to 24.3pp and leaves 3 under 4pp.
 * Adjacent levels always land in different rows, so only every-other-level pairs
 * can collide at all.
 */
const LABEL_ROW = [0, 1, 0, 1, 0] as const;

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
 * - **Every label sits at its own value on the rail.** It did not until
 *   2026-08-12: the rail placed ticks by value while the labels underneath were
 *   an evenly-spaced five-column grid, so the two disagreed on **all 233 live
 *   bands**, by a median of 20 and a maximum of 80 percentage points of panel
 *   width. AAPL printed "buy below 247.1" under a position the rail read as
 *   ~253. A scale whose labels do not match its marks is not a scale.
 * - **A null level is skipped, never drawn as a boundary.** Rendering it as 0
 *   would place "buy below $0" on screen. The backend now refuses a band whose
 *   end will not invert, so this should be unreachable from the API — it stays
 *   because a component must not draw a number nobody computed.
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
    // No explainer here. `Header`'s paragraph describes how to read five levels
    // and a spot marker, none of which exist on a refusal, and it pushed the one
    // sentence that answers "where is the band?" below three lines of prose
    // about a band that was never drawn. The reason leads instead.
    return (
      <section style={{ marginTop: 20 }}>
        <Header a={a} explain={false} />
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

      {/* One axis. Spot and its stem sit ABOVE the rail; every level's tick and
          its label sit BELOW, both placed by the same `pos()`. Nothing here is
          evenly spaced — the gaps between levels are the information. */}
      <div style={{ position: "relative", height: 96, marginBottom: 4 }}>
        {spot != null ? (
          <div
            style={{
              position: "absolute",
              left: `${pos(spot)}%`,
              top: 0,
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

        <div
          style={{
            position: "absolute",
            top: 36,
            left: 0,
            right: 0,
            height: 2,
            background: "var(--border-dim)",
          }}
        />

        {known.map((p) => {
          const row = LABEL_ROW[LEVELS.findIndex(([k]) => k === p.key)] ?? 0;
          return (
            <div key={p.key}>
              {/* Tick hangs BELOW the rail so it cannot be mistaken for, or
                  hidden behind, the spot stem above it — AAPL's spot (300.2)
                  and observe_high (299.5) land 0.7pp apart. */}
              <div
                style={{
                  position: "absolute",
                  left: `${pos(p.value)}%`,
                  top: 36,
                  width: 1,
                  height: row === 0 ? 6 : 24,
                  background: "var(--border-dim)",
                }}
              />
              <div
                style={{
                  position: "absolute",
                  left: `${pos(p.value)}%`,
                  top: row === 0 ? 44 : 62,
                  transform: "translateX(-50%)",
                  textAlign: "center",
                  whiteSpace: "nowrap",
                }}
                title={`${p.label} ${money(p.value)}`}
              >
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>
                  {money(p.value)}
                </div>
                <div style={{ color: "var(--text-muted)", fontSize: 9 }}>
                  {p.label}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* No second row of values. The five-column grid that used to live here
          was an evenly-spaced restatement of numbers the rail already carries at
          their true positions, and being adjacent to a value-scaled axis it read
          as that axis's labels. Removing it is the fix; the rail above is now
          the single place a level's price and its position are stated. */}

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

/**
 * Where spot sits, said as a RANK rather than a percentage.
 *
 * The percentile is exact but its resolution is not: it is a count over
 * `history_quarters` observations, so with a 20-quarter window it can only take
 * 21 values and every step is 5 points. "Cheaper than 95%" implies a precision
 * twenty observations cannot carry, and at the top it printed "cheaper than
 * 100%" — which reads as a bound rather than as what it is, the cheapest reading
 * in the window and possibly well past it. Naming the sample size fixes both,
 * and the ends get words instead of a number that has run out of room.
 */
export function rankPhrase(pct: number, quarters: number): string {
  const n = Math.round(pct * quarters);
  if (n >= quarters) return `Cheaper than any of its last ${quarters} quarters`;
  if (n <= 0) return `Richer than any of its last ${quarters} quarters`;
  return `Cheaper than ${n} of its last ${quarters} quarters`;
}

function Header({ a, explain = true }: { a: Anchors; explain?: boolean }) {
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
      {explain ? (
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
              <strong>{rankPhrase(pct, a.history_quarters)}</strong>
              {` on ${METHOD_LABEL[a.method] ?? a.method}. `}
            </>
          ) : null}
          {"Levels are percentiles of its "}
          <strong>own</strong>
          {" recent range, not a ranking against other companies — measured " +
            "within-ticker, where ranking names against each other on value is " +
            "inverted. A trailing window, because these multiples re-rate: a " +
            "full-history percentile is a price from a regime that has gone."}
        </p>
      ) : null}
    </>
  );
}
