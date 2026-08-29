"use client";

import { useRef, useState } from "react";

import type { components } from "@/lib/types";
import { api } from "@/lib/api";

type LensId = "structural" | "cyclical" | "valuation";
type LensResponse = components["schemas"]["GoldLensResponse"];
type Point = components["schemas"]["GoldInputSeriesPoint"];
const LENS_IDS: LensId[] = ["structural", "cyclical", "valuation"];

export type GoldLensDetailSlot = {
  lensId: LensId;
  response: LensResponse | null;
  error?: string;
};

function sparkline(points: Point[]): string {
  const values = points
    .map((point) => Number(point.value))
    .filter(Number.isFinite);
  if (values.length === 0) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  return values.map((value, index) => {
    const x = values.length === 1 ? 60 : (index / (values.length - 1)) * 120;
    const y = span === 0 ? 12 : 22 - ((value - min) / span) * 20;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

export function GoldLensDetailDisclosure({
  slots,
}: {
  slots?: GoldLensDetailSlot[];
}) {
  const [loadedSlots, setLoadedSlots] = useState(slots);
  const [loading, setLoading] = useState(false);
  const requested = useRef(slots !== undefined);
  const series = (loadedSlots ?? []).flatMap((slot) =>
    Object.entries(slot.response?.detail ?? {}).map(([name, points]) => ({
      lensId: slot.lensId,
      name,
      points: [...points].sort((a, b) =>
        a.obs_date.localeCompare(b.obs_date),
      ),
    })),
  );
  const failures = (loadedSlots ?? []).filter((slot) => slot.error);

  async function loadLensDetails() {
    if (requested.current) return;
    requested.current = true;
    setLoading(true);
    const results = await Promise.all(
      LENS_IDS.map(async (lensId): Promise<GoldLensDetailSlot> => {
        try {
          return { lensId, response: await api.goldLens(lensId) };
        } catch (error) {
          return {
            lensId,
            response: null,
            error:
              error instanceof Error
                ? error.message
                : `The ${lensId} lens request failed`,
          };
        }
      }),
    );
    setLoadedSlots(results);
    setLoading(false);
  }

  return (
    <details
      className="lens-detail"
      data-testid="gold-lens-details"
      onToggle={(event) => {
        if (event.currentTarget.open) void loadLensDetails();
      }}
    >
      <summary>
        Lens detail series · {loading
          ? "loading /api/gold/lenses/*"
          : loadedSlots
            ? `${series.length} bound from /api/gold/lenses/*`
            : "expand to load /api/gold/lenses/*"}
      </summary>
      {failures.map((slot) => (
        <p className="note-refuse" key={slot.lensId}>
          <b>{slot.lensId}:</b> {slot.error}
        </p>
      ))}
      {loading ? (
        <p className="cap">Loading lens-detail series…</p>
      ) : loadedSlots && series.length === 0 ? (
        <p className="cap">No lens-detail series were returned.</p>
      ) : series.length > 0 ? (
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Lens · series</th>
                <th>Window</th>
                <th className="num">Obs</th>
                <th>All observations</th>
                <th className="num">Latest</th>
              </tr>
            </thead>
            <tbody>
              {series.map(({ lensId, name, points }) => {
                const first = points[0];
                const latest = points.at(-1);
                return (
                  <tr
                    key={`${lensId}-${name}`}
                    data-testid={`lens-series-${name}`}
                    data-point-count={points.length}
                  >
                    <td>
                      {lensId} · {name}
                    </td>
                    <td>
                      {first?.obs_date ?? "—"} → {latest?.obs_date ?? "—"}
                    </td>
                    <td className="num">{points.length}</td>
                    <td>
                      <svg
                        aria-label={`${name} series using ${points.length} observations`}
                        viewBox="0 0 120 24"
                        width="120"
                        height="24"
                      >
                        <polyline
                          fill="none"
                          stroke="var(--positive)"
                          strokeWidth="1.5"
                          points={sparkline(points)}
                        />
                      </svg>
                    </td>
                    <td className="num">{latest?.value ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </details>
  );
}
