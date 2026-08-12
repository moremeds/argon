"""Stage-3 anchor job — a price band from each name's own valuation history.

Reads the tier-1 statement panel plus unadjusted daily closes, rebuilds every
ticker's own valuation-yield history, and persists one band per ticker per
compute day under the active method version.

WHY UNADJUSTED CLOSES
---------------------
`adj_close` is retroactively split-adjusted; `common_stock_shares_outstanding` is
as-reported at the filing. Multiplying the two mixes reference frames and
misprices every name across every split it has ever done — NVDA's 10:1 alone
moves its market cap by an order of magnitude, which would corrupt the whole
history the band's percentiles are drawn from. Raw close and as-reported shares
are both point-in-time, so their product is the market cap that was observable.

WHY `as_of` IS THE COMPUTE DATE, NOT THE FISCAL PERIOD
------------------------------------------------------
The five levels only move when a filing lands, but `spot` and `spot_percentile`
move with the price. Keying on the compute date lets the daily snapshot of where
price sat inside its own band accumulate as history, instead of a same-day
`DO NOTHING` freezing the first spot ever recorded into a row that looks current.

The job never raises on a single ticker: a name missing prices, statements or a
company_type is counted and skipped, because one unrouted ticker must not cost
the other 250 their bands.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import psycopg

from uw_scan.fundamentals.scoring import inputs_hash
from uw_scan.fundamentals.valuation import (
    LEVEL_ORDER,
    METHOD_NUMERATOR,
    TYPE_YIELD,
    build_anchors,
    quarter_inputs,
    yield_at,
)
from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.worker.jobs.fundamental_scoring import _knowledge_date

log = logging.getLogger(__name__)

BAR_FILENAME = "1d.parquet"


def load_raw_closes(
    root: Path, tickers: list[str]
) -> dict[str, list[tuple[date, float]]]:
    """Unadjusted daily closes per ticker from the local parquet mirror.

    Points pyarrow at the explicit `1d.parquet` rather than the symbol directory:
    the directory also holds intraday parquets and zero-byte `.lock` markers, and
    a dataset read picks them up and fails on the lock file.

    Rows with a null trade_date are dropped — some symbols carry an
    alternate-schema partition mixed in, and the non-null rows are the clean
    series.
    """
    import pyarrow.parquet as pq

    out: dict[str, list[tuple[date, float]]] = {}
    for t in tickers:
        path = root / f"symbol={t}" / BAR_FILENAME
        if not path.exists():
            continue
        try:
            tab = pq.read_table(str(path), columns=["trade_date", "close"])
        except (OSError, ValueError) as exc:
            log.warning("anchors: unreadable bars for %s: %s", t, repr(exc))
            continue
        rows = [
            (d, float(c))
            for d, c in zip(
                tab.column("trade_date").to_pylist(), tab.column("close").to_pylist()
            )
            if d is not None and c is not None
        ]
        if rows:
            out[t] = sorted(rows)
    return out


def close_on_or_before(series: list[tuple[date, float]], when: date) -> float | None:
    """Last close at or before `when`. Never after — that is look-ahead."""
    lo, hi, found = 0, len(series) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= when:
            found = series[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return found


def _history(
    per: dict[str, Any],
    periods: list[str],
    closes: list[tuple[date, float]],
    method: str,
) -> tuple[list[float], dict[str, float | None], int]:
    """(own-history yields, the latest quarter's inputs, index of that quarter).

    Each historical yield is priced at ITS OWN knowledge date, so the series is
    the one the validation measured rather than today's price applied backwards.
    """
    hist: list[float] = []
    latest: dict[str, float | None] = {}
    latest_i = -1
    for i, p in enumerate(periods):
        qi = quarter_inputs(per, periods, i)
        know, _ = _knowledge_date(per, p)
        y = yield_at(method, qi, close_on_or_before(closes, know))
        if y is not None:
            hist.append(y)
        if qi.get(METHOD_NUMERATOR[method]) is not None and qi.get("shares"):
            latest, latest_i = qi, i
    return hist, latest, latest_i


#: Watchlist sector -> company_type, matched by PREFIX so the taxonomy's own
#: variants ("SaaS" / "Software/SaaS", "Semiconductor" / "Semi-Logic/ASIC") route
#: without a row each. Longest prefix wins, so a specific rule can override a
#: general one.
#:
#: Deliberately partial. A sector with no rule leaves the ticker UNROUTED, which
#: the card reports as an explicit absence — that is a better failure than a
#: catch-all bucket, because a wrong company_type produces a confident band built
#: from the wrong yield, and nothing on screen would say so.
SECTOR_TO_TYPE: dict[str, str] = {
    "Semi": "chips_cyclical",
    "Foundry": "chips_cyclical",
    "Memory": "chips_cyclical",
    "Computer/GPU": "chips_cyclical",
    "Networking/Optical": "chips_cyclical",
    "SaaS": "software_growth",
    "Software": "software_growth",
    "IT-Services": "software_growth",
    "M7": "platform_scale",
    "AI-App": "platform_scale",
    "Telecom-Media": "platform_scale",
    "Power/Electrical": "power_infra",
    "Generation/Nuclear": "power_infra",
    "Energy": "power_infra",
    "DC-Connect": "power_infra",
    "NeoCloud": "high_risk_growth",
    "AI-Cloud": "high_risk_growth",
    "Crypto": "high_risk_growth",
}


def seed_company_types(
    conn: psycopg.Connection, *, schema: str = "uw_scan"
) -> dict[str, int]:
    """Route tickers from the watchlist sector taxonomy. Hand edits survive.

    Idempotent and safe to re-run: `assign` refuses to overwrite a row marked
    `manual`, so the seeding pass never undoes a correction.
    """
    repo = FundamentalAnchorsRepository(conn, schema=schema)
    with conn.cursor() as cur:
        cur.execute(
            # DISTINCT because fundamental_universe carries one row per TIER — a
            # plain join visits a core+ranked ticker twice and reports routing
            # counts that do not match the number of tickers routed.
            f"""SELECT DISTINCT w.ticker, w.sector
                  FROM {schema}.watchlist w
                  JOIN {schema}.fundamental_universe f ON f.ticker = w.ticker
                 WHERE w.sector IS NOT NULL"""
        )
        pairs = cur.fetchall()

    counters = {"seen": len(pairs), "routed": 0, "changed": 0, "unmatched": 0}
    for ticker, sector in pairs:
        matches = [k for k in SECTOR_TO_TYPE if sector.startswith(k)]
        if not matches:
            counters["unmatched"] += 1
            continue
        best = max(matches, key=len)
        counters["routed"] += 1
        counters["changed"] += repo.assign(
            ticker, SECTOR_TO_TYPE[best], source="seeded", note=f"sector={sector}"
        )
    log.info("company_type seeding: %s", counters)
    return counters


def fundamental_anchors(
    *,
    conn: psycopg.Connection,
    lake_root: Path,
    schema: str = "uw_scan",
    tickers: list[str] | None = None,
    as_of: date | None = None,
) -> dict[str, int]:
    """Compute and persist anchor bands. Returns counters, never raises per ticker."""
    obs = FundamentalObsRepository(conn, schema=schema)
    scores = FundamentalScoresRepository(conn, schema=schema)
    anchors_repo = FundamentalAnchorsRepository(conn, schema=schema)

    engine = scores.active_version()
    if engine is None:
        log.warning("anchors: no active method version, nothing computed")
        return {"skipped_no_engine": 1}

    types = anchors_repo.company_types()
    panel = obs.statement_panel(tickers)
    universe = sorted(t for t in panel if t in types)
    closes = load_raw_closes(lake_root, universe)

    counters = {
        "considered": len(panel),
        "unrouted": len(panel) - len(universe),
        "no_prices": 0,
        "banded": 0,
        "refused": 0,
        "written": 0,
    }

    rows: list[dict[str, Any]] = []
    for ticker in universe:
        per = panel[ticker]
        px = closes.get(ticker)
        if not px:
            counters["no_prices"] += 1
            continue
        company_type = types[ticker]
        method = TYPE_YIELD.get(company_type)
        if method is None:
            counters["unrouted"] += 1
            continue

        periods = sorted(per["income-statements"])
        hist, latest, latest_i = _history(per, periods, px, method)
        if latest_i < 0:
            counters["refused"] += 1
            continue

        know, _ = _knowledge_date(per, periods[latest_i])
        spot_date, spot = px[-1]
        band = build_anchors(
            ticker=ticker,
            company_type=company_type,
            history=hist,
            fundamental=latest.get(METHOD_NUMERATOR[method]) or 0.0,
            net_debt=latest.get("net_debt") or 0.0,
            shares=latest.get("shares") or 0.0,
            spot=spot,
            knowledge_age_days=(spot_date - know).days,
        )
        counters["banded" if band["anchors"] else "refused"] += 1

        levels = band["anchors"] or dict.fromkeys(LEVEL_ORDER, None)
        rows.append(
            {
                "ticker": ticker,
                "as_of": as_of or spot_date,
                "engine_version": engine,
                # company_type is inside the hash (via scoring.inputs_hash), so a
                # routing change produces a genuinely new band rather than
                # colliding with the old one and being silently dropped.
                "inputs_hash": inputs_hash(
                    features={
                        "fundamental": latest.get(METHOD_NUMERATOR[method]),
                        "net_debt": latest.get("net_debt"),
                        "shares": latest.get("shares"),
                        "history_n": float(len(hist)),
                    },
                    company_type=company_type,
                    engine=engine,
                ),
                "company_type": company_type,
                "method": method,
                **levels,
                "spot": spot,
                "spot_percentile": band["spot_percentile"],
                "history_quarters": band["history_quarters"],
                "confidence": band["confidence"],
                "confidence_reasons_jsonb": band["confidence_reasons"],
                "inputs_jsonb": {
                    "numerator": METHOD_NUMERATOR[method],
                    "fundamental": latest.get(METHOD_NUMERATOR[method]),
                    "net_debt": latest.get("net_debt"),
                    "shares": latest.get("shares"),
                    "period_end": periods[latest_i],
                    "knowledge_date": know.isoformat(),
                    "spot_date": spot_date.isoformat(),
                },
                "source_obs_ids": per["obs_ids"].get(periods[latest_i], []),
            }
        )

    counters["written"] = anchors_repo.insert_anchors(rows)
    log.info("anchors: %s", counters)
    return counters
