export function formatNumber(
  value: number | null | undefined,
  decimals = 2,
): string {
  if (value == null || !Number.isFinite(value)) return "---";
  return value.toFixed(decimals);
}

export function formatPercent(
  value: number | null | undefined,
  decimals = 2,
): string {
  if (value == null || !Number.isFinite(value)) return "---";
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}%`;
}

export function formatSignedNumber(
  value: number | null | undefined,
  decimals = 2,
): string {
  if (value == null || !Number.isFinite(value)) return "---";
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}`;
}
