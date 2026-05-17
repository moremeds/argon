"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function ReplayDatePicker({ initialDate }: { initialDate: string }) {
  const router = useRouter();
  const [value, setValue] = useState(initialDate);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (value) router.push(`/gold/replay/${value}`);
      }}
      style={{
        display: "flex",
        gap: 8,
        alignItems: "center",
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        letterSpacing: 1.2,
        textTransform: "uppercase",
        color: "var(--text-muted, #6b7280)",
      }}
    >
      <label htmlFor="replay-date">REPLAY</label>
      <input
        id="replay-date"
        type="date"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        style={{
          background: "var(--bg-elevated, #11141b)",
          color: "var(--text-primary, #cfd2db)",
          border: "1px solid var(--border-dim, #1b2030)",
          padding: "4px 6px",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
        }}
      />
      <button
        type="submit"
        style={{
          background: "transparent",
          color: "var(--text-secondary, #9aa3b2)",
          border: "1px solid var(--border-dim, #1b2030)",
          padding: "4px 8px",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          cursor: "pointer",
        }}
      >
        Go
      </button>
    </form>
  );
}
