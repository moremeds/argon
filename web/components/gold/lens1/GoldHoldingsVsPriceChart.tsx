"use client";

import { useMemo, useState, type CSSProperties } from "react";

import type { components } from "@/lib/types";

import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromPoints,
  type Point,
} from "@/lib/svgChart";

// niceTicks is designed for "nice" numeric ranges (10, 50, 100), not millisecond
// timestamps — handing it a 13-month range produces ~34 ticks. For time axes we
// sample N evenly-spaced positions across the domain instead.
function sampledTimeTicks(lo: number, hi: number, count: number): number[] {
  if (count < 2 || hi <= lo) return [lo];
  const out: number[] = [];
  for (let i = 0; i < count; i += 1) {
    out.push(lo + ((hi - lo) * i) / (count - 1));
  }
  return out;
}

function fmtDateTick(ms: number): string {
  const d = new Date(ms);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function fmtPriceTick(v: number): string {
  if (Math.abs(v) >= 1000) return v.toFixed(0);
  if (Math.abs(v) >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

function fmtTonnesTick(v: number): string {
  return v.toLocaleString(undefined, {
    maximumFractionDigits: 0,
  });
}

type Hp = components["schemas"]["GoldHistoryPoint"];
type Country = components["schemas"]["GoldCbCountryHistory"];

type Props = {
  goldHistory: Hp[];
  gldHistory: Hp[];
  cbCountryHistory?: Country[];
  width?: number;
  height?: number;
};

function toNumber(v: string | number): number {
  return typeof v === "string" ? Number(v) : v;
}

const CB_COLORS = [
  "#67e8f9",
  "#f472b6",
  "#a3e635",
  "#fb7185",
  "#76a9ff",
  "#d98cff",
  "#14b8a6",
  "#f59e0b",
];

const CHART_PADDING = { top: 12, right: 56, bottom: 24, left: 48 } as const;

function strategicCountries(countries: Country[]): string[] {
  return countries
    .filter((c) => c.bucket === "strategic_accumulator")
    .map((c) => c.country_iso3);
}

function fmtCountryTonnes(v: string | number | null | undefined): string {
  if (v == null) return "—";
  const n = typeof v === "string" ? Number(v) : v;
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function GoldHoldingsVsPriceChart({
  goldHistory,
  gldHistory,
  cbCountryHistory = [],
  width = 1040,
  height = 200,
}: Props) {
  const [selectedCountries, setSelectedCountries] = useState<string[]>([]);
  const selectedSet = useMemo(
    () => new Set(selectedCountries),
    [selectedCountries],
  );
  const visibleCountries = useMemo(
    () =>
      cbCountryHistory.filter((country) =>
        selectedSet.has(country.country_iso3),
      ),
    [cbCountryHistory, selectedSet],
  );
  const countryColorByIso3 = useMemo(
    () =>
      new Map(
        cbCountryHistory.map((country, index) => [
          country.country_iso3,
          CB_COLORS[index % CB_COLORS.length],
        ]),
      ),
    [cbCountryHistory],
  );

  const padding = CHART_PADDING;
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const cbHistoryPoints = useMemo(
    () =>
      visibleCountries.flatMap((country) =>
        (country.history ?? []).map((p) => ({
          t: new Date(p.obs_date).getTime(),
          value: toNumber(p.value),
        })),
      ),
    [visibleCountries],
  );
  const allDates = useMemo(
    () => [
      ...goldHistory.map((p) => new Date(p.obs_date).getTime()),
      ...gldHistory.map((p) => new Date(p.obs_date).getTime()),
      ...cbHistoryPoints.map((p) => p.t),
    ],
    [goldHistory, gldHistory, cbHistoryPoints],
  );
  const dateDomain = useMemo(() => finiteDomain(allDates), [allDates]);
  const goldDomain = useMemo(
    () => finiteDomain(goldHistory.map((p) => toNumber(p.value))),
    [goldHistory],
  );
  const tonnesDomain = useMemo(
    () =>
      finiteDomain([
        ...gldHistory.map((p) => toNumber(p.value)),
        ...cbHistoryPoints.map((p) => p.value),
      ]),
    [gldHistory, cbHistoryPoints],
  );
  const xRange = useMemo<[number, number]>(
    () => [padding.left, padding.left + innerW],
    [innerW, padding.left],
  );
  const yRange = useMemo<[number, number]>(
    () => [padding.top + innerH, padding.top],
    [innerH, padding.top],
  );

  const canDrawTop = dateDomain != null && dateDomain.count >= 2;

  const xScale = useMemo(
    () =>
      canDrawTop && dateDomain
        ? linearScale([dateDomain.lo, dateDomain.hi], xRange)
        : null,
    [canDrawTop, dateDomain, xRange],
  );
  const goldYScale = useMemo(
    () =>
      canDrawTop && goldDomain
        ? linearScale([goldDomain.lo, goldDomain.hi], yRange)
        : null,
    [canDrawTop, goldDomain, yRange],
  );
  const tonnesYScale = useMemo(
    () =>
      canDrawTop && tonnesDomain
        ? linearScale([tonnesDomain.lo, tonnesDomain.hi], yRange)
        : null,
    [canDrawTop, tonnesDomain, yRange],
  );

  const goldPoints: Point[] = useMemo(
    () =>
      goldYScale
        ? goldHistory.map((p) => [
            xScale?.(new Date(p.obs_date).getTime()) ?? 0,
            goldYScale(toNumber(p.value)),
          ])
        : [],
    [goldHistory, goldYScale, xScale],
  );

  const gldPoints: Point[] = useMemo(
    () =>
      tonnesYScale
        ? gldHistory.map((p) => [
            xScale?.(new Date(p.obs_date).getTime()) ?? 0,
            tonnesYScale(toNumber(p.value)),
          ])
        : [],
    [gldHistory, tonnesYScale, xScale],
  );
  const cbCountryPoints = useMemo(
    () =>
      visibleCountries.map((country) => ({
        country,
        points: tonnesYScale
          ? (country.history ?? []).map(
              (p): Point => [
                xScale?.(new Date(p.obs_date).getTime()) ?? 0,
                tonnesYScale(toNumber(p.value)),
              ],
            )
          : [],
      })),
    [visibleCountries, tonnesYScale, xScale],
  );

  const xTicks = useMemo(
    () =>
      canDrawTop && dateDomain
        ? sampledTimeTicks(dateDomain.lo, dateDomain.hi, 6)
        : [],
    [canDrawTop, dateDomain],
  );
  const goldYTicks = useMemo(
    () => (goldDomain ? niceTicks(goldDomain.lo, goldDomain.hi, 4) : []),
    [goldDomain],
  );
  const tonnesYTicks = useMemo(
    () => (tonnesDomain ? niceTicks(tonnesDomain.lo, tonnesDomain.hi, 4) : []),
    [tonnesDomain],
  );

  if (
    goldHistory.length === 0 &&
    gldHistory.length === 0 &&
    cbCountryHistory.length === 0
  ) {
    return (
      <div
        style={{
          color: "var(--text-muted, #6b7280)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          padding: 12,
        }}
      >
        No history yet
      </div>
    );
  }

  function toggleCountry(countryIso3: string) {
    setSelectedCountries((current) =>
      current.includes(countryIso3)
        ? current.filter((country) => country !== countryIso3)
        : [...current, countryIso3],
    );
  }

  const hasControls = cbCountryHistory.length > 0;

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 12,
        alignItems: "start",
      }}
    >
      {canDrawTop && xScale && (
        <div style={{ flex: "1 1 620px", minWidth: 0 }}>
          <svg
            width="100%"
            viewBox={`0 0 ${width} ${height}`}
            style={{ display: "block" }}
            role="img"
            aria-label={`Gold price against GLD ETF holdings over time${selectedCountries.length > 0 ? `, with central-bank reserves for ${selectedCountries.join(", ")}` : ""}`}
          >
            <g>
              {xTicks.map((t) => (
                <line
                  key={t}
                  x1={xScale(t)}
                  x2={xScale(t)}
                  y1={padding.top}
                  y2={padding.top + innerH}
                  stroke="var(--chart-grid, #1e2230)"
                  strokeWidth={0.5}
                />
              ))}
            </g>
            {goldPoints.length > 0 && (
              <path
                d={pathFromPoints(goldPoints)}
                fill="none"
                stroke="var(--positive, #05ad98)"
                strokeWidth={1.5}
              />
            )}
            {gldPoints.length > 0 && (
              <path
                d={pathFromPoints(gldPoints)}
                fill="none"
                stroke="var(--warning, #f5a623)"
                strokeWidth={1.5}
                strokeDasharray="4 2"
              />
            )}
            {cbCountryPoints.map(({ country, points }) => (
              <path
                key={country.country_iso3}
                d={pathFromPoints(points)}
                fill="none"
                stroke={
                  countryColorByIso3.get(country.country_iso3) ?? CB_COLORS[0]
                }
                strokeWidth={1.2}
              />
            ))}
            <g
              fontFamily="var(--font-mono)"
              fontSize={6.5}
              fill="var(--text-muted, #6b7280)"
            >
              {xTicks.map((t) => (
                <text
                  key={`xl-${t}`}
                  x={xScale(t)}
                  y={height - padding.bottom + 14}
                  textAnchor="middle"
                >
                  {fmtDateTick(t)}
                </text>
              ))}
              {goldYScale &&
                goldYTicks.map((v) => (
                  <g key={`yl-gold-${v}`}>
                    <line
                      x1={padding.left - 3}
                      x2={padding.left}
                      y1={goldYScale(v)}
                      y2={goldYScale(v)}
                      stroke="var(--text-muted, #6b7280)"
                      strokeWidth={0.5}
                    />
                    <text
                      x={padding.left - 6}
                      y={goldYScale(v) + 2.5}
                      textAnchor="end"
                      fill="var(--positive, #05ad98)"
                    >
                      {fmtPriceTick(v)}
                    </text>
                  </g>
                ))}
              {tonnesYScale &&
                tonnesYTicks.map((v) => (
                  <g key={`yl-gld-${v}`}>
                    <line
                      x1={padding.left + innerW}
                      x2={padding.left + innerW + 3}
                      y1={tonnesYScale(v)}
                      y2={tonnesYScale(v)}
                      stroke="var(--text-muted, #6b7280)"
                      strokeWidth={0.5}
                    />
                    <text
                      x={padding.left + innerW + 6}
                      y={tonnesYScale(v) + 2.5}
                      textAnchor="start"
                      fill="var(--warning, #f5a623)"
                    >
                      {fmtTonnesTick(v)}
                    </text>
                  </g>
                ))}
              <text x={padding.left} y={9} fill="var(--positive, #05ad98)">
                GLD price ($)
              </text>
              {tonnesYScale && (
                <text
                  x={padding.left + 70}
                  y={9}
                  fill="var(--warning, #f5a623)"
                >
                  GLD holdings + CB reserves (tonnes)
                </text>
              )}
            </g>
          </svg>
        </div>
      )}
      {hasControls && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            flex: "0 1 220px",
            gap: 6,
            maxHeight: 224,
            overflow: "auto",
            paddingRight: 4,
          }}
        >
          <span
            style={{
              color: "var(--text-secondary, #9aa3b2)",
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              letterSpacing: 1,
              textTransform: "uppercase",
            }}
          >
            Central bank reserves by country
          </span>
          <div style={{ display: "flex", gap: 6 }}>
            <button
              type="button"
              onClick={() =>
                setSelectedCountries(strategicCountries(cbCountryHistory))
              }
              style={toggleButtonStyle}
              title="Strategic accumulators: China, Russia, India, and Turkey when present."
            >
              Strategic
            </button>
            <button
              type="button"
              onClick={() =>
                setSelectedCountries(
                  cbCountryHistory.map((country) => country.country_iso3),
                )
              }
              style={toggleButtonStyle}
            >
              All
            </button>
            <button
              type="button"
              onClick={() => setSelectedCountries([])}
              style={toggleButtonStyle}
            >
              None
            </button>
          </div>
          {cbCountryHistory.map((country) => {
            const checked = selectedSet.has(country.country_iso3);
            return (
              <label
                key={country.country_iso3}
                style={{
                  display: "grid",
                  gridTemplateColumns: "18px 10px minmax(0, 1fr)",
                  alignItems: "center",
                  gap: 8,
                  color: checked
                    ? "var(--text-primary, #cfd2db)"
                    : "var(--text-muted, #6b7280)",
                  fontFamily: "var(--font-mono)",
                  fontSize: 9,
                }}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleCountry(country.country_iso3)}
                  aria-label={`Toggle ${country.country_name}`}
                />
                <span
                  aria-hidden="true"
                  style={{
                    width: 8,
                    height: 8,
                    background:
                      countryColorByIso3.get(country.country_iso3) ??
                      CB_COLORS[0],
                    display: "inline-block",
                  }}
                />
                <span
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {country.country_iso3} ·{" "}
                  {fmtCountryTonnes(country.latest_reserves_t)}
                </span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

const toggleButtonStyle: CSSProperties = {
  border: "1px solid var(--border-dim, #1b2030)",
  background: "var(--bg-panel, #0d1018)",
  color: "var(--text-secondary, #9aa3b2)",
  borderRadius: 4,
  padding: "4px 7px",
  fontFamily: "var(--font-mono)",
  fontSize: 9,
  textTransform: "uppercase",
};
