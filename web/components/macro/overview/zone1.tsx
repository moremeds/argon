import { CorrelationLineChart } from "@/components/gold/correlation/CorrelationLineChart";
import type { components } from "@/lib/types";

import { BoardPanel, BoardRead } from "../domain/BoardPanel";
import { confidencePct, plural} from "../format";
import type {
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "../types";
import { CAUSAL_ORDER, DOMAIN_LABEL } from "../types";

/**
 * ZONE 1 · WHAT CHANGED — the board's first three panels.
 *
 * All three answer the same question at different resolutions: the desk's own answers
 * (state and confidence), the market's (daily closes), and the one relationship the gold
 * gate stands on. The board puts them in that order because it is the order of authority:
 * what we published, what the world did, what the link between them is doing.
 */

/** One domain read at two instants. The prior read is a SECOND point-in-time request, not
 *  a history endpoint — the desk has none, and `/api/macro/*` replay is what makes the
 *  comparison possible at all. */
export type DomainWeekPair = {
  now: MacroOverviewSlot<MacroDomainState>;
  prior: { value: MacroDomainState | null; error?: string };
};

export type DomainWeek = Record<MacroDomainKey, DomainWeekPair>;

/**
 * PANEL 1 · State flips × confidence moves.
 *
 * ### A week of zero flips is not a week of zero information
 *
 * The board's own read for this panel makes the point and it is why the CONFIDENCE column
 * exists beside the state column: a state that did not move while its confidence decayed
 * is a domain quietly ageing out of its evidence, and a table showing only states would
 * report that week as empty.
 *
 * ### Why "no flip" is stated rather than left blank
 *
 * A blank cell is ambiguous between "did not move" and "we could not tell". This table can
 * be in the second situation for real — the prior instant may have no stored state — so
 * the two are printed as different sentences and never as the same silence.
 */
export function StateFlipsPanel({
  week,
  priorLabel,
  nowLabel,
}: {
  week: DomainWeek;
  priorLabel: string;
  nowLabel: string;
}) {
  const rows = CAUSAL_ORDER.map((domain) => {
    const { now, prior } = week[domain];
    const flipped =
      now.value && prior.value ? now.value.state !== prior.value.state : null;
    return { domain, now: now.value, prior: prior.value, flipped };
  });

  const comparable = rows.filter((r) => r.flipped !== null);
  const flips = comparable.filter((r) => r.flipped);

  return (
    <BoardPanel
      id="state-flips"
      title="State flips × confidence moves"
      questions={["Q1"]}
      basis="REAL"
      source={
        <>
          /api/macro/{"{inflation,rates,usd,gold}"} read at two instants —{" "}
          {priorLabel} and {nowLabel}. The desk publishes no state-history
          endpoint, so the prior column is a second point-in-time request, not a
          stored series
        </>
      }
    >
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Domain</th>
              <th>
                State {priorLabel} → {nowLabel}
              </th>
              <th>Confidence path</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.domain} data-testid={`macro-flip-${row.domain}`}>
                <td>{DOMAIN_LABEL[row.domain]}</td>
                <td>
                  {row.now && row.prior ? (
                    row.flipped ? (
                      <>
                        {row.prior.state} →{" "}
                        <b style={{ color: "var(--warning)" }}>
                          {row.now.state}
                        </b>
                      </>
                    ) : (
                      <>{row.now.state} · no flip</>
                    )
                  ) : row.now ? (
                    <span style={{ color: "var(--text-muted)" }}>
                      {row.now.state} · no stored state at {priorLabel} to
                      compare against
                    </span>
                  ) : (
                    <span style={{ color: "var(--text-muted)" }}>
                      never computed at this instant
                    </span>
                  )}
                </td>
                <td className="num">
                  {row.prior && row.now ? (
                    <ConfidencePath
                      from={row.prior.confidence}
                      to={row.now.confidence}
                    />
                  ) : row.now ? (
                    confidencePct(row.now.confidence)
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <BoardRead testId="macro-flips-read">
        {comparable.length === 0 ? (
          <>
            No domain could be compared across the week — every prior read came
            back without a stored state, so this table reports the desk&rsquo;s
            coverage rather than the world&rsquo;s movement.
          </>
        ) : flips.length === 0 ? (
          <>
            <b>Zero state flips</b> across{" "}
            {plural(comparable.length, "comparable domain")} — which is not a week of zero
            information. Confidence is where the change lives, and it is the
            column to read: a state that held while its confidence decayed is a
            domain ageing out of its evidence, not one being re-confirmed.
          </>
        ) : (
          <>
            <b>{plural(flips.length, "state flip")}</b> across{" "}
            {plural(comparable.length, "comparable domain")}:{" "}
            {flips.map((f) => DOMAIN_LABEL[f.domain]).join(", ")}. A flip is the
            engine&rsquo;s own published label changing, not a reading of ours.
          </>
        )}
      </BoardRead>
    </BoardPanel>
  );
}

/** The board prints confidence as a path, not a delta — `0.429 → 0.373`, so the reader
 *  sees the level and the move at once. The arrow is coloured only when the number moved,
 *  and only by direction: a fall in confidence is a fact, never a verdict. */
function ConfidencePath({
  from,
  to,
}: {
  from: string | number | null | undefined;
  to: string | number | null | undefined;
}) {
  const a = Number(from);
  const b = Number(to);
  if (!Number.isFinite(a) || !Number.isFinite(b)) {
    return <>{confidencePct(to)}</>;
  }
  if (a === b) {
    return <>{a.toFixed(2)} · unchanged</>;
  }
  return (
    <span className={b > a ? "delta-up" : "delta-dn"}>
      {a.toFixed(2)} → {b.toFixed(2)}
    </span>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * PANEL 2 · Market deltas
 * ──────────────────────────────────────────────────────────────────────────── */

type InputPoint = components["schemas"]["GoldInputSeriesPoint"];

/**
 * How each series' move is expressed.
 *
 * The unit is NOT cosmetic. A 0.02 move on DGS10 is two basis points and a 0.02 move on
 * VIXCLS is two hundredths of a vol point, and printing both as "+0.02" makes the first
 * unreadable and the second overstated. The board carries the unit per row for exactly
 * this reason, so it is carried here per row too.
 */
type DeltaUnit = "bp" | "pct" | "pts";

export type DeltaSeriesSpec = {
  id: string;
  label: string;
  unit: DeltaUnit;
};

/**
 * The nine series the board's panel names — and what we can actually serve.
 *
 * Measured against the live store 2026-08-29: five of the nine return points and four
 * return an empty series. They stay in this list rather than being quietly deleted,
 * because the panel's job includes saying which of the board's rows the desk cannot fill.
 * A row silently dropped reads as a row the board never asked for.
 */
export const DELTA_SERIES: readonly DeltaSeriesSpec[] = [
  { id: "DGS10", label: "DGS10 · nominal 10y", unit: "bp" },
  { id: "DFII10", label: "DFII10 · real 10y", unit: "bp" },
  { id: "T10YIE", label: "T10YIE · breakeven", unit: "bp" },
  { id: "DTWEXBGS", label: "DTWEXBGS · broad USD", unit: "pct" },
  { id: "VIXCLS", label: "VIX", unit: "pts" },
];

export type DeltaSeries = {
  spec: DeltaSeriesSpec;
  points: InputPoint[];
  error?: string;
};

/** start, end, and the move between them in the series' own unit. `null` when the window
 *  holds fewer than two observations — one point is a level, not a change. */
function moveOf(series: DeltaSeries): {
  start: number;
  end: number;
  delta: number;
  text: string;
} | null {
  const values = series.points
    .map((p) => Number(p.value))
    .filter((v) => Number.isFinite(v));
  if (values.length < 2) return null;
  const start = values[0];
  const end = values[values.length - 1];
  const raw = end - start;
  const delta =
    series.spec.unit === "bp"
      ? raw * 100
      : series.spec.unit === "pct"
        ? (raw / start) * 100
        : raw;
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
  const magnitude = Math.abs(delta);
  const text =
    series.spec.unit === "bp"
      ? `${sign}${magnitude.toFixed(0)}bp`
      : series.spec.unit === "pct"
        ? `${sign}${magnitude.toFixed(2)}%`
        : `${sign}${magnitude.toFixed(2)} pts`;
  return { start, end, delta, text };
}

/**
 * PANEL 2 · Market deltas · 1 week.
 *
 * ### The read is derived, never the board's sentence
 *
 * The board's own read says the week was "breakeven-led (+5bp BEI vs −3bp real)". Those
 * were true at its capture instant and are the exact kind of frozen number the desk's
 * standing rule forbids restating. So the comparison is recomputed here from the two
 * series and the sentence is assembled from the result — which means it can legitimately
 * say the opposite of the board, and should when the data does.
 */
export function MarketDeltasPanel({
  series,
  windowLabel,
}: {
  series: DeltaSeries[];
  windowLabel: string;
}) {
  const served = series.filter((s) => s.points.length >= 2);
  const missing = series.filter((s) => s.points.length < 2);

  const bei = served.find((s) => s.spec.id === "T10YIE");
  const real = served.find((s) => s.spec.id === "DFII10");
  const beiMove = bei ? moveOf(bei) : null;
  const realMove = real ? moveOf(real) : null;

  return (
    <BoardPanel
      id="market-deltas"
      title={`Market deltas · ${windowLabel}`}
      questions={["Q2"]}
      basis="COMPUTED"
      sourceLabel="Formula"
      source={
        <>
          last minus first stored daily close in the window, per series, from
          /api/gold/inputs/&#123;series_id&#125; · yields in bp, index levels in
          percent, vol in points
        </>
      }
    >
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Series</th>
              <th className="num">start → end</th>
              <th className="num">Δ {windowLabel}</th>
            </tr>
          </thead>
          <tbody>
            {series.map((s) => {
              const move = moveOf(s);
              return (
                <tr key={s.spec.id} data-testid={`macro-delta-${s.spec.id}`}>
                  <td>{s.spec.label}</td>
                  {move ? (
                    <>
                      <td className="num">
                        {move.start.toFixed(2)} → {move.end.toFixed(2)}
                      </td>
                      <td
                        className={`num ${
                          move.delta > 0
                            ? "delta-up"
                            : move.delta < 0
                              ? "delta-dn"
                              : "delta-flat"
                        }`}
                      >
                        {move.text}
                      </td>
                    </>
                  ) : (
                    <td
                      className="num"
                      colSpan={2}
                      style={{ textAlign: "left" }}
                    >
                      <span style={{ color: "var(--text-muted)" }}>
                        {s.error
                          ? s.error
                          : s.points.length === 1
                            ? "one observation in the window — a level, not a change"
                            : "not stored — this series has no observations on this desk"}
                      </span>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <BoardRead testId="macro-deltas-read">
        {beiMove && realMove ? (
          <>
            The 10y move is{" "}
            <b>
              {Math.abs(beiMove.delta) > Math.abs(realMove.delta)
                ? "breakeven-led"
                : Math.abs(realMove.delta) > Math.abs(beiMove.delta)
                  ? "real-yield-led"
                  : "split evenly between its two legs"}
            </b>{" "}
            ({beiMove.text} breakeven against {realMove.text} real). Which leg
            leads says what the move is about — inflation compensation or the
            discount rate — and the two can move in opposite directions inside
            the same nominal yield.
          </>
        ) : (
          <>
            The breakeven and real-yield legs cannot both be read over this
            window, so the desk does not say which led. The nominal
            yield&rsquo;s move is real either way; its decomposition is what is
            missing.
          </>
        )}
      </BoardRead>

      {missing.length > 0 ? (
        <p className="cap" data-testid="macro-deltas-coverage">
          {served.length} of {series.length} series served ·{" "}
          {missing.map((m) => m.spec.id).join(", ")} not stored on this desk.
          The board also names SOFR−EFFR, GVZ, HY OAS and GLD; none reach this
          endpoint.
        </p>
      ) : null}
    </BoardPanel>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * PANEL 3 · The anchor
 * ──────────────────────────────────────────────────────────────────────────── */

type GaugePoint = components["schemas"]["GoldGaugeTimeSeriesPoint"];
type CorrelationPoint = components["schemas"]["GoldCorrelationPoint"];

/**
 * PANEL 3 · Anchor letting go.
 *
 * ### The board asks for a window this desk does not compute
 *
 * The board titles this panel `gauge corr_60d` and its read quotes a 60-day series moving
 * −0.79 → −0.17 in twelve sessions. `GoldGaugeTimeSeriesPoint` carries `corr_252d` and
 * nothing else — the producer (`reports/gold_posture.py`) computes at one window — so the
 * 60-day cut is absent from every point of every series the API serves.
 *
 * That is a gap in the PRODUCER, not something the web layer may paper over. Drawing the
 * 252-day series under a 60-day heading would be the one thing worse than the missing
 * panel: a real line wearing the wrong label. So the panel renders the window that exists,
 * says so in its own caption, and names where the fix belongs.
 */
export function AnchorPanel({
  gauge,
}: {
  gauge: { value: { history_252d?: GaugePoint[] } | null; error?: string };
}) {
  const points = gauge.value?.history_252d ?? [];
  const anchor: CorrelationPoint[] = points
    .filter((p): p is GaugePoint & { corr_252d: string } => p.corr_252d != null)
    .map((p) => ({ obs_date: p.obs_date, value: p.corr_252d }));

  const first = anchor[0];
  const last = anchor[anchor.length - 1];

  return (
    <BoardPanel
      id="anchor-decay"
      title="Anchor letting go · gauge corr_252d"
      questions={["Q4"]}
      basis="REAL"
      source={
        <>
          /api/gold/gauge · history_252d,{" "}
          {plural(anchor.length, "valued observation")} of {points.length} dated rows
          {first && last ? (
            <>
              {" "}
              spanning {first.obs_date} → {last.obs_date}
            </>
          ) : null}
        </>
      }
    >
      {gauge.error ? (
        <p className="cap" style={{ color: "var(--negative)" }}>
          {gauge.error}
        </p>
      ) : anchor.length === 0 ? (
        <p className="cap">
          No valued correlation observation has been stored — the gauge has
          dated rows but no computed window at this instant.
        </p>
      ) : (
        <>
          <div className="chart">
            <CorrelationLineChart
              width={640}
              height={190}
              series={[
                {
                  id: "corr252",
                  label: "gold ↔ real yield · 252d",
                  // Near-neutral ink at heavier weight: this is the anchor, not one of
                  // several channels, and the palette validator rejected the vivid
                  // alternatives against --positive under deuteranopia (ΔE 4.6).
                  color: "var(--text-primary, #e2e8f0)",
                  strokeWidth: 2.25,
                  points: anchor,
                },
              ]}
            />
          </div>
          <p className="cap">
            gold ↔ real-yield correlation, <b>252-day window</b>, as stored{" "}
            <span className="tag real">REAL</span>
          </p>

          <BoardRead testId="macro-anchor-read">
            {first && last && first !== last ? (
              <>
                The measured link reads{" "}
                <span className="num">{Number(first.value).toFixed(2)}</span> →{" "}
                <span className="num">{Number(last.value).toFixed(2)}</span>{" "}
                across the stored history. The board asks this panel for the{" "}
                <b>60-day</b> cut, which is where a decay shows first; the desk
                computes only 252 days, so what is drawn is the slow window and
                the fast one does not exist to draw.
              </>
            ) : (
              <>
                One valued observation is a level, not a decay. The board asks
                for the 60-day window here and the desk computes only 252 days.
              </>
            )}
          </BoardRead>
        </>
      )}
    </BoardPanel>
  );
}
