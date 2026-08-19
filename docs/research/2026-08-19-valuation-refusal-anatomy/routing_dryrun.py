"""Read-only: what the new routing rules would produce on live data. Writes nothing.

Mirrors `seed_company_types`'s precedence exactly (name override -> chain prefix
-> vendor exact -> default) rather than re-implementing it loosely, so a
divergence here is a real divergence and not an artifact of the probe.
"""
import psycopg
from uw_scan.config import Settings
from uw_scan.fundamentals.valuation import FINANCIALS, UNCLASSIFIED
from uw_scan.worker.jobs.fundamental_anchors import (
    SECTOR_TO_TYPE,
    TICKER_TO_TYPE,
    VENDOR_SECTOR_TO_TYPE,
)

s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
    cur.execute("""
        SELECT DISTINCT f.ticker, w.sector, t.company_type
          FROM uw_scan.fundamental_universe f
          LEFT JOIN uw_scan.watchlist w ON w.ticker = f.ticker
          LEFT JOIN uw_scan.fundamental_company_type t ON t.ticker = f.ticker
         WHERE f.removed_at IS NULL""")
    rows = cur.fetchall()

    cur.execute("SELECT max(as_of) FROM uw_scan.valuation_anchors")
    as_of = cur.fetchone()[0]
    cur.execute("""SELECT ticker, buy_below, spot FROM uw_scan.valuation_anchors
                    WHERE as_of=%s""", (as_of,))
    band = {t: (bb, sp) for t, bb, sp in cur.fetchall()}

flips = []
for ticker, sector, current in rows:
    matches = [k for k in SECTOR_TO_TYPE if sector and sector.startswith(k)]
    if ticker in TICKER_TO_TYPE:
        new = TICKER_TO_TYPE[ticker]
    elif matches:
        new = SECTOR_TO_TYPE[max(matches, key=len)]
    else:
        new = UNCLASSIFIED  # no company_sector rows yet: vendor pass is empty
    if new != current:
        flips.append((ticker, current, new, sector))

fin = [f for f in flips if f[2] == FINANCIALS]
print(f"universe={len(rows)}  would change={len(flips)}  -> financials={len(fin)}\n")
print("names flipping to `financials` from the CHAIN taxonomy alone")
print("(AXP/COF/FLG need the monthly vendor fill and are NOT here yet):\n")
for t, cur_t, new_t, sec in sorted(fin):
    bb, sp = band.get(t, (None, None))
    had = "—" if bb is None else f"{float(bb):.2f}"
    in_zone = bb is not None and sp is not None and float(sp) <= float(bb)
    print(f"  {t:<6} {cur_t:<14}-> {new_t:<11} chain={sec:<9} "
          f"had buy_below={had:<9}{'  <-- WAS IN ITS BUY ZONE' if in_zone else ''}")

other = [f for f in flips if f[2] != FINANCIALS]
print(f"\nchanges that are NOT the bank fix (each needs its own argument): {len(other)}")
for t, cur_t, new_t, sec in sorted(other):
    bb, sp = band.get(t, (None, None))
    had = "—" if bb is None else f"{float(bb):.2f}"
    in_zone = bb is not None and sp is not None and float(sp) <= float(bb)
    print(f"  {t:<6} {cur_t:<14}-> {new_t:<11} chain={sec!s:<9} "
          f"had buy_below={had:<9}{'  <-- IN ITS BUY ZONE' if in_zone else ''}")
