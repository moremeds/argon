export function toFiniteNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number") return Number.isFinite(value) ? value : fallback;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }
  return fallback;
}

export function fmtValue(value: unknown, unit = "", digits = 2): string {
  if (value == null) return "n/a";
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  return `${n.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

export function fmtSigned(value: unknown, unit = "", digits = 1): string {
  if (value == null) return "n/a";
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}${unit ? ` ${unit}` : ""}`;
}

export function statusLabel(status: string | undefined): string {
  if (status === "missing") return "Unavailable";
  if (status === "partial") return "Partial";
  if (status === "stale") return "Stale";
  return "Live";
}

const ET_DATE_TIME = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/**
 * `YYYY-MM-DD HH:MM ET`. Stored instants (`first_seen_at`, `last_seen_at`) print
 * on the New York wall clock — the desk's convention — so the same stored value
 * reads the same on every machine instead of drifting with the reader's zone.
 */
export function fmtEtTimestamp(value: unknown): string {
  if (value == null) return "—";
  const d = new Date(String(value));
  if (Number.isNaN(d.getTime())) return "—";
  const parts = Object.fromEntries(
    ET_DATE_TIME.formatToParts(d).map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute} ET`;
}

/** ``toFiniteNumber`` for an optional field: absent and unparseable both read null. */
export function finiteOrNull(value: unknown): number | null {
  if (value == null) return null;
  const n = toFiniteNumber(value, Number.NaN);
  return Number.isFinite(n) ? n : null;
}
