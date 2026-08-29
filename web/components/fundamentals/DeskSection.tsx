/**
 * The desk's section chrome: a numbered question, its findings, its notes.
 *
 * The number is not decoration. The page is built in the order a fundamental
 * PM has to ask the questions and question three cannot be answered before
 * question one, so the sequence carries information and is rendered as a
 * sequence. `structure is information` — a numbered marker earns its place
 * only where the content really is ordered, and here it is.
 *
 * Inline styles over CSS variables, per `web/CLAUDE.md`: no styled-components,
 * no CSS-in-JS, and Tailwind is present but unused for component styling.
 */

import type { CSSProperties, ReactNode } from "react";

export const MONO = "var(--font-mono)";

/** Argon's canonical label: 10px mono, wide tracking, uppercase, muted. */
export const labelStyle: CSSProperties = {
  fontFamily: MONO,
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

export const panelStyle: CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
};

export function DeskSection({
  index,
  title,
  accent,
  children,
  testId,
}: {
  /** 1-based position in the question ladder. */
  index: number;
  title: string;
  /** CSS colour for this question's rule and numeral. */
  accent: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section
      data-testid={testId}
      style={{
        borderTop: `2px solid ${accent}`,
        paddingTop: 18,
        marginTop: 34,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <span
          style={{
            fontFamily: MONO,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: 1,
            color: accent,
          }}
        >
          {String(index).padStart(2, "0")}
        </span>
        <h2
          style={{
            fontFamily: MONO,
            fontSize: 17,
            fontWeight: 800,
            letterSpacing: 1,
            textTransform: "uppercase",
            color: "var(--text-primary)",
          }}
        >
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

/** Body copy. One measure, never full-bleed — long lines stop being read. */
export function Lede({ children }: { children: ReactNode }) {
  return (
    <p
      style={{
        marginTop: 10,
        maxWidth: "64ch",
        fontSize: 13,
        lineHeight: 1.62,
        color: "var(--text-secondary)",
      }}
    >
      {children}
    </p>
  );
}

/**
 * A measured conclusion, tinted by what it does to the thesis.
 *
 * `tone` is semantic, not decorative: `warn` is a reading that complicates the
 * argument above it and `bad` is one that constrains what the desk may say at
 * all. A finding that only confirms is `ok`.
 */
export function Finding({
  label,
  tone = "ok",
  children,
}: {
  label: string;
  tone?: "ok" | "warn" | "bad";
  children: ReactNode;
}) {
  const color =
    tone === "warn"
      ? "var(--warning)"
      : tone === "bad"
        ? "var(--negative)"
        : "var(--positive)";
  return (
    <div
      style={{
        marginTop: 16,
        padding: "12px 14px",
        borderLeft: `2px solid ${color}`,
        background: "var(--bg-panel-raised)",
        borderRadius: 4,
      }}
    >
      <div style={{ ...labelStyle, color, marginBottom: 6 }}>{label}</div>
      <p
        style={{
          fontSize: 12.5,
          lineHeight: 1.6,
          color: "var(--text-secondary)",
          maxWidth: "72ch",
        }}
      >
        {children}
      </p>
    </div>
  );
}

/** A number inside prose. Mono and primary, so a figure reads as a figure. */
export function Num({ children }: { children: ReactNode }) {
  return (
    <b
      style={{
        fontFamily: MONO,
        fontWeight: 600,
        color: "var(--text-primary)",
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {children}
    </b>
  );
}

/** Method, caveat, panel composition — quieter than a finding, still prose. */
export function Note({ children }: { children: ReactNode }) {
  return (
    <p
      style={{
        marginTop: 14,
        fontSize: 12,
        lineHeight: 1.6,
        color: "var(--text-muted)",
        maxWidth: "76ch",
      }}
    >
      {children}
    </p>
  );
}

/**
 * A panel that failed to load, said out loud.
 *
 * Every section settles independently, so one endpoint failing must leave the
 * others standing. What it must NOT do is render as an empty result: "no
 * upcoming print is held" is an affirmative coverage claim manufactured out of
 * a request failure.
 */
export function PanelError({ what, error }: { what: string; error: string }) {
  return (
    <div
      role="alert"
      style={{
        ...panelStyle,
        marginTop: 16,
        padding: "12px 14px",
        borderColor: "var(--negative)",
      }}
    >
      <div style={{ ...labelStyle, color: "var(--negative)" }}>
        {what} unavailable
      </div>
      <p style={{ marginTop: 6, fontSize: 12, color: "var(--text-secondary)" }}>
        The request failed, so this section is showing nothing rather than
        showing zero: <span style={{ fontFamily: MONO }}>{error}</span>
      </p>
    </div>
  );
}

/** The frame every chart sits in: a caption bar, the canvas, a live readout. */
export function VizFrame({
  caption,
  controls,
  children,
  readout,
}: {
  caption: ReactNode;
  controls?: ReactNode;
  children: ReactNode;
  readout?: ReactNode;
}) {
  return (
    <div style={{ ...panelStyle, marginTop: 16, overflow: "hidden" }}>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 12px",
          borderBottom: "1px solid var(--border-dim)",
        }}
      >
        <span style={{ ...labelStyle, letterSpacing: 1.2 }}>{caption}</span>
        {controls ? (
          <span style={{ display: "flex", gap: 6 }}>{controls}</span>
        ) : null}
      </div>
      {children}
      {readout ? (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 18,
            padding: "9px 12px",
            borderTop: "1px solid var(--border-dim)",
            fontFamily: MONO,
            fontSize: 11.5,
            color: "var(--text-secondary)",
            minHeight: 34,
            alignItems: "center",
          }}
        >
          {readout}
        </div>
      ) : null}
    </div>
  );
}

/** A viz control. Pressed state uses argon's accent pair, not a grey. */
export function VizButton({
  pressed,
  onClick,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      style={{
        fontFamily: MONO,
        fontSize: 10,
        letterSpacing: 1,
        textTransform: "uppercase",
        padding: "4px 9px",
        borderRadius: 4,
        cursor: "pointer",
        border: "1px solid var(--border-dim)",
        background: pressed ? "var(--accent-bg)" : "transparent",
        color: pressed ? "var(--accent-text)" : "var(--text-secondary)",
      }}
    >
      {children}
    </button>
  );
}
