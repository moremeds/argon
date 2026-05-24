---
name: Unusual Whales Opportunity Scanner
description: Dense options and macro research cockpit for watchlist triage.
colors:
  base-void: "#0a0f14"
  panel-ink: "#0f1519"
  raised-ink: "#151c22"
  border-slate: "#1e293b"
  text-primary: "#e2e8f0"
  text-secondary: "#94a3b8"
  text-muted: "#475569"
  signal-teal: "#05ad98"
  signal-teal-strong: "#0fcfb5"
  signal-teal-deep: "#048a7a"
  risk-red: "#e85d6c"
  warning-amber: "#f5a623"
  volatility-violet: "#8b5cf6"
  dislocation-magenta: "#d946a8"
typography:
  display:
    fontFamily: "IBM Plex Mono, monospace"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "1px"
  headline:
    fontFamily: "Inter, -apple-system, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0"
  title:
    fontFamily: "IBM Plex Mono, monospace"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "0.08em"
  body:
    fontFamily: "Inter, -apple-system, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.5
    letterSpacing: "0"
  label:
    fontFamily: "IBM Plex Mono, monospace"
    fontSize: "11px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "1px"
rounded:
  xs: "2px"
  sm: "3px"
  md: "4px"
  lg: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "4px 10px"
  button-primary:
    backgroundColor: "{colors.signal-teal}"
    textColor: "{colors.base-void}"
    rounded: "{rounded.sm}"
    padding: "4px 10px"
  card:
    backgroundColor: "{colors.panel-ink}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "12px"
  chip-active:
    backgroundColor: "{colors.signal-teal}"
    textColor: "{colors.base-void}"
    rounded: "{rounded.sm}"
    padding: "4px 10px"
---

# Design System: Unusual Whales Opportunity Scanner

## 1. Overview

**Creative North Star: "The Desk Tape"**

This product should feel like a live trading desk condensed into software: quiet, dark, compact, source-aware, and precise. It is not trying to impress with decoration. It earns trust by making dense data scannable and by keeping the same component vocabulary across watchlist cards, scanner candidates, stock detail panels, macro views, and admin controls.

The visual system is flat by default. Depth comes from tonal layers, 1px borders, and compact spacing. Semantic color is reserved for state and meaning: positive flow, negative/risk, warning, volatility, dislocation, and muted neutral evidence.

**Key Characteristics:**

- Dark operational surfaces with restrained teal as the primary action and current-state accent.
- Mono-heavy labels and data blocks, with Inter available for longer explanatory copy.
- Compact cards and tables using 4px corners, 1px borders, and narrow gaps.
- Semantic colors tied to market meaning, not decoration.

## 2. Colors

The palette is a dark, tinted neutral system with one primary teal accent and a small set of market-state colors.

### Primary

- **Signal Teal** (#05ad98): Primary actions, active chips, current/live indicators, constructive or positive state.
- **Signal Teal Strong** (#0fcfb5): High-emphasis teal for charts or stronger live-state emphasis.
- **Signal Teal Deep** (#048a7a): Light-theme positive state and lower-luminance teal variants.

### Secondary

- **Risk Red** (#e85d6c): Bearish, negative, stale, fault, and risk states.
- **Warning Amber** (#f5a623): Caution, queue/running, mixed reads, and attention states.
- **Volatility Violet** (#8b5cf6): Volatility-specific accents and comparison series.
- **Dislocation Magenta** (#d946a8): Dislocation or extreme condition accents.

### Neutral

- **Base Void** (#0a0f14): Main dark background.
- **Panel Ink** (#0f1519): Primary panel and card surface.
- **Raised Ink** (#151c22): Hover, raised panel, and secondary surface.
- **Border Slate** (#1e293b): Hairline borders, dividers, chart axes, and structural separation.
- **Primary Text** (#e2e8f0): Main values and headings.
- **Secondary Text** (#94a3b8): Supporting data and descriptions.
- **Muted Text** (#475569): Timestamps, small labels, inactive nav, and disabled details.

### Named Rules

**The Meaning-First Color Rule.** Do not introduce color unless it communicates state, category, selection, freshness, or chart series identity.

## 3. Typography

**Display Font:** IBM Plex Mono, with monospace fallback  
**Body Font:** Inter, with system sans fallback  
**Label/Mono Font:** IBM Plex Mono

**Character:** The product reads like a terminal-native research cockpit, but with enough Inter in explanatory copy to keep dense pages legible.

### Hierarchy

- **Display** (700, 24px, 1.1): Route headers such as DASHBOARD, SCANNER, and dense page titles.
- **Headline** (700, 22px, 1.2): Section headings and larger analytical panel titles.
- **Title** (700, 13px, 1.25): Card headers, table section labels, and compact panel titles.
- **Body** (500, 13px, 1.5): Explanatory readouts, tooltips, and synthesis text. Keep prose around 65-75ch when possible.
- **Label** (700, 11px, uppercase, 1px tracking): Chips, table headers, metadata, status pills, and metric labels.

### Named Rules

**The Data Label Rule.** Labels, timestamps, IDs, and metric captions use IBM Plex Mono. Longer human-readable reads may use Inter.

## 4. Elevation

The system is flat by default and uses tonal layering instead of shadows. Panels separate through `--bg-base`, `--bg-panel`, `--bg-panel-raised`, and 1px `--border-dim` strokes. Shadows are reserved for dialogs and popovers where overlay separation is necessary.

### Shadow Vocabulary

- **Dialog Shadow** (`0 24px 64px rgba(0, 0, 0, 0.44)`): Blocking dialogs and confirmation surfaces.
- **Popover Shadow** (`0 12px 30px rgba(0, 0, 0, 0.35)`): Tooltips and small floating explanatory panels.

### Named Rules

**The Flat-At-Rest Rule.** Cards, tables, route sections, and charts do not use shadows at rest.

## 5. Components

### Buttons

- **Shape:** Tight rectangular controls with 3px radius.
- **Primary:** Signal Teal background with Base Void text, compact 4px by 10px padding.
- **Hover / Focus:** Use existing focus-visible outline and border shifts. Keep motion short and state-driven.
- **Secondary / Ghost:** Transparent background, Border Slate stroke, Secondary Text label.

### Chips

- **Style:** 3px radius, mono 11px label, compact horizontal padding.
- **State:** Active chips use Signal Teal fill with Base Void text. Inactive chips are transparent with Border Slate and Secondary Text.

### Cards / Containers

- **Corner Style:** 4px for most product surfaces, 8px only for large route sections or charts that need extra breathing room.
- **Background:** Panel Ink for cards, Raised Ink for hover or secondary panels, Base Void for nested chart/table wells.
- **Shadow Strategy:** No shadows at rest.
- **Border:** Always 1px Border Slate or the themed `--border-dim`.
- **Internal Padding:** 12px for dense cards, 16-24px for larger analytical sections.

### Inputs / Fields

- **Style:** Base Void background, Border Slate stroke, 4px radius, Primary Text value.
- **Focus:** Use a 2px focus-visible outline or Border Focus shift.
- **Error / Disabled:** Use Risk Red for errors, Muted Text for disabled, and avoid saturated fills on inactive controls.

### Navigation

- **Style:** Sidebar and route tabs are mono, compact, and restrained. Active state uses a clear border or filled chip, not decorative color blocks.
- **Mobile Treatment:** Collapse horizontal navigation into scrollable rows. Preserve stable hit targets and avoid layout shifts.

### Data Tables

- **Style:** Mono numeric data, 1px dividers, right-aligned numeric columns, left-aligned labels.
- **Density:** Dense is correct. Add whitespace only where it improves scan order.

## 6. Do's and Don'ts

### Do:

- **Do** keep route surfaces on `--bg-base`, `--bg-panel`, and `--bg-panel-raised`.
- **Do** use 4px card corners and 1px borders for most product panels.
- **Do** reserve teal, red, amber, violet, and magenta for semantic state or chart identity.
- **Do** use mono labels for compact data and timestamps.
- **Do** keep layouts dense, predictable, and source-aware.

### Don't:

- **Don't** add marketing-page hero composition to product routes.
- **Don't** use decorative gradients, glassmorphism, or large ambient blur.
- **Don't** introduce navy-and-gold fintech styling.
- **Don't** use side-stripe borders as card accents.
- **Don't** use gradient text.
- **Don't** change the palette per route unless the data role requires it.

