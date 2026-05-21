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

export function fmtMoneyAbbrev(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v === 0) return "$0";
  const sign = v >= 0 ? "+" : "-";
  const abs = Math.abs(v);
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

export function fmtDecimal(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtTimeOfDay(
  iso: string | null | undefined,
  opts: { timeZone?: string } = {},
): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    ...(opts.timeZone ? { timeZone: opts.timeZone } : {}),
  }).format(d);
}

export function fmtRelativeAgo(
  iso: string | null | undefined,
  now: Date = new Date(),
): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const deltaMs = now.getTime() - d.getTime();
  if (deltaMs < 0) return "in future";
  const sec = Math.floor(deltaMs / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  if (hr < 24) return remMin === 0 ? `${hr}h ago` : `${hr}h ${remMin}m ago`;
  const day = Math.floor(hr / 24);
  return `${day}d ago`;
}

export function fmtRelativeDay(
  iso: string | null | undefined,
  today: Date = new Date(),
): string {
  if (!iso) return "—";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return "—";
  const todayUtc = Date.UTC(
    today.getUTCFullYear(),
    today.getUTCMonth(),
    today.getUTCDate(),
  );
  const days = Math.round((todayUtc - d.getTime()) / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days > 1) return `${days}d ago`;
  return "in future";
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
