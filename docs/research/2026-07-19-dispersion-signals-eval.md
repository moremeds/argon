# Two dispersion/correlation signals — directional evaluation

**Date:** 2026-07-19
**Status:** Claim 2 NOT SUPPORTED (mostly false as framed); Claim 1 directionally consistent but UNPROVEN (underpowered). **Do not build as a trading signal.** Confidence MED.
**Reproduce:**
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
UW_SCAN_DB_USER=argon_app UW_SCAN_API_KEY=x APEX_API_URL=http://100.66.147.98:8322 \
uv run python scripts/research/dispersion_signals_eval.py
```
Full trace: `2026-07-19-dispersion-signals-eval.json` (this dir).

## Claims

- **Claim 1:** "When VIX/COR1M is very high, deleverage all high-beta/high-vol stocks (COHR, LITE, GLW, SNDK) — funds deleverage high-beta regardless of fundamentals."
- **Claim 2:** "VIXEQ/VIX high (index vol low, single-stock vol high = low correlation) is a **warning** signal."

## Key identities / prior art

- **COR1M ≈ (VIX/VIXEQ)²  ⟹  VIXEQ/VIX ≈ 1/√COR1M.** So "VIXEQ/VIX high" ⟺ "COR1M **low**". Claim 2 is tested via COR1M (real, 2006→2026) because VIXEQ (Cboe, live only since Nov-2024) is **not sourceable** on our stack (not on UW; Yahoo banned) and has <2yr history. [KNOWN, HIGH]
- Prior art `docs/research/2026-07-07-implied-corr-gate.md` (#226): COR1M carries **no independent SPX short-vol edge**, ~0.80 collinear with VIX-z. That tested vol-**harvesting** P&L; these claims are equity-**directional**, hence this separate test. [KNOWN]

## Method

- Data: `vol_index_daily` VIX/COR1M/SPX (n=5,133 aligned days, 2007-01-04→2026-05-29) + apex adjusted daily SPHB/SPLV (high-beta − low-vol factor spread; 2021-06-11→2026-05, the binding constraint for Claim 1). Trailing-252 z-scores (no look-ahead). Non-overlapping (step=horizon) samples for honest significance. [COMPUTED]

## Confounds (structural)

| pair | Pearson |
|---|---|
| **ratio_z (VIX/COR1M) vs VIX-z** | **0.063** — nearly orthogonal to VIX |
| COR1M-z vs VIX-z | 0.801 — level tracks VIX (confirms #226) |
| ratio_z vs COR1M-z | −0.419 — high ratio ⟺ low correlation |

The VIX/COR1M **ratio** is a genuine dispersion axis, *not* a VIX proxy. [COMPUTED]

## Claim 2 — low correlation = "warning"? NOT SUPPORTED

Non-overlapping quintiles by COR1M-z (Q1 = lowest correlation = the "warning" side), h=21d:

| target | Q1 (low corr) | Q5 (high corr) | reading |
|---|---|---|---|
| fwd SPX return | +0.01% (t 0.03) | +1.73% (t 1.87) | low-corr → **flat**, not negative |
| fwd SPX max drawdown | **−2.07%** (t −6.0) | **−4.21%** (t −4.9) | **deepest drawdowns follow HIGH corr, not low** |
| fwd VIX change | +2.40 (t 4.0) | −3.59 (t −3.8) | low-corr → VIX rises… |

The one supportive morsel — VIX rises after low correlation — is mostly **low-VIX mean reversion** (COR-z is 0.80 collinear with VIX-z). The VIX-tercile control leaves only a weak, sign-flipping residual (mid-VIX: low-corr fwd SPX −0.38% vs high-corr +2.02%; but tercile 2 flips). The headline is decisive: **the biggest forward drawdowns come from HIGH correlation, not low** — the opposite of the claim. High correlation as the danger marker is already encoded in CRI's `crash_trigger` (COR1M > 60). [COMPUTED] [INFERRED, HIGH]

## Claim 1 — high VIX/COR1M ⟹ high-beta underperforms? DIRECTIONALLY CONSISTENT, UNPROVEN

fwd (SPHB−SPLV) spread on ratio_z, non-overlapping:

| model | h10 | h21 | h42 |
|---|---|---|---|
| OLS coef on ratio_z | −0.0025 (t −0.8) | −0.0090 (t −1.2) | −0.013 (t −0.7) |
| n | 124 | 59 | 29 |

Sign is **consistently negative** across all horizons (high VIX/COR1M → high-beta underperforms low-vol), matching the claim's intuition — but **never statistically significant** and quintiles are non-monotone. n is tiny (SPHB/SPLV only exist from 2021-06 in the lake; ~1.5 regimes). Cannot confirm or reject. [COMPUTED]

## Verdict

- **Claim 2 (low-corr = warning): reject as framed.** Low correlation is the *calmest* forward regime (shallowest drawdowns, flat returns); HIGH correlation is the danger — already covered by CRI. [INFERRED, HIGH]
- **Claim 1 (deleverage high-beta on high VIX/COR1M): a sound risk-management *posture*, not a validated timing signal.** The dispersion axis is real and orthogonal to VIX, and the sign is right, but underpowered on ~5yr. The general reflex — size down high-beta in high-vol/high-dispersion regimes — is prudent regardless; the precise `/COR1M` trigger adds nothing provable over just watching VIX + COR1M levels we already show. [INFERRED, MED]
- **Build recommendation:** no new market-tide signal/subtab. Both variables are already captured (COR1M feeds CRI; `/api/regime/vol-backdrop` returns VIX+COR1M). If dispersion visibility is wanted, add a *descriptive* COR1M-percentile / VIX-COR1M-ratio readout to the existing CRI or vol-backdrop view — explicitly labeled as regime context, **not** a low-correlation warning.

## Caveats

- SPHB/SPLV history (~5yr) is the hard limit on Claim 1 power; a 15yr test would need an external SPHB/SPLV feed (UW MCP has it; not wired into a reproducible script here). [KNOWN]
- COR1M pre-2021 lake history is partly reconstructed (per #226); the 0.91 proxy agreement there is the validity check. [KNOWN]
- Local DB ends 2026-05-29 (~7wk stale); does not affect a 20yr conditional test. [KNOWN]

[RULES I BROKE]: Earlier in the session I asserted "VIX/COR1M is dominated by VIX" — the confound table (ratio_z ⊥ VIX-z, 0.063) falsified it; corrected here.
