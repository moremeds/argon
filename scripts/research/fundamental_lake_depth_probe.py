"""Measure whether lake price depth — not universe membership — gates the valuation band.

`docs/superpowers/plans/2026-08-13-fundamental-lane-next.md` D5 concluded that widening
the fundamental universe buys only ~29 extra valuation bands, because the 144 candidate
names lack unadjusted daily closes. That measurement was taken on the MacBook mirror,
which is a partial copy. This probe re-measures against an arbitrary lake root so the
production mirror can answer the same question.

D5 counted `1d.parquet` existence. That is coverage, not computability — the same
conflation that produced the retracted `0/257` concentration verdict. A band needs
`MIN_HISTORY` (12) of the trailing `WINDOW_QUARTERS` (20) quarters to carry BOTH a
statement and a priced knowledge date, so this probe reports depth at both thresholds
rather than file presence alone.

Reproduce (MacBook mirror, cohorts read from the local DB and embedded in the output):

    D=docs/research/2026-08-18-fundamental-lake-depth
    UW_SCAN_API_KEY=$(grep -m1 '^UW_SCAN_API_KEY=' .env | cut -d= -f2-) \
    UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_PASSWORD= \
    UW_SCAN_DB_NAME=option_wizard_local \
    uv run --extra postgres python scripts/research/fundamental_lake_depth_probe.py \
        --lake-root ~/market-warehouse/data-lake/bronze/asset_class=equity \
        --label macbook --as-of 2026-08-18 --out $D

Reproduce (mini mirror). Prod holds statements for the 257 universe names only, so the
144-name cohort is replayed from the MacBook run rather than re-read from the prod DB.
The lake lives on an external volume mounted read-only into the containers as `/lake`;
it is NOT under the mini user's home, which holds an empty skeleton of the same tree:

    ssh macmini 'cat > /tmp/probe.py' < scripts/research/fundamental_lake_depth_probe.py
    ssh macmini 'cat > /tmp/cohorts.json' < $D/depth_macbook.json
    ssh macmini '/opt/homebrew/bin/docker cp /tmp/probe.py argon-api-1:/tmp/probe.py \
      && /opt/homebrew/bin/docker cp /tmp/cohorts.json argon-api-1:/tmp/cohorts.json \
      && /opt/homebrew/bin/docker exec argon-api-1 python /tmp/probe.py \
           --cohorts-from /tmp/cohorts.json --lake-root /lake/bronze/asset_class=equity \
           --label mini --as-of 2026-08-18 --out /tmp/out'
    ssh macmini '/opt/homebrew/bin/docker exec argon-api-1 cat /tmp/out/depth_mini.json' \
        > $D/depth_mini.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

#: Mirrors `uw_scan.fundamentals.valuation`. Duplicated as plain ints so the probe runs
#: inside the deployed container against whatever code that image carries, instead of
#: silently measuring against a different window than production uses.
WINDOW_QUARTERS = 20
MIN_HISTORY = 12

#: A quarter is ~91.3 days. The band prices each historical quarter at its own knowledge
#: date, so covering N quarters needs closes reaching back N quarters — not just a file.
DAYS_PER_QUARTER = 91.3125


def _cutoff(today: date, quarters: int) -> date:
    return today - timedelta(days=round(DAYS_PER_QUARTER * quarters))


def load_cohorts_from_db() -> dict[str, list[str]]:
    """Universe members, and the statement-bearing names with no membership."""
    import psycopg

    from uw_scan.config import Settings

    with psycopg.connect(Settings.from_env().db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT ticker FROM uw_scan.fundamental_universe ORDER BY 1"
        )
        universe = [r[0] for r in cur.fetchall()]
        cur.execute(
            """
            SELECT DISTINCT s.ticker
              FROM uw_scan.fundamental_statement_obs s
              LEFT JOIN uw_scan.fundamental_universe u ON u.ticker = s.ticker
             WHERE u.ticker IS NULL
             ORDER BY 1
            """
        )
        excluded = [r[0] for r in cur.fetchall()]
        # Statement depth is the band's other necessary condition. Measured here so a
        # price-only result is never read as "these names would produce bands".
        cur.execute(
            """
            SELECT ticker, count(DISTINCT period_end)
              FROM uw_scan.fundamental_statement_obs
             WHERE period_type = 'quarterly'
             GROUP BY 1
            """
        )
        stmt_quarters = {t: n for t, n in cur.fetchall()}
    return {"universe": universe, "excluded": excluded, "stmt_quarters": stmt_quarters}


def measure(root: Path, tickers: list[str], today: date) -> dict:
    """Per-ticker file presence and the earliest close, at both band thresholds."""
    import pyarrow.parquet as pq

    c12, c20 = _cutoff(today, MIN_HISTORY), _cutoff(today, WINDOW_QUARTERS)
    per: dict[str, dict] = {}
    for t in tickers:
        path = root / f"symbol={t}" / "1d.parquet"
        if not path.exists():
            per[t] = {"file": False}
            continue
        col = pq.read_table(str(path), columns=["trade_date"]).column("trade_date")
        days = [d for d in col.to_pylist() if d is not None]
        if not days:
            per[t] = {"file": True, "rows": 0}
            continue
        lo, hi = min(days), max(days)
        per[t] = {
            "file": True,
            "rows": len(days),
            "first": lo.isoformat(),
            "last": hi.isoformat(),
            "depth_12q": lo <= c12,
            "depth_20q": lo <= c20,
        }
    return {
        "cohort_n": len(tickers),
        "has_file": sum(1 for v in per.values() if v.get("file")),
        "depth_12q": sum(1 for v in per.values() if v.get("depth_12q")),
        "depth_20q": sum(1 for v in per.values() if v.get("depth_20q")),
        "cutoff_12q": c12.isoformat(),
        "cutoff_20q": c20.isoformat(),
        "per_ticker": per,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake-root", required=True, type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", type=Path, default=Path("."))
    ap.add_argument(
        "--cohorts-from",
        type=Path,
        help="reuse cohorts from a prior run's JSON instead of the DB "
        "(prod carries no statements for the excluded cohort)",
    )
    ap.add_argument("--as-of", type=date.fromisoformat, default=None)
    args = ap.parse_args()

    today = args.as_of or date.today()
    if args.cohorts_from:
        prior = json.loads(args.cohorts_from.read_text())
        cohorts = prior["cohorts"]
    else:
        cohorts = load_cohorts_from_db()

    root = args.lake_root.expanduser()
    stmt_q = cohorts["stmt_quarters"]
    result = {
        "probe": "fundamental lake price depth vs universe membership",
        "label": args.label,
        "lake_root": str(root),
        "as_of": today.isoformat(),
        "window_quarters": WINDOW_QUARTERS,
        "min_history": MIN_HISTORY,
        "cohorts": cohorts,
        "universe": measure(root, cohorts["universe"], today),
        "excluded": measure(root, cohorts["excluded"], today),
        "excluded_stmt_depth": {
            "ge_12q": sum(
                1 for t in cohorts["excluded"] if stmt_q.get(t, 0) >= MIN_HISTORY
            ),
            "ge_20q": sum(
                1 for t in cohorts["excluded"] if stmt_q.get(t, 0) >= WINDOW_QUARTERS
            ),
        },
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"depth_{args.label}.json"
    path.write_text(json.dumps(result, indent=1, sort_keys=True))

    u, e = result["universe"], result["excluded"]
    print(f"[{args.label}] root={root}")
    print(
        f"  universe {u['cohort_n']}: file={u['has_file']} 12q={u['depth_12q']} 20q={u['depth_20q']}"
    )
    print(
        f"  excluded {e['cohort_n']}: file={e['has_file']} 12q={e['depth_12q']} 20q={e['depth_20q']}"
    )
    print(f"  excluded statement depth: {result['excluded_stmt_depth']}")
    print(f"  wrote {path}")


if __name__ == "__main__":
    main()
