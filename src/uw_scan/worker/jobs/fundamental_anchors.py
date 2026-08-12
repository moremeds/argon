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

from uw_scan.fundamentals.fx import (
    METHOD_STATEMENTS,
    USD_LIKE,
    convert,
    load_fx,
)
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


#: UW serializes a missing currency as the LITERAL STRING "None", not as JSON
#: null — measured on AMZN, APLD, OXY, VST and WDC, all US filers. Treating it as
#: a currency code is not a cosmetic bug: the newest-first walk below would stop
#: on it, and NBIS (which reports RUB on its real rows) would be read as
#: USD-like and banded from unconverted rubles.
_CURRENCY_SENTINELS = frozenset({"", "none", "null", "nan"})


#: Panel key -> the statement name `fx.FIELD_SOURCE` uses.
_STATEMENT_KEYS = {
    "income": "income-statements",
    "balance": "balance-sheets",
    "cash_flow": "cash-flows",
}


def statement_currencies(
    per: dict[str, Any], periods: list[str]
) -> dict[str, str | None]:
    """Newest REAL reporting currency PER STATEMENT.

    Per statement, not per filer: NBIS reports USD on income and balance while
    its cash-flow statement reports RUB, in the same quarter. Resolving one
    currency for the ticker picks whichever statement is read first and applies
    it to figures that were never denominated in it.

    Newest-first because the field arrived part-way through UW's history, so the
    oldest rows legitimately carry nothing; sentinel-skipping because a walk that
    stops on the literal string "None" reclassifies a foreign filer as domestic.
    """
    out: dict[str, str | None] = {}
    for name, key in _STATEMENT_KEYS.items():
        out[name] = None
        for p in reversed(periods):
            cur = (per.get(key, {}).get(p) or {}).get("reported_currency")
            if cur and str(cur).strip().lower() not in _CURRENCY_SENTINELS:
                out[name] = str(cur).strip().upper()
                break
    return out


def _history(
    per: dict[str, Any],
    periods: list[str],
    closes: list[tuple[date, float]],
    method: str,
    *,
    currencies: dict[str, str | None] | None = None,
    fx: dict[str, list[tuple[date, float]]] | None = None,
) -> tuple[list[float], dict[str, float | None], int]:
    """(own-history yields, the latest quarter's inputs, index of that quarter).

    Each historical yield is priced at ITS OWN knowledge date, so the series is
    the one the validation measured rather than today's price applied backwards.

    For a foreign filer each quarter is translated at ITS OWN contemporaneous
    rate, never at today's. USDEUR ran 0.747-0.859 across this history, so one
    rate applied backwards would reshape the distribution the percentiles are
    drawn from rather than merely shift it.
    """
    hist: list[float] = []
    latest: dict[str, float | None] = {}
    latest_i = -1
    for i, p in enumerate(periods):
        qi = quarter_inputs(per, periods, i)
        if currencies and any(c not in USD_LIKE for c in currencies.values()):
            # The TTM window the flow figures accrued over: this quarter plus the
            # three before it, so the average rate covers the same span as the sum.
            converted = convert(
                qi,
                currencies=currencies,
                series_by_ccy=fx or {},
                period_end=date.fromisoformat(p),
                ttm_start=date.fromisoformat(periods[max(0, i - 3)]),
            )
            if converted is None:
                continue
            qi = converted
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


def _refusal_row(
    *,
    ticker: str,
    as_of: date,
    engine: str,
    company_type: str,
    method: str,
    spot: float,
    reasons: list[str],
) -> dict[str, Any]:
    """A persisted refusal. Written rather than skipped so the card can SAY why
    it has no band — a skipped ticker renders as an unexplained blank."""
    return {
        "ticker": ticker,
        "as_of": as_of,
        "engine_version": engine,
        "inputs_hash": inputs_hash(
            features={}, company_type=company_type, engine=engine
        ),
        "company_type": company_type,
        "method": method,
        **dict.fromkeys(LEVEL_ORDER, None),
        "spot": spot,
        "spot_percentile": None,
        "history_quarters": 0,
        "confidence": "none",
        "confidence_reasons_jsonb": reasons,
        "inputs_jsonb": {},
        "source_obs_ids": [],
    }


def fundamental_anchors(
    *,
    conn: psycopg.Connection,
    lake_root: Path,
    schema: str = "uw_scan",
    tickers: list[str] | None = None,
    as_of: date | None = None,
    fx_root: Path | None = None,
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

    # One FX series per distinct foreign reporting currency, loaded once. Five
    # filers in the measured 257-name panel report non-USD; the rest short-circuit.
    currencies = {
        t: statement_currencies(panel[t], sorted(panel[t]["income-statements"]))
        for t in universe
    }
    fx_series = {
        c: load_fx(fx_root or lake_root.parent / "asset_class=fx", c)
        for c in {
            v
            for per_ccy in currencies.values()
            for v in per_ccy.values()
            if v not in USD_LIKE
        }
    }
    for c, s in fx_series.items():
        log.info("anchors: fx %s -> %d observations", c, len(s))

    counters = {
        "considered": len(panel),
        "unrouted": len(panel) - len(universe),
        "no_prices": 0,
        "no_fx": 0,
        "converted": 0,
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
        by_statement = currencies.get(ticker) or {}
        spot_date, spot = px[-1]

        # Blocked only by a currency THIS METHOD reads. NBIS's RUB cash-flow
        # statement does not stop `sales_to_ev`, which needs income + balance and
        # finds both in USD — refusing on any non-USD statement anywhere would
        # drop a name we can price correctly.
        blocked = sorted(
            {
                str(by_statement.get(st))
                for st in METHOD_STATEMENTS[method]
                if by_statement.get(st) not in USD_LIKE
                and not fx_series.get(str(by_statement.get(st)))
            }
        )
        foreign = any(
            by_statement.get(st) not in USD_LIKE for st in METHOD_STATEMENTS[method]
        )

        # A foreign filer with no FX series is REFUSED, never banded unconverted.
        # This is the quiet failure the EV guard does not catch: ASML (EUR) and
        # NOK produced full bands at plausible prices before this existed, ASML
        # at `confidence: high`.
        if blocked:
            counters["no_fx"] += 1
            names = ", ".join(blocked)
            rows.append(
                _refusal_row(
                    ticker=ticker,
                    as_of=as_of or spot_date,
                    engine=engine,
                    company_type=company_type,
                    method=method,
                    spot=spot,
                    reasons=[
                        f"statements this method reads are reported in {names} and no "
                        f"USD{blocked[0]} series is available, so the filing and the "
                        f"quote cannot be put in one currency"
                    ],
                )
            )
            continue

        hist, latest, latest_i = _history(
            per,
            periods,
            px,
            method,
            currencies=by_statement,
            fx=fx_series,
        )
        if latest_i < 0:
            counters["refused"] += 1
            continue
        if foreign:
            counters["converted"] += 1

        know, _ = _knowledge_date(per, periods[latest_i])
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
