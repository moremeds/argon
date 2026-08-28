import { BoardPanel, MONO_LABEL } from "./BoardPanel";
import {
  ConfidenceArithmeticPanel,
  ConfidenceRepairPanel,
} from "./ConfidencePanels";
import { FactorTable, seriesList, type MacroFactor } from "./FactorTable";
import type { MacroDomainState } from "../types";

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
 * Tab 03 — the four panels the board specifies for Inflation.
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
    <div style={{ display: "grid", gap: 14 }}>
      <ConfidenceArithmeticPanel
        reasons={state.confidence_reasons ?? []}
        confidence={state.confidence}
        endpoint="/api/macro/inflation"
      />

      <ConfidenceRepairPanel
        reasons={state.confidence_reasons ?? []}
        confidence={state.confidence}
      />

      <BoardPanel
        id="realized-inflation"
        title="Realized inflation"
        questions={["Q1"]}
        basis="REAL"
        source={
          <>
            /api/macro/inflation · factors[] where causal_role is realized,
            breadth or stickiness — {seriesList(realized) || "none"}. Δ window
            is <code>change_over_window</code> as published; the engine attaches
            no unit to it, so none is invented here.
          </>
        }
      >
        <FactorTable
          factors={realized}
          fallingIsGood
          testId="inflation-realized-table"
        />
        <p
          style={{
            margin: 0,
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--text-secondary)",
          }}
        >
          Direction is coloured for a macro reader, not a price chart: falling
          inflation is green here because it is an improvement, independent of
          what green means on any asset on this desk.
        </p>
      </BoardPanel>

      <ExpectationsPanel
        survey={survey}
        citedRates={citedRates}
        citationError={citationError}
      />
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
      basis="REAL"
      source={
        <>
          survey leg: /api/macro/inflation · factors[causal_role=
          expectations_survey]. Market leg: /api/macro/rates ·{" "}
          {BREAKEVEN_SERIES}, cited from the domain that owns it and never
          recomputed here.
        </>
      }
    >
      <FactorTable factors={survey} testId="inflation-survey-table" />

      <div style={{ display: "grid", gap: 6 }}>
        <div style={MONO_LABEL}>
          market-implied · cited from the rates domain
        </div>
        {citationError ? (
          <p
            style={{ margin: 0, fontSize: 12, color: "var(--negative)" }}
            data-testid="expectations-citation-error"
          >
            The rates state could not be read ({citationError}), so the
            market-implied leg is missing. The survey reading above stands
            alone, which is half the picture and must not be read as the whole
            of it.
          </p>
        ) : breakeven ? (
          <div style={{ fontSize: 12, color: "var(--text-secondary)" }}>
            <span
              style={{
                fontFamily: "var(--font-mono), monospace",
                color: "var(--text-primary)",
              }}
            >
              {BREAKEVEN_SERIES} {fmtPercent(breakeven.value)}
            </span>{" "}
            10-year breakeven · {breakeven.period_end} ·{" "}
            {citedRates?.engine_version} as of {citedRates?.as_of.slice(0, 10)}
          </div>
        ) : (
          <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>
            The rates state answered and carries no {BREAKEVEN_SERIES} factor,
            so there is no market-implied leg to cite at this instant.
          </p>
        )}
        {forward ? null : (
          <p style={{ margin: 0, fontSize: 11, color: "var(--text-muted)" }}>
            The board also lists the {FORWARD_SERIES} 5y5y forward. No published
            state carries it, so it is named as missing rather than sourced from
            somewhere that has not been cited.
          </p>
        )}
      </div>

      {gap === null ? null : (
        <p
          data-testid="expectations-split"
          style={{
            margin: 0,
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--text-secondary)",
          }}
        >
          Household and market expectations are{" "}
          <strong style={{ color: "var(--text-primary)" }}>
            {Math.abs(gap).toFixed(2)}pp apart
          </strong>{" "}
          ({surveyLevel.toFixed(2)}% survey against {marketLevel.toFixed(2)}%
          priced). They are two different populations answering two different
          questions, and the size of the gap is the context a single state label
          cannot carry.
        </p>
      )}

      <div
        style={{
          borderLeft: "2px solid var(--warning)",
          paddingLeft: 10,
          display: "grid",
          gap: 4,
        }}
      >
        <div style={MONO_LABEL}>refusal</div>
        <p
          style={{
            margin: 0,
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--text-secondary)",
          }}
        >
          No 0–100 composite of these readings. Averaging a survey against a
          priced breakeven produces one tidy number by destroying the only thing
          on this panel worth reading, which is that the two disagree.
        </p>
      </div>
    </BoardPanel>
  );
}
