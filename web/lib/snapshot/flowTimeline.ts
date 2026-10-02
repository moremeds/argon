// Options timeline series, verbatim from FlowTab.tsx TimelineSection
// (per-row totals and put/call ratios). P/C uses call_volume as the
// denominator: a real put_volume of 0 must chart as 0, not missing — a null
// or zero call_volume means "no ratio", so the point drops to null.
import type { components } from "@/lib/types";

export type OptionsDailyRow = components["schemas"]["OptionsDailyRow"];

export type FlowTimelineSeries = {
  dates: OptionsDailyRow["date"][];
  totalVol: (number | null)[];
  pcVol: (number | null)[];
  totalOi: (number | null)[];
  pcOi: (number | null)[];
};

export function flowTimelineSeries(
  timeline: OptionsDailyRow[],
): FlowTimelineSeries {
  const dates = timeline.map((r) => r.date);
  const totalVol = timeline.map((r) =>
    r.call_volume == null || r.put_volume == null
      ? null
      : r.call_volume + r.put_volume,
  );
  const pcVol = timeline.map((r) =>
    r.call_volume != null && r.call_volume !== 0 && r.put_volume != null
      ? r.put_volume / r.call_volume
      : null,
  );
  const totalOi = timeline.map((r) =>
    r.call_open_interest == null || r.put_open_interest == null
      ? null
      : r.call_open_interest + r.put_open_interest,
  );
  const pcOi = timeline.map((r) =>
    r.call_open_interest != null &&
    r.call_open_interest !== 0 &&
    r.put_open_interest != null
      ? r.put_open_interest / r.call_open_interest
      : null,
  );
  return { dates, totalVol, pcVol, totalOi, pcOi };
}
