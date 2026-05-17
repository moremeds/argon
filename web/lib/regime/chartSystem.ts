import chartSystemSpec from "./chart-system-spec.json";

export const REGIME_CHART_SYSTEM = chartSystemSpec;

export type ChartSeriesRole = keyof typeof chartSystemSpec.seriesRoles;
export type ChartFamily = keyof typeof chartSystemSpec.families;

export type ChartLegendItem = {
  label: string;
  role?: ChartSeriesRole;
  color?: string;
};

export function chartSeriesColor(role: ChartSeriesRole): string {
  const series = chartSystemSpec.seriesRoles[role];
  return `var(${series.cssVar}, ${series.fallback})`;
}

export function chartSeriesFallback(role: ChartSeriesRole): string {
  return chartSystemSpec.seriesRoles[role].fallback;
}

export function resolveChartSeriesColor(
  role: ChartSeriesRole,
  root?: Element | null,
): string {
  const series = chartSystemSpec.seriesRoles[role];
  const target =
    root ?? (typeof document !== "undefined" ? document.documentElement : null);

  if (!target || typeof getComputedStyle !== "function") {
    return series.fallback;
  }

  const resolved = getComputedStyle(target)
    .getPropertyValue(series.cssVar)
    .trim();
  return resolved || series.fallback;
}

export function chartFamilyLabel(family: ChartFamily): string {
  return chartSystemSpec.families[family].label;
}
