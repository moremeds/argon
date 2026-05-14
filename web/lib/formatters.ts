export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function fmtSigned(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

export function fmtMoney(
  v: number | null | undefined,
  opts: { signed?: boolean } = {},
): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  const fmt = abs.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (v < 0) return `-$${fmt}`;
  return opts.signed ? `+$${fmt}` : `$${fmt}`;
}

export function fmtDecimal(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtDateTimeWithZone(
  iso: string | null | undefined,
  opts: { timeZone?: string } = {},
): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZoneName: "short",
    ...(opts.timeZone ? { timeZone: opts.timeZone } : {}),
  }).formatToParts(d);
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";
  const timeZoneName = value("timeZoneName");
  const compactZone = timeZoneName === "GMT+8" ? "HKG" : timeZoneName;
  return `${value("year")}/${value("month")}/${value("day")} ${value("hour")}:${value("minute")}:${value("second")} ${compactZone}`;
}

/**
 * Coerce an unknown API value to `number | null` *preserving zero*.
 * `Number(x) || null` is wrong: 0 collapses to null, then the UI renders
 * a missing value where "0" was the right answer (zero return, flat skew, …).
 */
export function toNum(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}
