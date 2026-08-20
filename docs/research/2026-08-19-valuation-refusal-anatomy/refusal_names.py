"""Read-only: which NAMES sit in each fixable refusal class."""
import psycopg
from uw_scan.config import Settings

s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
    cur.execute("SELECT max(as_of) FROM uw_scan.valuation_anchors")
    as_of = cur.fetchone()[0]
    cur.execute(
        "SELECT ticker, confidence_reasons_jsonb, method, company_type "
        "FROM uw_scan.valuation_anchors WHERE as_of=%s AND buy_below IS NULL",
        (as_of,),
    )
    rows = cur.fetchall()

fx, netdebt, hist = [], [], []
for t, reasons, method, ctype in rows:
    r0 = (reasons or [""])[0]
    if "reported in" in r0 and "series" in r0:
        cur_code = r0.split("reported in ")[1].split(" ")[0]
        fx.append((t, cur_code))
    elif "no price at this net debt" in r0:
        netdebt.append((t, method))
    elif "of the last 20 quarters are usable" in r0:
        hist.append((t, int(r0.split("only ")[1].split(" ")[0])))

print(f"FX-blocked ({len(fx)}): " + ", ".join(f"{t}[{c}]" for t, c in sorted(fx)))
print(f"\nnet-debt band collapse ({len(netdebt)}): " + ", ".join(f"{t}({m})" for t, m in sorted(netdebt)))
print(f"\nhistory-short ({len(hist)}): " + ", ".join(f"{t}={q}q" for t, q in sorted(hist, key=lambda x: -x[1])))
