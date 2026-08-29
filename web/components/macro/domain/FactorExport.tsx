import type { MacroDomainSlot } from "../types";

import { BoardPanel, BoardRead, BoardRefusal } from "./BoardPanel";
import type { MacroFactor } from "./FactorTable";
import { humanizeIdentifier, seriesLabel } from "../presentation";

/**
 * Board tab 07 — Factor Export · Equity Consumes Macro.
 *
 * ### Why this tab is assembly and not analysis
 *
 * The board's own build note says it: _"read side is pure assembly (every number above is
 * already extractable from existing tables — this page is the proof)"_. Each domain state
 * already publishes `factors[]`, and each factor already carries the four things an export
 * row needs — a value, a change over its window, the instant it became available, and the
 * causal role that says what kind of thing it is. This tab flattens the four states into
 * one table and adds nothing. If a number here disagreed with the same number on the
 * domain's own tab, this page would be the bug.
 *
 * ### The direction contract, and why it is the tab's whole point
 *
 * `equity → reads → macro factor`, never the reverse. The macro desk derives no equity
 * exposure; it guarantees the factor is point-in-time correct and the burden of proving
 * predictive power sits with each consumer's own out-of-sample test. That is not modesty,
 * it is the measured outcome: MC6 returned `descriptive_only`, and MC5 was shut.
 *
 * ### Continuous rows are the payload; the four state LABELS are not
 *
 * The board is explicit and gives the measured reason: state labels chatter — inflation
 * flipped four times in 68 months, because a classifier boundary sitting at the median
 * chatters maximally. An equity backtest that joins a chattering label gets boundary
 * noise, not macro information. So the labels appear here as one row that names itself as
 * context and points at the tabs that own them, never as an exportable column.
 */

/**
 * Keyed by the ROUTE name, not by `MacroDomainKey`.
 *
 * The two vocabularies disagree on exactly one domain: the desk's causal-order key is
 * `policy_rates` while the endpoint is `/api/macro/rates`. This tab is a flattening of
 * four HTTP answers, so it keys on what it actually called — mapping through the causal
 * key here would gain nothing and give the mismatch a second place to be got wrong.
 */
export type ExportDomain = "inflation" | "rates" | "usd" | "gold";

/** In the board's own listed order. */
const EXPORT_DOMAINS: readonly ExportDomain[] = [
  "inflation",
  "rates",
  "usd",
  "gold",
];

export type FactorExportSlots = Partial<Record<ExportDomain, MacroDomainSlot>>;

type Row = {
  domain: string;
  factor: MacroFactor;
};

function rowsFor(slots: FactorExportSlots): Row[] {
  const out: Row[] = [];
  for (const d of EXPORT_DOMAINS) {
    const state = slots[d]?.value;
    if (!state) continue;
    for (const factor of (state.factors ?? []) as MacroFactor[]) {
      out.push({ domain: d, factor });
    }
  }
  return out;
}

function fmtValue(f: MacroFactor): string {
  const n = Number(f.value);
  if (!Number.isFinite(n)) return "—";
  if (f.unit.startsWith("percent")) return `${n.toFixed(2)}%`;
  return n.toFixed(Math.abs(n) >= 100 ? 2 : 3);
}

function fmtDelta(f: MacroFactor): string {
  const raw = f.change_over_window;
  const n = raw === null || raw === undefined ? NaN : Number(raw);
  if (!Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(2)}`;
}

/** The board's "Data as-of" is the availability instant, not the period end — that is the
 *  whole point of a point-in-time export, so it is the one that reaches the column. The
 *  period end travels beside it because a reader needs both to know what a stale row is. */
function fmtAsOf(f: MacroFactor): string {
  const at = f.available_at.slice(0, 10);
  return at === f.period_end ? at : `${at} · per ${f.period_end}`;
}

/**
 * The one panel on this tab that carries numbers.
 *
 * Every domain that failed to answer is named rather than dropped — an export whose
 * coverage silently depends on which engines happened to be up is worse than one that is
 * incomplete and says so, because the consumer joining it cannot see the difference.
 */
export function FactorVectorPanel({ slots }: { slots: FactorExportSlots }) {
  const rows = rowsFor(slots);
  const missing = EXPORT_DOMAINS.filter((d) => !slots[d]?.value);

  return (
    <BoardPanel
      id="factor-vector"
      title="Current factor vector"
      questions={["Q1"]}
      basis="REAL"
      source={
        <>
          /api/macro/{"{"}inflation,rates,usd,gold{"}"} <code>factors[]</code> —
          flattened, not recomputed. Every row is the same number the
          domain&apos;s own tab prints, carried with its availability instant
          and causal role.
        </>
      }
    >
      {rows.length === 0 ? (
        <BoardRead bad testId="factor-vector-empty">
          No domain answered for this instant, so there is no vector to export.
          That is a statement about the engines, not about the macro world.
        </BoardRead>
      ) : (
        <div className="tbl-wrap">
          <table data-testid="factor-vector-table">
            <thead>
              <tr>
                <th>Factor</th>
                <th className="num">Current</th>
                <th className="num">Δ window</th>
                <th className="num">Data as-of</th>
                <th>Type</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ domain, factor }) => (
                <tr key={`${domain}-${factor.name}-${factor.series_id}`}>
                  {/* Series id alone. `name` is `<role>:<series_id>` for most rows and
                      identical to the series id for the positioning ones, so printing it
                      underneath restated the cell in every row; the role it carries
                      reaches the Type column instead, which is where the board puts it. */}
                  <td title={factor.series_id} data-raw-value={factor.series_id}>
                    {seriesLabel(factor.series_id)}
                  </td>
                  <td className="num">{fmtValue(factor)}</td>
                  <td className="num">{fmtDelta(factor)}</td>
                  <td className="num">{fmtAsOf(factor)}</td>
                  <td>
                    continuous · {domain} ·{" "}
                    {humanizeIdentifier(factor.causal_role)}
                  </td>
                </tr>
              ))}
              {/* The board's own last row. It is here to be REFUSED, not consumed. */}
              <tr>
                <td>state labels ×4</td>
                <td className="num">see each domain tab</td>
                <td className="num">—</td>
                <td className="num">—</td>
                <td>labels · context only</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}

      <BoardRead testId="factor-vector-read">
        Continuous values are exportable; discrete state labels are context.
        {missing.length > 0 ? (
          <>
            {" "}
            <b>
              {missing.length} of {EXPORT_DOMAINS.length} domains did not answer
            </b>{" "}
            for this instant ({missing.join(", ")}), so this vector is missing
            their rows.
          </>
        ) : null}
      </BoardRead>
    </BoardPanel>
  );
}

/**
 * The delivery form. `PLANNED`, and it must stay that way until the route exists.
 *
 * The board tags this panel `plan` and describes an endpoint and a nightly table that do
 * not exist yet. Rendering either as though it were live would be the one thing the basis
 * vocabulary exists to prevent — so no path here is presented as callable, and the panel
 * carries no value of any kind.
 */
export function DeliveryFormPanel() {
  return (
    <BoardPanel
      id="factor-delivery"
      title="Delivery plan"
      questions={["Q7"]}
      basis="PLANNED"
      sourceLabel="Status"
      source="no route and no table exist yet; nothing on this panel is callable today"
    >
      <ul
        style={{
          margin: 0,
          paddingLeft: 18,
          fontSize: 12.5,
          lineHeight: 1.6,
          color: "var(--text-secondary)",
        }}
        data-testid="factor-delivery-list"
      >
        <li>
          <b>API</b> — one point-in-time JSON row per factor.
        </li>
        <li>
          <b>Table</b> — one daily vector after the nightly snapshot.
        </li>
        <li>
          <b>Consumer</b> — each strategy tests significance independently.
        </li>
      </ul>
      <BoardRead>
        Reading works today; the API and materialized table are still planned.
      </BoardRead>
    </BoardPanel>
  );
}

/** The board's Q7 panel, and the reason the whole tab is allowed to exist. It is a PANEL
 *  wrapping a refusal, which is the board's own shape here — the tab's own boundary is a
 *  finding about the desk, so it earns a heading and a provenance line like any other. */
export function ExportRefusalPanel() {
  return (
    <BoardPanel
      id="factor-refusal"
      title="Limit"
      questions={["Q7"]}
      basis="PLANNED"
      sourceLabel="Basis"
      source="the desk's own pre-test verdict; no forward-return claim is computed anywhere on this tab"
    >
      <RefusalBody />
    </BoardPanel>
  );
}

function RefusalBody() {
  return (
    <BoardRefusal testId="factor-export-refusal">
      No predictive claim. This vector describes the current macro state;
      forward-return relevance must be earned in each consumer&apos;s out-of-sample
      test.
    </BoardRefusal>
  );
}
