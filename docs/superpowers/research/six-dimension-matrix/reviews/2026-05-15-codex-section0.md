# Codex review — `00-overview.md` §0 (Operational definitions)

**Reviewer**: codex (gpt-5.5, read-only sandbox)
**Run date**: 2026-05-15
**Run mode**: `codex exec --sandbox read-only`, session `019e2762-0b2e-79f2-b3ef-b4192ef0240b`
**Scope**: Independent critical review of the newly synthesized §0 of `00-overview.md` covering direction mapping (§0.1), consistency tolerance (§0.2), data-freshness contract (§0.3), and v1 definition of done (§0.4). Cross-checked against the per-dimension docs 01-vanna through 06-vrp, the limitations doc, and the backtest plan.

The review surfaced **5 substantive issues**, all of which have been applied to the doc set. A further block of **threshold-level suggestions** and **process notes** (DoD gaps, consistency-cluster rules) is preserved verbatim below for future calibration work.

This review is intentionally preserved as a separate artifact (not folded silently into `00-overview.md`) because it records the *why* behind several non-obvious choices in §0 — for example, why `event_back` maps to vol-down despite being labeled "idiosyncratic", and why the skew formula convention was changed in `03-skew.md` §1.

---

## Codex output (verbatim)

### Findings

1. **Skew sign convention is unsafe and likely inverted.** `03-skew.md:15-17` defines `RR25Δ = IV_put - IV_call`, then says a *negative* RR means puts are richer. That is internally inconsistent. §0 then says `skew_25d_zscore_180d > +1.0` is "compressed" and `< -1.0` is "extreme negative" (`00-overview.md:45`). This only works if the stored metric is effectively `call IV - put IV`, not the formula in `03-skew.md`. Fix the metric convention first; otherwise `vol_up`/`vol_down` can be reversed.

2. **Term Structure contradicts Scenario A / Strategy 1.** §0 treats `event_back` as neutral (`00-overview.md:46`), but Scenario A.1 uses event-type backwardation as part of the short-vol setup (`00-overview.md:174`), and Strategy 1 requires both `6-dim matrix all agree on vol-down` and `Term-structure state = event_back` (`09-backtest-plan.md:123-126`). With §0 as written, that trade can never be "6/6 consistent_vol_down." Either map `event_back` to vol-down for event trades, or change Strategy 1 to accept strong/weak consistency plus `event_back`.

3. **Vanna mapping omits conditional reading #2.** §0 maps reading #1 to vol-down and #3 to vol-up (`00-overview.md:43`), but `01-vanna.md:35-37` has reading #2: IV crush after upside call chase causes "Reverse sell-off." That is not "ambiguous"; it needs an explicit label, probably neutral/no-trade or vol-up depending whether the matrix is classifying vol exposure or spot-path risk.

4. **Flow is missing from the direction mapping.** The fifth dimension is "Implied Move + Flow" (`00-overview.md:118`; `05-implied-move-and-flow.md:5-7`), and §0.3 gives Flow a 5-minute freshness rule (`00-overview.md:79`), but §0.1 maps only Implied Move (`00-overview.md:47`). That leaves one half of the dimension outside the consistency check.

5. **Charm's vol-up rule is partly unmotivated.** High IV breaking the pin makes sense (`02-charm.md:104-106`), but `|pin_distance_sigma| > 2.0` alone (`00-overview.md:44`) may simply mean "no operative pin," not risk-off. I would map far-from-pin to neutral unless paired with high-vol / liquidity-back / skew acceleration.

### Thresholds

The defaults are acceptable as provisional gates, not research-derived truth. I would use:

- Skew: rolling per-ticker convention-safe z-score; acceleration as `5d_change < -2σ` only after fixing sign. Require flow concordance where possible (`03-skew.md:140`, `03-skew.md:152`).
- Implied Move: `>0.7` is okay for "suspect," but tradeable vol-down should require either `> median * 1.3` per `05-implied-move-and-flow.md:68` or a higher percentile such as `>0.8`, plus sample-size guard.
- VRP: `±0.5z` is a reasonable early default; sign flip should override because `06-vrp.md:219-220` explicitly defines it as regime-change alarm.
- Vanna/Charm: avoid hard z-style thresholds until classifier labels are empirically calibrated.

### Consistency Tolerance

The VRP/Term rationale is directionally sound: Term has explicit empirical support as a vol-crush predictor (`04-term-structure.md:61-67`), and VRP is the long-horizon carry state (`06-vrp.md:73-75`, `06-vrp.md:95-97`). But the weak 4/6 rule is incomplete because `07-limitations.md:37-45` says true agreement requires signals across confirmation clusters. If Vanna+Charm are both neutral, the matrix has no dealer-flow confirmation; that should be NO-TRADE for Scenario B and at least downgraded from "weak proceed" elsewhere.

### Freshness

Mostly reasonable. Tighten Vanna/Charm and Implied Move to 5-15 minutes during 0DTE/event windows; 30 minutes is okay for slower daily cockpit use. Skew 24h is fine. Term 24h normal / 30m stress is fine, but stress detection itself must use fresh curve data. Flow 5m is right. Strict VRP nightly is correct because it is lagged by definition (`06-vrp.md:43-47`, `07-limitations.md:85-88`).

### Definition Of Done

§0.4 is close but not fully shippable. It lacks sign-convention tests, denominator rules after stale dimensions are excluded (`00-overview.md:81`), persistence of `matrix_state_snapshots` required for replay (`08-implementation-gaps.md:249-250`), and a rule for what happens if Phase 1 falsification answers are "fail" rather than merely "ran" (`00-overview.md:90`; `09-backtest-plan.md:13-22`).

---

## Disposition (applied 2026-05-15)

| Finding | Applied in | Notes |
|---|---|---|
| Skew sign convention | `03-skew.md` §1; `00-overview.md` dim-3 row | Formula changed to `RR = IV_call − IV_put` (UW convention; baseline negative for SPX smirk). Doc set now declares the convention explicitly so future readers don't silently invert it. |
| Term `event_back` → vol-down | `00-overview.md` §0.1 Term row | Was `neutral`; now `vol_down`. Preserves Strategy 1 viability. `MatrixState.ts_state` still carries the contango-vs-event_back distinction for A.1-vs-A.2 routing. |
| Vanna reading #2 | `00-overview.md` §0.1 Vanna row | Added to vol-down column (vol crushes in both #1 and #2; spot-direction differs). |
| Flow in direction mapping | `00-overview.md` §0.1 — new Flow row + note | IM and Flow are read as two sub-dimensions; dim-5 contributes `neutral` unless they agree. Preserves 6-vote count. |
| Charm pin_distance > 2 alone | `00-overview.md` §0.1 Charm row | Moved to `neutral`. High-IV-breaks-pin requires pairing with liquidity_back/mixed term state OR skew z < −1. |
| Threshold suggestions | (not yet applied) | Kept as provisional defaults until Phase 1 backtest empirical distributions are available. Codex's IM > 0.8 / median × 1.3 alternative is the leading candidate for re-calibration. |
| §0.2 weak-rule cluster gap | `00-overview.md` §0.2 — new "Cluster-coverage overrides" subsection | Both Vanna+Charm neutral → NO-TRADE; VRP sign-flip → force vol-up label AND down-grade tier. |
| §0.3 freshness — 0DTE/event tightening | (deferred) | Acknowledged but not applied — the §0.3 contract serves the *display* layer; the §0.2 consistency check already excludes stale dimensions. Tightening to 5–15 min during 0DTE/event windows is a Phase 2 UI concern, not a Phase 1 backtest concern. |
| §0.4 ship criteria | `00-overview.md` §0.4 — four new items | (a) sign-convention golden test, (b) stale-dimension denominator rule, (c) `matrix_state_snapshots` persistence, (d) Phase 1 falsification fail-state dispositions. |

The skew formula bug (Finding 1) is the highest-impact correction: without it, a reader implementing from the formula in `03-skew.md` would have inverted the §0.1 z-score direction and produced an opposite-sign backtest, while a reader implementing from §0 directly would have gotten it right. Both readers would have produced "consistent" results that disagreed with each other under their own definitions.

## Cross-references

- Updated §0 in [`00-overview.md`](../00-overview.md)
- Updated skew sign convention in [`03-skew.md`](../03-skew.md) §1
- Limitation #1 (confirmation clusters — the basis for the cluster-coverage override) in [`07-limitations.md`](../07-limitations.md)
- Phase 1 falsification criteria referenced in DoD in [`09-backtest-plan.md`](../09-backtest-plan.md) §1
