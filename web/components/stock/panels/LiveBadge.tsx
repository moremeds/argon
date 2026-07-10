// Small LIVE/EOD chip for the Technicals tab. Green LIVE · HH:MM:SS · <source>
// when the cached live-technicals capture is within maxAgeSec; grey EOD
// otherwise (stale or absent — the daily payload is authoritative then).

// Module-level so the time read (Date.now) stays out of the component render
// body — the badge is inherently clock-dependent; parents re-poll every 25s.
function badgeLabel(
  captured_at: string | null | undefined,
  source: string | null | undefined,
  maxAgeSec: number,
): { live: boolean; label: string } {
  const ts = captured_at ? new Date(captured_at) : null;
  const ageSec = ts ? (Date.now() - ts.getTime()) / 1000 : Infinity;
  const live = ts != null && Number.isFinite(ageSec) && ageSec <= maxAgeSec;
  const label = live
    ? `LIVE · ${ts!.toLocaleTimeString([], { hour12: false })}${source ? ` · ${source}` : ""}`
    : "EOD";
  return { live, label };
}

export function LiveBadge({
  captured_at,
  source,
  maxAgeSec = 900,
  compact = false,
}: {
  captured_at?: string | null;
  source?: string | null;
  maxAgeSec?: number;
  compact?: boolean;
}) {
  const { live, label } = badgeLabel(captured_at, source, maxAgeSec);
  const text = compact ? (live ? "LIVE" : "EOD") : label;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        fontSize: 10,
        letterSpacing: 1,
        textTransform: "uppercase",
        fontFamily: "var(--font-mono)",
        color: live ? "var(--positive)" : "var(--text-muted)",
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: live ? "var(--positive)" : "var(--text-muted)",
          display: "inline-block",
        }}
      />
      {text}
    </span>
  );
}
