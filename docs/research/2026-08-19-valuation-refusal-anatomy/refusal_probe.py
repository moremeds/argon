"""Read-only: why do the widened cohort's bands refuse? No writes, no provider calls."""
from collections import Counter
import re, psycopg
from uw_scan.config import Settings

s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
    cur.execute("SELECT max(as_of) FROM uw_scan.valuation_anchors")
    as_of = cur.fetchone()[0]
    cur.execute(
        """
        SELECT ticker, buy_below IS NOT NULL AS banded, confidence,
               confidence_reasons_jsonb
        FROM uw_scan.valuation_anchors WHERE as_of = %s
        """,
        (as_of,),
    )
    rows = cur.fetchall()

banded = [r for r in rows if r[1]]
refused = [r for r in rows if not r[1]]
print(f"as_of={as_of}  rows={len(rows)}  banded={len(banded)}  refused={len(refused)}"
      f"  refusal_rate={len(refused)/len(rows):.1%}")

def family(reason: str) -> str:
    r = reason.lower()
    if "different currencies" in r or "enterprise value is not positive" in r:
        return "non-positive EV (ADR/FX or real)"
    if "wider than the" in r and "limit" in r:
        return "own range too wide (regime change)"
    if "quarters of history" in r or "history" in r:
        return "insufficient history"
    if "stale" in r or "days old" in r:
        return "stale filing"
    if "numerator" in r or "not positive" in r:
        return "non-positive numerator"
    return reason[:70]

fam = Counter()
for t, _, conf, reasons in refused:
    rs = reasons or []
    if not rs:
        fam["(no reason recorded)"] += 1
    else:
        # a refusal's first reason is the binding one
        fam[family(rs[0])] += 1

print("\nrefusal families (binding reason):")
for k, v in fam.most_common():
    print(f"  {v:4d}  {k}")

# how wide is 'too wide'? extract the span multiples
spans = []
for t, _, conf, reasons in refused:
    for r in reasons or []:
        m = re.search(r"spans ([\d.]+)x", r)
        if m:
            spans.append((float(m.group(1)), t))
spans.sort(reverse=True)
if spans:
    print(f"\nrange-too-wide: n={len(spans)}  median={sorted(x for x,_ in spans)[len(spans)//2]:.1f}x"
          f"  worst: {', '.join(f'{t} {x:.1f}x' for x, t in spans[:6])}")
