---
state: low_contango
condition: "level == 'LOW' and vix_vix3m_ratio < 0.95"
posture: opportunistic
---

**LOW + contango.** Vol is cheap. Term structure is upward-sloping. Defined-risk *long-vol* setups become attractive: long puts, long VIX calls, long-vega vertical debit spreads. Mean-reversion in vol is dormant — don't expect vol compression as a tailwind. No short-vol exposure beyond defined-risk credit spreads with hard stops.

---
state: low_neutral
condition: "level == 'LOW' and 0.95 <= vix_vix3m_ratio < 1.0"
posture: neutral
---

**LOW + flat curve.** No directional vol edge. Premium selling (defined-risk only — iron condors, credit verticals, cash-secured puts) is consistent with the regime, but size small and respect the no-naked-shorts rule. Watch for vix_vix3m_ratio crossing 1.0 — that's the regime-flip signal.

---
state: low_missing_term_structure
condition: "level == 'LOW' and vix_vix3m_ratio is None"
posture: neutral
---

**LOW + term structure unavailable.** CRI is in the LOW band but VIX3M data is missing today, so we can't read the curve shape (contango vs backwardation). Treat as a flat/unknown regime: no directional vol edge to lean on. Defined-risk strategies (iron condors, credit verticals — never naked) are still consistent with the LOW level, but size small until the term-structure tile is back. Check the data sync job (`vol_index_lake_sync`) if this persists into a second session.

---
state: elevated_contango
condition: "level == 'ELEVATED' and vix_vix3m_ratio < 1.0"
posture: cautious
---

**ELEVATED + contango.** Stress is brewing but the curve hasn't flipped yet. Trim short-vol exposure; consider rolling defined-risk credit positions out in time to reduce gamma. Don't initiate new short-vol. Long-vol can still work as a hedge but is less cheap than in LOW.

---
state: elevated_backwardation
condition: "level == 'ELEVATED' and vix_vix3m_ratio >= 1.0"
posture: defensive
---

**ELEVATED + backwardation.** The vol curve has inverted — historically the leading edge of a stress regime. Defensive posture: no new short-vol of any kind. Existing short-vol positions should be reduced or fully hedged. Long-vol is no longer cheap but is the regime's natural friend.

---
state: elevated_missing_term_structure
condition: "level == 'ELEVATED' and vix_vix3m_ratio is None"
posture: cautious
---

**ELEVATED + term structure unavailable.** Stress signals are firing but the curve-shape input is missing today, so we can't tell whether the front-end has flipped into backwardation. Default to cautious without commitments either way: trim existing short-vol exposure as if the curve might be inverting, but don't add new long-vol bets that depend on a confirmed flip. Investigate the `vol_index_lake_sync` job before next session.

---
state: high
condition: "level == 'HIGH'"
posture: defensive
---

**HIGH.** Multiple stress dimensions are firing. Capital preservation first. Defined-risk short-vol is high-edge but high-noise — only if you can stomach the variance. Long-vol is expensive; better to use SPX/SPY put spreads than naked VIX calls.

---
state: critical
condition: "level == 'CRITICAL'"
posture: defensive
---

**CRITICAL.** Consistent with the worst historical drawdowns. The crash trigger may or may not have fired separately. Position sizing should be at minimum. Avoid initiating new positions of any flavor; the variance on every greek is at multi-year highs.
