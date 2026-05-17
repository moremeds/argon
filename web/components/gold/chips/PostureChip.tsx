export type PostureState =
  | "FAVORABLE"
  | "NEUTRAL"
  | "STRETCHED"
  | "SUSPENDED"
  | "DEGRADED";

const colorByState: Record<PostureState, string> = {
  FAVORABLE: "var(--positive, #05ad98)",
  NEUTRAL: "var(--text-secondary, #9aa3b2)",
  STRETCHED: "var(--warning, #f5a623)",
  SUSPENDED: "var(--text-muted, #6b7280)",
  DEGRADED: "var(--negative, #e85d6c)",
};

export function PostureChip({ state }: { state: PostureState }) {
  return (
    <span
      aria-label={`posture ${state.toLowerCase()}`}
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        letterSpacing: 1.5,
        textTransform: "uppercase",
        padding: "2px 6px",
        border: `1px solid ${colorByState[state]}`,
        color: colorByState[state],
        borderRadius: 3,
        whiteSpace: "nowrap",
      }}
    >
      {state}
    </span>
  );
}
