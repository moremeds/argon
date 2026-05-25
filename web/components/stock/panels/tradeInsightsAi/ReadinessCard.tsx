import { Fragment } from "react";

import type { TradeInsightsAiAnalysisResponse } from "@/lib/api";
import { LegsTable } from "./LegsTable";
import {
  AnalysisCard,
  BulletList,
  ProviderKeyValueGrid,
  type Tone,
  plainText,
} from "./ui";

type Outcome = NonNullable<TradeInsightsAiAnalysisResponse["outcome"]>;

export function ReadinessCard({
  preferred,
  toneFromText,
}: {
  preferred: Outcome["preferred_expression"];
  toneFromText: (value: string | null | undefined) => Tone;
}) {
  return (
    <AnalysisCard
      title="Trade Setup Readiness"
      subtitle={
        preferred ? preferred.title : "No trade structure cleared validation"
      }
      tone={toneFromText(preferred?.status_observed)}
    >
      {preferred ? (
        <Fragment>
          <ProviderKeyValueGrid
            items={[
              { label: "Structure", value: preferred.structure },
              { label: "Entry", value: preferred.estimated_entry },
              {
                label: "Max Profit",
                value: preferred.max_profit_observed,
              },
              { label: "Max Loss", value: preferred.max_loss_observed },
              { label: "R:R", value: preferred.reward_risk },
              { label: "Status", value: preferred.status_observed },
            ]}
          />
          {preferred.strike_role && (
            <ProviderKeyValueGrid
              items={[
                {
                  label: "Trigger",
                  value: preferred.strike_role.trigger_level || "—",
                },
                {
                  label: "Target",
                  value: preferred.strike_role.target_level || "—",
                },
                {
                  label: "Invalidate",
                  value: preferred.strike_role.invalid_level || "—",
                },
                {
                  label: "Long leg",
                  value: preferred.strike_role.long_leg_role || "n/a",
                },
                {
                  label: "Short leg",
                  value: preferred.strike_role.short_leg_role || "n/a",
                },
              ]}
            />
          )}
          {preferred.legs && <LegsTable legs={preferred.legs} />}
          <div style={{ color: "var(--text-primary)", fontSize: 13 }}>
            {plainText(preferred.why)}
          </div>
          <BulletList items={preferred.management_notes ?? []} limit={3} />
        </Fragment>
      ) : (
        <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
          No entry candidate is ready yet. The generated structures stay pending
          validation until the checklist passes.
        </div>
      )}
    </AnalysisCard>
  );
}
