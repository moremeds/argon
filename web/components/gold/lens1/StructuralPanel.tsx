import { GOLD_STRUCTURAL_WIDTH } from "@/components/macro/chartGeometry";
import type { components } from "@/lib/types";

import { PostureChip, type PostureState } from "../chips/PostureChip";

import { CbReservesCard } from "./CbReservesCard";
import { ComexRegimeCard } from "./ComexRegimeCard";
import { CotPositioningCard } from "./CotPositioningCard";
import { EtfFlowCard } from "./EtfFlowCard";
import { FxBasketCard } from "./FxBasketCard";
import { GoldHoldingsVsPriceChart } from "./GoldHoldingsVsPriceChart";
import { StructuralPostureText } from "./StructuralPostureText";
import { UwSkewCard } from "./UwSkewCard";

type S = components["schemas"]["GoldStructuralPostureModel"];

export function StructuralPanel({ structural }: { structural: S }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h2
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              letterSpacing: 1.8,
              textTransform: "uppercase",
              color: "var(--text-primary, #cfd2db)",
              margin: 0,
            }}
          >
            LENS 1 · STRUCTURAL FLOW
          </h2>
          <PostureChip
            state={(structural.posture_chip ?? "NEUTRAL") as PostureState}
          />
        </div>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted, #6b7280)",
          }}
        >
          {structural.state_label ?? "—"}
        </span>
      </div>

      <GoldHoldingsVsPriceChart
        goldHistory={structural.gold_history ?? []}
        gldHistory={structural.gld_history ?? []}
        cbCountryHistory={structural.cb_country_history ?? []}
        width={GOLD_STRUCTURAL_WIDTH}
        height={Math.round((GOLD_STRUCTURAL_WIDTH * 200) / 1040)}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 12,
        }}
      >
        <CbReservesCard structural={structural} />
        <EtfFlowCard structural={structural} />
        <ComexRegimeCard structural={structural} />
        <CotPositioningCard structural={structural} />
        <UwSkewCard structural={structural} />
        <FxBasketCard structural={structural} />
      </div>

      <StructuralPostureText structural={structural} />
    </div>
  );
}
