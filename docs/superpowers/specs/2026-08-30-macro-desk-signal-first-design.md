# Macro Desk Signal-First Redesign

**Date:** 2026-08-30

**Status:** approved by operator delegation

**Scope:** `/macro` shell and every `/macro/[tab]` presentation surface

**Supersedes:** the 2026-08-27 captured board, its conformance audit, and the
2026-08-29 pixel-remediation plans and handover. Those intermediate implementation
artifacts were removed after this redesign shipped so they cannot compete with the
current product contract. This document plus the executable browser and component tests
is the maintained authority.

## Problem

The current desk is faithful to the approved Claude artifact, but that fidelity preserved
the artifact's review scaffolding as operator UI. At 1660px the Overview carries roughly
9,400 visible characters, Fed roughly 10,100, and Design Notes roughly 18,500. The shell
repeats the product name, proposal status, provenance vocabulary, seven acceptance
questions, tab title, panel question tags, endpoint paths, and footer invariants before or
around the actual answer.

The responsive contract is also false. The AppShell fixes the macro canvas at 1440px and
puts it inside a horizontal scroller. At a 1280px viewport the document itself reports no
overflow only because the 1440px canvas is clipped inside that scroller. Overview, Fed,
and USD then add their own horizontally scrolling tables.

Finally, implementation identifiers such as `WELL_ABOVE_TARGET`, `series_id`,
`confidence_reasons`, and `market_implied` are displayed as if they were user-facing
labels. They are useful audit keys, not information architecture.

## First-principles contract

A macro decision surface earns visible space only if it answers one of five questions:

1. What state are we in?
2. What changed?
3. What disagrees with that state or with pricing?
4. What happens next that can change the answer?
5. Can the answer be trusted?

Every visible string must therefore be one of: an answer, its unit/context, a decision
caveat, or navigation. Implementation metadata remains available to tests, assistive
technology, and an on-demand audit disclosure; it does not compete with the answer.

## Approaches considered

### A. Artifact-preserving compression

Keep all current sections and shorten sentences. This has the lowest implementation risk,
but retains the wrong hierarchy: seven Q cards, repeated provenance rails, and an internal
design-review tab still sit beside decision content.

### B. Regime-style progressive disclosure — selected

Use the successful `/regime` hierarchy: one page title and one purpose line, a compact
status row, a fully visible navigation row, then the data. Keep every live analytic and
its binding, but move acceptance metadata and technical provenance behind a shared audit
disclosure. Translate machine states and field names at the presentation boundary.

This is the best balance: it removes noise without changing analytical meaning or
weakening auditability.

### C. Single-screen command center

Delete most deep panels and make the Overview the only primary surface. This is the
cleanest visual result, but it removes useful evidence and changes the desk's information
contract too far for a presentation redesign.

## Information architecture

### Shell

- Title: **Macro**
- Purpose line: **Inflation → Policy → Dollar → Gold**
- Compact status: human-readable chain status, snapshot time, replay control
- Navigation: **Overview, Fed, Rates, Inflation, Dollar, Gold, Energy, Factors, Method**
- Remove ordinals from visible labels. Route slugs and replay behavior remain unchanged.
- Remove the proposal/review kicker, seven-question card rail, provenance legend, source
  chip, and verbose global footer.

### Tabs

- Each tab starts with a short title and at most one sentence saying what the operator can
  learn there.
- Panel names use a noun or question, not an essay.
- Interpretive copy is capped at one short paragraph per panel.
- Repeated refusals collapse into a single concise desk limit.
- Design Notes becomes **Method**: current data coverage, binding classes, known limits,
  and replay semantics only. Historical implementation review prose does not ship as UI.

### Provenance and variables

- `REAL`, `COMPUTED`, and `PLANNED` become **Live**, **Derived**, and **Planned**.
- Q1–Q7 stay in `data-questions` and accessible labels, but are not drawn.
- Endpoint paths, table names, engine versions, hashes, state IDs, and raw field names move
  into a native `<details>` disclosure labelled **Data details**.
- Raw states render through a shared human-label formatter while the raw value remains in
  `data-raw-value`/`title` for audit and tests.
- Series identifiers render as concise market labels where a known mapping exists; unknown
  identifiers are humanized rather than printed with underscores.

## Layout and overflow contract

- The sidebar remains visible.
- Macro main content is fluid: it consumes the width remaining after the sidebar and never
  has a fixed desktop minimum.
- The document and all descendants must satisfy `scrollWidth <= clientWidth` at 1280,
  1440, and 1660 CSS pixels.
- There is one vertical scroll owner: the AppShell main region. No nested horizontal
  scrolling is allowed.
- Tabs use a responsive grid/wrap; every destination is always visible.
- Tables use fixed layout and wrapping. Wide rows switch to stacked label/value blocks at
  narrow content widths rather than hiding columns behind a scroller.
- Long tokens use safe breaking. Numeric cells may remain tabular but cannot force the
  table wider than its panel.

### Atomic line groups

- One datum is one visual group: label, value, unit, direction, formula operator, and
  formula result must not split internally when their combined intrinsic width fits the
  card.
- Formula terms use one horizontal face (`label · value`) rather than stacking a value
  over its label. Operators travel with the term that follows, and the equals sign travels
  with the result.
- A row may wrap only after its available width is genuinely exhausted. Before wrapping,
  reduce decorative gap/padding and let the group consume unused row or column space.
- If a group still cannot fit, move the whole group to the next line. Never split its
  value from its unit and never introduce horizontal scrolling to preserve one line.
- Browser tests measure rendered line boxes at 1280, 1440, and 1660px. A group occupying
  multiple line boxes while its row has enough spare width is a regression.

## Dynamic-binding contract

Every displayed analytical value must be classified as:

- **Live:** copied from the current API response.
- **Derived:** computed only from values in that response, with a concise formula in Data
  details.
- **Planned:** prose only; it must render no analytical number.
- **Reference:** stable method or label text, never presented as current market data.

Static arrays may map fields to labels or order rows. They may not contain current levels,
probabilities, states, dates, freshness, or conclusions. The Energy inventory's dated
repository audit is Method material, not a live market reading. Tests will hold the
classification and reject frozen analytical values in planned panels.

## Verification gates

1. Unit tests prove the compact shell, human label formatter, hidden acceptance metadata,
   concise Method surface, and binding classifications.
2. Existing macro unit and replay tests stay green.
3. A browser sweep visits every tab at 1280, 1440, and 1660 and finds no horizontal
   overflow on the document, AppShell, desk, tab row, panels, or tables.
4. The browser sweep finds no visible snake_case identifiers on operator tabs.
5. Screenshots of Overview, Fed, Inflation, Gold, and Method are reviewed against Regime's
   hierarchy and information density.
