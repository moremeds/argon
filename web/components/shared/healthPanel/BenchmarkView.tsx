"use client";

import { type BenchmarkCurrent, benchmarkStatusColor, dash } from "./status";
import { labelStyle, panelButtonStyle, rowStyle, valStyle } from "./styles";
import { StatusRow } from "./StatusRow";

export function BenchmarkScoreRow({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <div style={rowStyle}>
      <span style={labelStyle}>{label}</span>
      <span style={valStyle}>{Math.round(value)}</span>
    </div>
  );
}

export function BenchmarkView({
  benchmark,
  loading,
  error,
  onBack,
}: {
  benchmark: BenchmarkCurrent | null;
  loading: boolean;
  error: boolean;
  onBack: () => void;
}) {
  if (loading && benchmark == null) {
    return (
      <>
        <div
          style={{
            ...rowStyle,
            alignItems: "center",
            paddingBottom: 8,
          }}
        >
          <span style={{ color: "var(--text-secondary)" }}>
            Pipeline Benchmark
          </span>
          <button type="button" onClick={onBack} style={panelButtonStyle}>
            Status
          </button>
        </div>
        <div style={rowStyle}>
          <span style={labelStyle}>Loading</span>
          <span style={valStyle}>...</span>
        </div>
      </>
    );
  }

  if (error || benchmark == null) {
    return (
      <>
        <div
          style={{
            ...rowStyle,
            alignItems: "center",
            paddingBottom: 8,
          }}
        >
          <span style={{ color: "var(--text-secondary)" }}>
            Pipeline Benchmark
          </span>
          <button type="button" onClick={onBack} style={panelButtonStyle}>
            Status
          </button>
        </div>
        <div style={rowStyle}>
          <span style={labelStyle}>Benchmark unavailable</span>
          <span style={valStyle}>—</span>
        </div>
      </>
    );
  }

  const statusColor = benchmarkStatusColor(benchmark.status);

  return (
    <>
      <div
        style={{
          ...rowStyle,
          alignItems: "center",
          paddingBottom: 8,
        }}
      >
        <span style={{ color: "var(--text-secondary)" }}>
          Pipeline Benchmark
        </span>
        <button type="button" onClick={onBack} style={panelButtonStyle}>
          Status
        </button>
      </div>
      <div style={rowStyle}>
        <span style={labelStyle}>Score</span>
        <span style={{ ...valStyle, color: statusColor }}>
          {Math.round(benchmark.score)}
        </span>
      </div>
      <StatusRow
        label="Status"
        status={{ label: benchmark.status, color: statusColor }}
      />
      <BenchmarkScoreRow
        label="Freshness"
        value={benchmark.subscores.freshness}
      />
      <BenchmarkScoreRow
        label="Coverage"
        value={benchmark.subscores.coverage}
      />
      <BenchmarkScoreRow
        label="Throughput"
        value={benchmark.subscores.throughput}
      />
      <BenchmarkScoreRow
        label="Provider"
        value={benchmark.subscores.provider}
      />
      <BenchmarkScoreRow label="Worker" value={benchmark.subscores.worker} />
      <BenchmarkScoreRow
        label="Persistence"
        value={benchmark.subscores.persistence}
      />
      <div
        style={{
          borderTop: "1px solid var(--border-dim)",
          margin: "8px 0",
        }}
      />
      <div style={rowStyle}>
        <span style={labelStyle}>Fresh scanned</span>
        <span style={valStyle}>
          {dash(benchmark.metrics.scanner_fresh_count)}
        </span>
      </div>
      <div style={rowStyle}>
        <span style={labelStyle}>Stale scanned</span>
        <span style={valStyle}>
          {dash(benchmark.metrics.scanner_stale_count)}
        </span>
      </div>
      <div style={rowStyle}>
        <span style={labelStyle}>Watchlist</span>
        <span style={valStyle}>{dash(benchmark.metrics.watchlist_size)}</span>
      </div>
      {benchmark.bottleneck && (
        <div style={{ ...rowStyle, alignItems: "flex-start" }}>
          <span style={labelStyle}>Bottleneck</span>
          <span
            style={{
              ...valStyle,
              color:
                benchmark.bottleneck.severity === "critical"
                  ? "var(--negative)"
                  : "var(--warning)",
              maxWidth: 180,
              textAlign: "right",
              whiteSpace: "normal",
            }}
          >
            {benchmark.bottleneck.message}
          </span>
        </div>
      )}
    </>
  );
}
