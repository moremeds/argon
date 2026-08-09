"use client";

export default function MagnetRead({ read }: { read: string[] }) {
  return (
    // No heading here — the enclosing AnalyticalSeriesPanel titles this block.
    <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
      <ul style={{ margin: 0, paddingLeft: 16, lineHeight: 1.6 }}>
        {read.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <div
        style={{
          marginTop: 10,
          fontStyle: "italic",
          opacity: 0.5,
          fontSize: 11,
        }}
      >
        The 0.618 extension was tested against a matched null at five ZigZag
        thresholds and showed no edge. It is drawn as geometry, never as a
        target.
      </div>
    </div>
  );
}
