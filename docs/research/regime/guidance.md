---
state: low_contango
condition: "level == 'LOW' and vix_vix3m_ratio < 0.95"
posture: opportunistic
---

• Vol is cheap (IV > realized); term structure upward-sloping
• Defined-risk long-vol attractive: long puts, long VIX calls, long-vega debit spreads
• Mean-reversion in vol is dormant — don't expect vol compression as a tailwind
• No short-vol beyond defined-risk credit spreads with hard stops

---
state: low_neutral
condition: "level == 'LOW' and 0.95 <= vix_vix3m_ratio < 1.0"
posture: neutral
---

• No directional vol edge — curve has flattened
• Premium selling consistent (defined-risk only — iron condors, credit verticals, cash-secured puts)
• Size small; respect the no-naked-shorts rule
• Watch for VIX/VIX3M crossing 1.0 — that's the regime-flip signal

---
state: low_missing_term_structure
condition: "level == 'LOW' and vix_vix3m_ratio is None"
posture: neutral
---

• LOW band confirmed, but VIX3M is missing — can't read curve shape (contango vs backwardation)
• Treat as flat/unknown regime: no directional vol edge to lean on
• Defined-risk strategies still consistent with the LOW level — size small until the term-structure tile is back
• Check `vol_index_lake_sync` if this persists into a second session

---
state: elevated_contango
condition: "level == 'ELEVATED' and vix_vix3m_ratio < 1.0"
posture: cautious
---

• Stress brewing but the curve hasn't flipped yet
• Trim short-vol exposure; roll defined-risk credits out in time to reduce gamma
• Don't initiate new short-vol
• Long-vol works as a hedge but is less cheap than in LOW

---
state: elevated_backwardation
condition: "level == 'ELEVATED' and vix_vix3m_ratio >= 1.0"
posture: defensive
---

• Vol curve has inverted — leading edge of a stress regime historically
• No new short-vol of any kind
• Reduce or fully hedge existing short-vol positions
• Long-vol is no longer cheap but is the regime's natural friend

---
state: elevated_missing_term_structure
condition: "level == 'ELEVATED' and vix_vix3m_ratio is None"
posture: cautious
---

• Stress signals firing but curve-shape input is missing
• Can't tell whether the front-end has flipped into backwardation
• Trim existing short-vol as if the curve might be inverting
• Don't add new long-vol that depends on a confirmed flip
• Investigate `vol_index_lake_sync` before next session

---
state: high
condition: "level == 'HIGH'"
posture: defensive
---

• Multiple stress dimensions firing — capital preservation first
• Defined-risk short-vol is high-edge but high-noise (only if you can stomach the variance)
• Long-vol is expensive — prefer SPX/SPY put spreads over naked VIX calls

---
state: critical
condition: "level == 'CRITICAL'"
posture: defensive
---

• Consistent with the worst historical drawdowns
• Crash trigger may or may not have fired separately
• Position sizing at minimum; avoid new positions of any flavor
• Variance on every Greek at multi-year highs
