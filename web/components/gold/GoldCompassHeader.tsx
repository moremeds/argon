import { ReplayDatePicker } from "./ReplayDatePicker";

type Props = {
  obsDate: string;
  /**
   * Whether to draw this header's own date picker.
   *
   * `true` on the standalone `/gold/replay/<date>` surface, which has no other control.
   * `false` on the macro desk's gold tab, which sits under `ReplayControl` — the desk's
   * one control, labelled with the tab's declared clock. Two pickers over one page would
   * be two questions with one answer between them, and this one navigates OFF the desk to
   * `/gold/replay/<date>`, so the operator would leave without meaning to.
   */
  showReplayPicker?: boolean;
};

export function GoldCompassHeader({ obsDate, showReplayPicker = true }: Props) {
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
      {showReplayPicker ? <ReplayDatePicker initialDate={obsDate} /> : null}
    </header>
  );
}
