import { BoardPanel, BoardRead, BoardRefusal } from "./BoardPanel";
import {
  ConfidenceArithmeticPanel,
  ConfidenceRepairPanel,
} from "./ConfidencePanels";
import { FactorTable, seriesList, type MacroFactor } from "./FactorTable";
import type { MacroDomainState } from "../types";
import { periodLabel, seriesLabel } from "../presentation";

/** What the board's "realized inflation" table carries: the prints themselves plus the
 *  two cuts that say how broad they are. */
const REALIZED_ROLES = new Set(["realized", "breadth", "stickiness"]);

/** Household surveys. The market leg is NOT here — see `ExpectationsPanel`. */
const SURVEY_ROLES = new Set(["expectations_survey"]);

/** The market-implied leg the board draws its split against, owned by the rates domain. */
const BREAKEVEN_SERIES = "T10YIE";

/** The board's third expectations row. Absent from every published state we read, and
 *  named here so the absence is reported rather than silently dropped. */
const FORWARD_SERIES = "T5YIFR";

function fmtPercent(raw: string | null | undefined): string {
  const n = raw === null || raw === undefined ? NaN : Number(raw);
  return Number.isFinite(n) ? `${n.toFixed(2)}%` : "—";
}

/**
 * Tab 03 — the four panels the board specifies for Inflation, in the board's two-by-two.
 *
 * `citedRates` is the rates domain's published state, or null. The expectations panel
 * needs the market-implied leg to make its point, and that series is OWNED by the rates
 * domain — the board says so in the row itself, "(single owner)". So it is cited, never
 * re-derived: the number rendered here is the one the rates engine published, carrying
 * that engine's own version and instant, and if the citation is missing the panel says
 * which half it is missing rather than showing a survey reading alone as though it were
 * the whole picture.
 */
export function InflationPanels({
  state,
  citedRates,
  citationError,
}: {
  state: MacroDomainState;
  citedRates: MacroDomainState | null;
  citationError?: string;
}) {
  const factors = (state.factors ?? []) as MacroFactor[];
  const realized = factors.filter((f) => REALIZED_ROLES.has(f.causal_role));
  const survey = factors.filter((f) => SURVEY_ROLES.has(f.causal_role));

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="grid g2">
        <ConfidenceArithmeticPanel
          reasons={state.confidence_reasons ?? []}
          confidence={state.confidence}
          endpoint="/api/macro/inflation"
        />
        <ConfidenceRepairPanel
          reasons={state.confidence_reasons ?? []}
          confidence={state.confidence}
        />
      </div>

      <div className="grid g2">
        <BoardPanel
          id="realized-inflation"
          title="Realized inflation"
          questions={["Q1"]}
          basis="REAL"
          sourceLabel="Pipeline"
          source={
            <>
              /api/macro/inflation factors[] where causal_role is realized,
              breadth or stickiness — {seriesList(realized) || "none"} · PIT:
              available_at ≤ as_of
            </>
          }
        >
          <FactorTable
            factors={realized}
            fallingIsGood
            testId="inflation-realized-table"
          />
          <BoardRead>
            Falling inflation is marked as improvement. Change is shown exactly
            as published; no missing unit is inferred.
          </BoardRead>
        </BoardPanel>

        <ExpectationsPanel
          survey={survey}
          citedRates={citedRates}
          citationError={citationError}
        />
      </div>
    </div>
  );
}

/**
 * Board t3 · "Inflation expectations".
 *
 * Its whole point is the SPLIT — households and the bond market disagree, and the size of
 * that gap is the tradable context the state label alone cannot carry. So the gap is
 * computed from the two published levels rather than asserted, and it prints only when
 * both legs are actually present. The board's own numbers are frozen at its capture
 * instant and are not restated here.
 *
 * The board puts the survey and the cited market leg in ONE table under a `Note` column,
 * which is the right shape: the reader is meant to see two rows disagreeing, not two
 * blocks sitting near each other. The `Note` is where each row says what it is and where
 * it came from.
 */
function ExpectationsPanel({
  survey,
  citedRates,
  citationError,
}: {
  survey: readonly MacroFactor[];
  citedRates: MacroDomainState | null;
  citationError?: string;
}) {
  const ratesFactors = (citedRates?.factors ?? []) as MacroFactor[];
  const breakeven =
    ratesFactors.find((f) => f.series_id === BREAKEVEN_SERIES) ?? null;
  const forward =
    ratesFactors.find((f) => f.series_id === FORWARD_SERIES) ?? null;

  const surveyLevel = survey.length > 0 ? Number(survey[0].value) : NaN;
  const marketLevel = breakeven ? Number(breakeven.value) : NaN;
  const gap =
    Number.isFinite(surveyLevel) && Number.isFinite(marketLevel)
      ? surveyLevel - marketLevel
      : null;

  return (
    <BoardPanel
      id="inflation-expectations"
      title="Inflation expectations"
      questions={["Q1", "Q3"]}
      basis="COMPUTED"
      sourceLabel="Pipeline"
      source={
        <>
          survey leg: /api/macro/inflation factors[causal_role=
          expectations_survey] · market leg: /api/macro/rates {BREAKEVEN_SERIES}
          , cited from the domain that owns it and never recomputed here
        </>
      }
    >
      <div className="tbl-wrap">
        <table data-testid="inflation-survey-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th className="num">Level</th>
              <th>Note</th>
            </tr>
          </thead>
          <tbody>
            {survey.map((f) => (
              <tr key={f.series_id}>
                <td title={f.series_id} data-raw-value={f.series_id}>
                  {seriesLabel(f.series_id)}
                </td>
                <td className="num">{fmtPercent(f.value)}</td>
                <td
                  title={`Covers ${f.period_end}, published ${f.available_at}`}
                >
                  {periodLabel(f.period_end)} · published {f.age_days}d ago —
                  its age is one of the freshness terms in the chain at left
                </td>
              </tr>
            ))}
            {citationError ? (
              <tr data-testid="expectations-citation-error">
                <td>{seriesLabel(BREAKEVEN_SERIES)}</td>
                <td className="num delta-dn">—</td>
                <td>
                  <span className="delta-dn">
                    the rates state could not be read ({citationError})
                  </span>
                  , so the market leg is missing and the survey row above stands
                  alone — half the picture, not the whole of it
                </td>
              </tr>
            ) : breakeven ? (
              <tr>
                <td>{seriesLabel(BREAKEVEN_SERIES)}</td>
                <td className="num">{fmtPercent(breakeven.value)}</td>
                <td>rates-owned series · {breakeven.period_end}</td>
              </tr>
            ) : (
              <tr>
                <td>{seriesLabel(BREAKEVEN_SERIES)}</td>
                <td className="num">—</td>
                <td>
                  the rates state answered and carries no {BREAKEVEN_SERIES}{" "}
                  factor, so there is no market leg to cite at this instant
                </td>
              </tr>
            )}
            {forward ? (
              <tr>
                <td>{seriesLabel(FORWARD_SERIES)}</td>
                <td className="num">{fmtPercent(forward.value)}</td>
                <td>cited from the rates domain · {forward.period_end}</td>
              </tr>
            ) : (
              <tr>
                <td>{seriesLabel(FORWARD_SERIES)}</td>
                <td className="num">—</td>
                <td>
                  on the board, but no published state carries it — named as
                  missing rather than sourced from somewhere uncited
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {gap === null ? null : (
        <BoardRead testId="expectations-split">
          Household and market expectations differ by{" "}
          <b>{Math.abs(gap).toFixed(2)}pp</b> ({surveyLevel.toFixed(2)}% versus{" "}
          {marketLevel.toFixed(2)}%).
        </BoardRead>
      )}

      <BoardRefusal>
        Survey and market pricing remain separate; averaging them would erase
        the disagreement.
      </BoardRefusal>
    </BoardPanel>
  );
}
