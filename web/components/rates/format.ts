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
