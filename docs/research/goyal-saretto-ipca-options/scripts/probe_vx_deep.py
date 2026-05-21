"""Drill into /vX/reference/financials results[0].financials to count actual fields."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

env = dotenv_values(Path("/Users/chenxi/projects/unusual-whales/.env"))
API_KEY = env["MASSIVE_API_KEY"]
BASE_URL = env.get("MASSIVE_BASE_URL", "https://api.massive.com")

r = httpx.get(
    BASE_URL + "/vX/reference/financials",
    params={"ticker": "AAPL", "limit": 1, "timeframe": "quarterly"},
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=20.0,
)
payload = r.json()
row = payload["results"][0]
fin = row["financials"]

out = {
    "outer_keys": sorted(row.keys()),
    "outer_count": len(row),
    "financials_groups": sorted(fin.keys()),
    "groups_with_fields": {},
}
total_atomic = 0
for grp in fin:
    grp_payload = fin[grp]
    if isinstance(grp_payload, dict):
        out["groups_with_fields"][grp] = {
            "field_count": len(grp_payload),
            "fields": sorted(grp_payload.keys()),
            "sample_field_shape": (
                next(iter(grp_payload.values())) if grp_payload else None
            ),
        }
        total_atomic += len(grp_payload)
    else:
        out["groups_with_fields"][grp] = {"_type": type(grp_payload).__name__}

out["total_atomic_fields"] = total_atomic
out["fiscal_period"] = row.get("fiscal_period")
out["fiscal_year"] = row.get("fiscal_year")
out["start_date"] = row.get("start_date")
out["end_date"] = row.get("end_date")
out["filing_date"] = row.get("filing_date")

json.dump(out, sys.stdout, indent=2, default=str)
