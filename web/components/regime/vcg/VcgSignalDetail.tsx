"use client";

import { Zap } from "lucide-react";

import InfoTooltip from "../InfoTooltip";
import { type VcgSignal } from "@/lib/regime/useVcg";
import { interpretationLabel } from "./format";
import VcgSignalTiers from "./VcgSignalTiers";
import VcgAttribution from "./VcgAttribution";

/* Signal Detail section: tier/VVIX/EDR/bounce (left) + attribution (right). */
export default function VcgSignalDetail({
  sig,
  attr,
  interpColor,
}: {
  sig: VcgSignal;
  attr: NonNullable<VcgSignal["attribution"]>;
  interpColor: string;
}) {
  return (
    <div className="section">
      <div className="section-header">
        <div className="section-title">
          <Zap size={14} />
          Signal Detail
          <InfoTooltip text="Severity tier (1=critical, 2=high, 3=elevated), VVIX amplifier, and bounce conditions. Tier activates when ro=1 (Tier 1/2) or edr=1 (Tier 3)." />
        </div>
        <span
          className="pill"
          style={{
            background: interpColor,
            color:
              sig.interpretation === "NORMAL" || sig.interpretation === "BOUNCE"
                ? "#000"
                : "#fff",
            fontSize: "9px",
          }}
          data-testid="vcg-interpretation-pill"
        >
          {interpretationLabel(sig.interpretation)}
        </span>
      </div>

      <div className="metrics-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
        {/* Left: Tier + VVIX severity + EDR/Bounce */}
        <VcgSignalTiers sig={sig} />

        {/* Right: Attribution bars */}
        <VcgAttribution sig={sig} attr={attr} />
      </div>
    </div>
  );
}
