import { ReplayDatePicker } from "./ReplayDatePicker";

type Props = { obsDate: string };

export function GoldCompassHeader({ obsDate }: Props) {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        gap: 16,
        padding: "16px 24px",
        borderBottom: "1px solid var(--border-dim, #1b2030)",
      }}
    >
      <div>
        <h1
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 18,
            letterSpacing: 2,
            textTransform: "uppercase",
            color: "var(--text-primary, #cfd2db)",
            margin: 0,
          }}
        >
          GOLD COMPASS
        </h1>
        <p
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted, #6b7280)",
            margin: "4px 0 0",
          }}
        >
          Heuristic posture monitor · v1 · obs {obsDate}
        </p>
      </div>
      <ReplayDatePicker initialDate={obsDate} />
    </header>
  );
}
