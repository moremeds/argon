/** The GOLD COMPASS placeholder, in the two shapes that are NOT a posture.
 *
 *  These used to be one shape. `fetchGoldState` returned `null` both for a
 *  non-2xx response and for a thrown error, so a dead API and a posture the
 *  engine had never computed rendered the same sentence — an operator looking
 *  at the page could not tell an outage from an empty table. Desk invariant 2
 *  requires three states, and the third (answered, with a posture) is the
 *  cockpit itself.
 *
 *  `tone` is the whole distinction, so it is required rather than defaulted:
 *  a caller cannot get the failure colour by forgetting to say which state it
 *  is in.
 */
type Props = {
  /** Rendered uppercase. Names the state, not the remedy. */
  headline: string;
  /** The API error text, verbatim and in its own case. Failure state only. */
  detail?: string;
  /** One sentence on what is and is not known. */
  body: string;
  tone: "failed" | "pending";
};

const SHELL: React.CSSProperties = {
  padding: 32,
  background: "var(--bg-base, #060810)",
  minHeight: "100vh",
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  letterSpacing: 1.5,
};

export function GoldPostureNotice({ headline, detail, body, tone }: Props) {
  const accent = tone === "failed" ? "var(--negative)" : "var(--text-muted)";
  return (
    <main style={SHELL}>
      <p style={{ margin: 0, textTransform: "uppercase", color: accent }}>
        {headline}
      </p>
      {detail ? (
        <p
          style={{
            margin: "12px 0 0",
            maxWidth: 720,
            fontSize: 12,
            letterSpacing: 0,
            lineHeight: 1.6,
            color: accent,
            wordBreak: "break-word",
          }}
        >
          {detail}
        </p>
      ) : null}
      <p
        style={{
          margin: "12px 0 0",
          maxWidth: 720,
          fontSize: 13,
          letterSpacing: 0.3,
          lineHeight: 1.6,
          color: "var(--text-muted)",
        }}
      >
        {body}
      </p>
    </main>
  );
}
