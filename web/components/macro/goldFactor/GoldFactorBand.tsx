import { Zone } from "@/components/macro/overview/Zone";

import {
  AttributionTable,
  DriftVsGoldPanel,
  ExplainedSharePanel,
  RegroupPanel,
  SensitivityHistoryPanel,
  SensitivityPanel,
  YearToDatePanel,
} from "./GoldFactorPanels";
import { MoveBreakdownPanel, YearlyBreakdownPanel } from "./GoldFactorToggles";
import { GoldFlowPanels } from "./GoldFlowPanels";
import type { GoldFactor, GoldFlows } from "./shared";

/**
 * The gold factor model laid out in the sections of design v3: how much of gold's daily
 * move the 10-year real yield, the dollar and the safe-haven spread explain, and each day's
 * move split into those parts. Shared by the overview (tab 00) and tab 05, so the two show
 * the same panels. Live only: the endpoints take no date.
 */

/** Research result: the sensitivities with their intervals, and the explained share. */
export function GoldResearchConclusion({ data }: { data: GoldFactor }) {
  const last = data.points.at(-1);
  return (
    <div className="grid g2">
      {last ? <SensitivityPanel last={last} /> : null}
      <ExplainedSharePanel data={data} />
    </div>
  );
}

/** What moved gold: the window breakdown, the running total, each year, the slope history,
 *  then flows and holdings when they were read. */
export function GoldBreakdownSection({
  data,
  flows,
  scope,
}: {
  data: GoldFactor;
  flows: GoldFlows | null;
  scope: string;
}) {
  return (
    <section data-testid="gold-factor-band">
      <Zone
        kicker="Gold"
        label="What moved gold"
        scope={scope}
        testKey="gold-breakdown"
      />
      <div className="grid g2">
        <MoveBreakdownPanel data={data} />
        <YearToDatePanel data={data} />
      </div>
      <div className="grid g2" style={{ marginTop: 12 }}>
        <YearlyBreakdownPanel years={data.years} />
        <SensitivityHistoryPanel data={data} />
      </div>
      {flows ? <GoldFlowPanels flows={flows} /> : null}
    </section>
  );
}

/** Attribution review: why "unexplained" looks like a hole this year, and the regrouping that fixes
 *  the reading without refitting anything. */
export function GoldAttributionSection({ data }: { data: GoldFactor }) {
  return (
    <section data-testid="gold-factor-attribution">
      <Zone
        kicker="Review"
        label="Attribution review"
        scope="regrouped, not refit"
        testKey="gold-attribution"
      />
      <div className="grid g2">
        <DriftVsGoldPanel data={data} />
        <RegroupPanel data={data} />
      </div>
      <AttributionTable years={data.years} />
    </section>
  );
}
