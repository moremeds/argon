# Macro Desk Pixel-Exact Remediation Design

**Status:** approved 2026-08-29
**Reference:** `docs/superpowers/specs/2026-08-27-macro-desk-board.html`
**Reference SHA-256:** `b98a32de3041a348aa8e86f5c4cc2cb9480b000752bdd6b26a2dead7b08f4029`

## Goal

Port the complete Claude board—not only its content grammar—to `/macro/*`: the
full-width app bar, intro, provenance and PM-question strips, sticky nine-tab
navigation, every tab panel, and every visible data binding. Argon's existing 220px
sidebar remains visible. The complete 1440px artifact canvas is translated to its right
and is never compressed to fit beside the sidebar. At the operator's direction, the
artifact's centered 1240px wrap is replaced by the Regime page's 32px gutters: the
component grammar remains the same, but the panels use the available canvas instead of
leaving roughly 100px empty on each side. Other routes keep the existing `AppShell`
unchanged.

The page remains a live analytical surface. Frozen values in the reference are used
only in deterministic visual tests; production rendering continues to read the real
API and refuses unavailable facts rather than restating reference numbers.

## Visual contract

The canonical comparison environment for the board canvas is Chromium, 1440x1000 CSS
pixels, DPR 1, dark theme. The board's DOM hierarchy, class grammar, panel order, selector counts,
computed styles, and element geometry after applying the explicit 32px-gutter override
are the contract. The comparison covers all
nine tabs, including operator-facing Design Notes, and does not exclude the shell.

The visual gate reports every occurrence of a selector rather than only the first.
It produces paired screenshots and a machine-readable DOM/style/geometry report.
There are no silently masked regions. Dynamic data is made deterministic at the API
boundary for the visual run; a separate binding suite proves the live page still reads
the API and handles missing publishers.

Responsive behavior follows the board's 980px and 640px breakpoints. Pixel equality is
gated at the canonical viewport; smaller viewports are gated for reachability, tab
overflow, and absence of unintended horizontal page overflow.

## Page architecture

- `AppShell` is already a client boundary. On `/macro` and `/macro/*` it renders the
  normal sidebar followed by a fixed-width 1440px macro canvas. App-shell tests cover
  the sidebar and translation; pixel comparisons crop the unchanged canvas itself.
- `app/macro/layout.tsx` owns the board shell in reference order: app bar, intro,
  provenance legend, Q1-Q7 strip, sticky tab bar, and the tab content slot.
- Navigation remains link-based because each tab is a route. Its classes and appearance
  match the board while its semantics remain honest (`nav`, links, `aria-current`).
- Tab 08 remains reachable and is restored to the visible strip because the requested
  port covers every artifact tab. Its content uses the same board panel primitives.
- The 635-line route module is split into tab-specific server components/loaders. The
  route file retains only validation, replay parsing, and dispatch.
- Board primitives are shared; old Rates-only shell chrome and duplicate CSS are removed
  when no remaining caller needs them.

## Data contract

- Replay calendar dates sent to `/api/macro/snapshot` use its `as_of` date parameter;
  `as_of_ts` remains reserved for genuinely timezone-aware intraday instants.
- `/api/gold/gauge` reads the already-persisted daily `gauge_corr_60d` history from
  `gold_posture_daily`; it does not recompute five years of weekly 252-day gauges on
  every request.
- The probability bar renders only from a publisher-supplied
  `probability_distribution`. If the market-implied path is unavailable, the visible
  refusal remains; no board number is invented.
- Frenzy Capital Fed Watch is the approved current market-implied source. It remains
  explicitly classified as `third_party_shadow` with `delay_status=unknown`; activation
  does not promote it to official evidence. Target environments opt in with
  `UW_SCAN_MACRO_MARKET_SHADOW_INGEST_ENABLED=true`, retain the exact fetched HTML, and
  persist the parsed distribution before the API exposes it. The frozen Claude-board
  probabilities are never copied into production.
- Frenzy exposes one continuously updated page and injects request-varying Cloudflare
  challenge bytes. `source_record_id` therefore identifies the stable Fed Watch page,
  while `content_hash` identifies each exact HTML representation. The policy semantic
  hash decides whether the normalized distribution is a new fact, so cosmetic bytes can
  become additional witnesses without creating a false policy vintage.
- Gold lens and input detail endpoints are called only for an interaction that visibly
  exposes their data. Endpoint consumption is not a goal by itself, and hidden N+1
  requests are forbidden.
- Every displayed derived sentence remains computed from the response at render time.

## Reference inventory

The reference has 58 titled panels: 11 Overview, 8 Fed, 9 Rates, 4 Inflation,
2 US Dollar, 8 Gold, 2 Energy, 3 Factor Export, and 11 Design Notes. Decorative nested
frames are not counted as panels. The implementation must not add standalone Summary,
Cross-Market, Source Freshness, or Energy preview panels that do not exist in the board;
use panel provenance/read rails for their still-useful facts.

## Simplification rules

- Target less than 500 lines per production module and split the two existing 500+
  Overview zones by cohesive panel groups.
- Keep durable rationale in this design and the implementation plan. Production comments
  explain local invariants, not commit history or superseded plans.
- Collapse repeated settle/replay wiring only where endpoint clocks remain explicit.
- Remove unused CSS selectors and duplicate page chrome after their callers are gone.
- Keep the CHANGELOG as a concise user-facing release entry; detailed implementation
  history belongs in plans, tests, and the handover.

## Verification gates

1. Regression tests fail before each correctness fix (snapshot replay and 60-day history).
2. API/OpenAPI/type generation remains contract-stable except for the additive gold
   history field.
3. Every reference tab has the exact panel inventory and order.
4. Full-shell selector, style, and geometry comparison passes at 1440x1000.
5. Production `next build` plus Playwright covers all nine tabs, redirects, live and
   replay paths, unavailable publishers, and responsive reachability.
6. Python tests, web unit tests, typecheck, lint, posture lint, and diff review pass.

## Probability-bar correction (approved 2026-08-29)

The Fed and Overview tabs share one publisher-bound per-meeting probability-bar renderer. It reads only `market_implied.path.points`; it never substitutes dealer or committee expectations. Buckets with a finite probability above zero receive a visual segment, while the full publisher distribution remains in the bar's accessible label so zero-probability outcomes are not silently erased from the evidence.

Segments divide the usable track by probability weight rather than combining percentage widths with padded flex items. This keeps the visible Hike/Hold ratio exact after labels, padding, and inter-segment spacing. Overview renders the same meeting rows whenever Frenzy supplies a path and keeps the existing honest refusal only for a missing path.
