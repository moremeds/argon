"""Response-hash differential: does UW actually HONOUR ?date= on these endpoints?

HTTP 200 with rows proves nothing — an ignored date param returns the current
snapshot with a 200. If two different dates return byte-identical bodies, a
date-looped replay would write today's payload under a past key. That is
fabrication, not backfill.
"""

import hashlib

import httpx

from uw_scan.config import Settings

s = Settings.from_env()
base = s.base_url.rstrip("/")
h = {
    "Authorization": f"Bearer {s.api_key.get_secret_value()}",
    "Accept": "application/json",
}

PATHS = [
    ("oi-per-strike", "/api/stock/AAPL/oi-per-strike"),
    ("max-pain", "/api/stock/AAPL/max-pain"),
    ("spot-exposures", "/api/stock/AAPL/spot-exposures"),
    ("term-structure", "/api/stock/AAPL/volatility/term-structure"),
    ("interpolated-iv", "/api/stock/AAPL/interpolated-iv"),
]
DATES = ["2026-08-12", "2026-08-13", "2026-08-14"]

with httpx.Client(timeout=30) as c:
    for name, path in PATHS:
        digests = {}
        for d in DATES + [None]:
            params = {"date": d} if d else {}
            try:
                r = c.get(base + path, headers=h, params=params)
                digests[d or "none"] = (
                    r.status_code,
                    hashlib.sha256(r.content).hexdigest()[:12],
                )
            except Exception as exc:  # noqa: BLE001
                digests[d or "none"] = ("ERR", repr(exc)[:40])
        uniq = {v[1] for v in digests.values()}
        verdict = (
            "HONOURS date"
            if len(uniq) > 1
            else "IGNORES date -> replay would FABRICATE"
        )
        print(f"{name:18s} {verdict}")
        for k, v in digests.items():
            print(f"    {k:12s} {v[0]}  {v[1]}")
