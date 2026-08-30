import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import type { components } from "@/lib/types";

import { PostureChip, type PostureState } from "../chips/PostureChip";

import { ArticleZoneCard } from "./ArticleZoneCard";
import { GprCard } from "./GprCard";
import { InfExpCard } from "./InfExpCard";
import { RealRateCard } from "./RealRateCard";
import { UsdTrendCard } from "./UsdTrendCard";

type C = components["schemas"]["GoldCyclicalPostureModel"];

/**
 * Board t5 — "L2 cyclical readings (dimmed display)".
 *
 * ### The dimming is published elsewhere, and must say so
 *
 * `dimmed` is the transmission gauge's verdict, not this panel's. Its readings are true of
 * their own inputs either way — the real rate IS what it is — and what a suspended gauge
 * changes is whether the relationship they are read THROUGH is currently transmitting. So
 * the panel keeps rendering everything, at 0.68 opacity, with a sentence naming what
 * dimmed it. A dimmed panel with no such sentence reads as broken rather than as
 * conditional, which is the failure mode the board's own "(dimmed display)" heading is
 * warning about.
 */
export function CyclicalPanel({
  cyclical,
  dimmed = false,
}: {
  cyclical: C;
  /** True when the transmission gauge reads `suspended`. Owned by the layout, because
   *  this panel cannot see the gauge and must not re-derive its verdict. */
  dimmed?: boolean;
}) {
  return (
    <BoardPanel
      id="cyclical"
      title="Cyclical readings"
      questions={["Q1"]}
      basis="REAL"
      dim={dimmed}
      source={
        <>
          /api/gold/state cyclical · real rates, the dollar, geopolitical risk
          and inflation compensation, each as its own publisher released it
        </>
      }
    >
      <div className="lgd">
        <PostureChip
          state={(cyclical.posture_chip ?? "NEUTRAL") as PostureState}
        />
        <span className="dir">Event-hedge context</span>
      </div>

      {dimmed ? (
        <p className="cap" data-testid="gold-cyclical-dim-note">
          <b style={{ color: "var(--warning)" }}>Context only.</b> Real-yield
          transmission is suspended; the inputs remain valid but do not drive gold here.
        </p>
      ) : null}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: 8,
        }}
      >
        <RealRateCard cyclical={cyclical} />
        <UsdTrendCard cyclical={cyclical} />
        <GprCard cyclical={cyclical} />
        <InfExpCard cyclical={cyclical} />
      </div>

      <ArticleZoneCard cyclical={cyclical} />

      {cyclical.narrative_text ? (
        <details className="data-details">
          <summary>Publisher note</summary>
          <p className="cap">{cyclical.narrative_text}</p>
        </details>
      ) : null}
    </BoardPanel>
  );
}
