"""Does UW honour ?date= ? Decide by response-hash differential, never by HTTP 200.

An endpoint is replay-safe ONLY if its body for date=A differs from its body for
date=B. Identical hashes mean the param is ignored and the endpoint always serves
the latest session -- writing that under a past market_date would be fabrication.
"""
import hashlib

import httpx
from uw_scan.config import Settings
from uw_scan.api.endpoints import REGISTRY as ENDPOINTS, EndpointSlug as S

s = Settings.from_env()
H = {"Authorization": f"Bearer {s.api_key.get_secret_value()}", "Accept": "application/json"}
TICKER, EXPIRY = "AAPL", "2026-09-18"
A, B = "2026-08-11", "2026-08-13"

CASES = [
    (S.TERM_STRUCTURE, {}), (S.INTERPOLATED_IV, {}),
    (S.GREEK_EXPOSURE, {"expiry": EXPIRY}),
    (S.SPOT_EXPOSURES, {"expirations[]": EXPIRY}),
    (S.GREEKS, {"expiry": EXPIRY}),
    (S.OI_PER_STRIKE, {}), (S.OI_CHANGE, {}), (S.MAX_PAIN, {}),
    (S.OPTION_CONTRACTS, {"limit": 500}),
    (S.DARKPOOL_TICKER, {}), (S.SHORT_DATA, {}),
    (S.OPTIONS_VOLUME_DAILY, {}), (S.SHORT_INTEREST_FLOAT, {}),
    (S.VOLATILITY_STATS, {}), (S.IV_RANK, {}),
    (S.GREEK_EXPOSURE_BY_EXPIRY, {}),
]

def get(slug, params):
    path = ENDPOINTS[slug].path_template.format(ticker=TICKER)
    r = httpx.get(f"{s.base_url}{path}", params=params, headers=H, timeout=45)
    return r.status_code, r.text

print(f"{'slug':<28}{'A(08-11)':>11}{'B(08-13)':>11}{'undated':>11}  verdict")
print("-" * 84)
results = {}
for slug, base in CASES:
    try:
        ca, ta = get(slug, {**base, "date": A})
        cb, tb = get(slug, {**base, "date": B})
        cu, tu = get(slug, dict(base))
    except Exception as e:
        print(f"{slug:<28} ERROR {e!r}")
        continue
    if not (ca == cb == cu == 200):
        print(f"{slug:<28} HTTP {ca}/{cb}/{cu}  -> cannot assess")
        continue
    ha, hb, hu = (hashlib.sha256(t.encode()).hexdigest()[:10] for t in (ta, tb, tu))
    if ha != hb:
        verdict = "HONORS"
    elif ha == hu:
        verdict = "IGNORES (== undated)"
    else:
        verdict = "IGNORES (A==B, != undated)"
    results[str(slug)] = verdict
    print(f"{slug:<28}{ha:>11}{hb:>11}{hu:>11}  {verdict}")

print("\n=== SUMMARY ===")
for k, v in sorted(results.items()):
    print(f"  {k:<30} {v}")
