// RegimePillState carries BOTH warning_state values (NONE/CCA/BTDA/BOTH) and
// speed.state values (NEUTRAL/CCA/BTDA/BOTH). They overlap but `NEUTRAL` is
// speed-only and `NONE` is warning-only. Pill supports both vocabularies so
// the same component can render either field.
export type RegimePillState =
  | "NONE"
  | "NEUTRAL"
  | "CONFIRMED_CANARY_ACTIVE"
  | "BUY_THE_DIP_ACTIVE"
  | "BOTH_ACTIVE_AMBIGUOUS";

const STYLES: Record<RegimePillState, { label: string; classes: string }> = {
  NONE: { label: "No Signal", classes: "border-zinc-700 text-zinc-400" },
  NEUTRAL: { label: "Neutral", classes: "border-zinc-700 text-zinc-400" },
  CONFIRMED_CANARY_ACTIVE: {
    label: "Confirmed Canary",
    classes: "border-red-700/60 text-red-300 bg-red-950/30",
  },
  BUY_THE_DIP_ACTIVE: {
    label: "Buy The Dip",
    classes: "border-emerald-700/60 text-emerald-300 bg-emerald-950/30",
  },
  BOTH_ACTIVE_AMBIGUOUS: {
    label: "Ambiguous (Both)",
    classes: "border-amber-700/60 text-amber-300 bg-amber-950/30",
  },
};

function joinClasses(...parts: Array<string | undefined>) {
  return parts.filter(Boolean).join(" ");
}

export function RegimePill({
  state,
  className,
}: {
  state: RegimePillState;
  className?: string;
}) {
  const s = STYLES[state];
  return (
    <span
      className={joinClasses(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        s.classes,
        className,
      )}
    >
      <span aria-hidden="true">●</span>
      {s.label}
    </span>
  );
}
