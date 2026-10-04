"use client";

import { labelStyle, rowStyle, statusStyle, valStyle } from "./styles";

export function StatusRow({
  label,
  status,
}: {
  label: string;
  status: { label: string; color: string };
}) {
  return (
    <div style={rowStyle}>
      <span style={labelStyle}>{label}</span>
      <span style={statusStyle}>
        <span
          style={{
            width: 8,
            height: 8,
            background: status.color,
            display: "inline-block",
          }}
        />
        <span style={valStyle}>{status.label}</span>
      </span>
    </div>
  );
}
