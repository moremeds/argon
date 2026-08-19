"""Stage-3 anchor job — a price band from each name's own valuation history.

Reads the tier-1 statement panel plus unadjusted daily closes, rebuilds every
ticker's own valuation-yield history, and persists one band per ticker per
PRICE date under the active method version.

WHY UNADJUSTED CLOSES
---------------------
`adj_close` is retroactively split-adjusted; `common_stock_shares_outstanding` is
as-reported at the filing. Multiplying the two mixes reference frames and
misprices every name across every split it has ever done — NVDA's 10:1 alone
moves its market cap by an order of magnitude, which would corrupt the whole
history the band's percentiles are drawn from. Raw close and as-reported shares
are both point-in-time, so their product is the market cap that was observable.

WHY `as_of` IS THE SPOT DATE, NOT THE FISCAL PERIOD OR THE CLOCK
---------------------------------------------------------------
The five levels only move when a filing lands, but `spot` and `spot_percentile`
move with the price, so the row has to be keyed on something that tracks price —
otherwise a same-day `DO NOTHING` freezes the first spot ever recorded into a row
that looks current.

`as_of` is the date of the close the row was priced at (`spot_date`, the last bar
in the ticker's series), NOT the date the job ran. Those coincide only when the
lake is current, and the lake is an EOD store: livewire lands a session's close
around midnight New York, well after this job's 18:20 ET slot. So a healthy run
on a Monday evening writes `as_of` = **Friday** — the newest close that existed
when it ran. A ticker whose series ends earlier still gets its real last close,
which is why old `as_of` values appear beside current ones and are correct.

Keying on the clock instead would be actively wrong: a stale lake would then mint
one row per calendar day all carrying the same spot, asserting a price
observation on days when none existed. Keying on the spot date writes exactly one
row per real observation, so the table stays a point-in-time record.

**Do not health-check this table with `max(as_of) >= today`** — that is
unsatisfiable by construction and reads a healthy job as a dead one. Check
`max(computed_at)` for liveness, and compare `max(as_of)` against the lake's own
last close for correctness.

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
from uw_scan.fundamentals.valuation import (
    FINANCIALS,
    FINANCIALS_REFUSAL,
    LEVEL_ORDER,
    METHOD_NUMERATOR,
    TYPE_YIELD,
    UNCLASSIFIED,
    anchor_inputs_hash,
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

#: Share of attempted bands refused that means the METHOD is wrong rather than
#: the names being unusual.
REFUSAL_ALERT_SHARE = 0.30


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
    method: str | None,
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
#: Deliberately partial. A sector with no rule falls through to `UNCLASSIFIED`,
#: which routes to the pooled-universe yield and SAYS SO on the card. What must
#: never happen is a name being forced into one of the five real types on a
#: guess: that produces a confident band built from the wrong yield with nothing
#: on screen to say the type was invented. Consumer, Healthcare, Defense and
#: Airlines all sit here — they are real sectors that this AI-supply-chain
#: taxonomy has no honest bucket for.
#:
#: Banks USED to sit there too, and that was a bug rather than a gap: the pooled
#: default is a claim that a name's EV yield is meaningful, which is false for a
#: deposit-funded balance sheet. See `FINANCIALS` for the measurement. They now
#: route to a type that refuses and says why.
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
    # Funding-financed balance sheets — routed to a refusal, not to a yield.
    # `Fintech` is the mixed one: HOOD is a broker and SOFI a lender, but PYPL
    # is a payment processor. The sector rule is right about the sector, so the
    # exception is per name and lives in `TICKER_TO_TYPE` below.
    "Banks": FINANCIALS,
    "Fintech": FINANCIALS,
}

#: Ticker -> company_type, checked BEFORE either sector map.
#:
#: For one situation only: a name whose sector label is right about its industry
#: and wrong about what prices it. Not a general escape hatch — a DB-level
#: `manual` assignment is that, and it still beats this (`assign` writes
#: `seeded` here, so a hand correction is never overwritten by a reseed).
TICKER_TO_TYPE: dict[str, str] = {
    # PYPL's chain sector is `Fintech`, which routes to the financials refusal
    # because deposit- and custodial-funded balance sheets carry no meaningful
    # enterprise value. That is right about PayPal's BALANCE SHEET — it holds
    # customer balances and runs a BNPL credit book — but `fcf_yield` divides by
    # MARKET CAP and never adds `net_debt` (see `EV_DENOMINATED`), so the
    # contamination the refusal exists to stop cannot reach this band at all.
    # The exception is therefore not a hole in the rule; it is a method the rule
    # never covered.
    #
    # Measured on the mini 2026-08-19 against the deployed engine
    # (`docs/research/2026-08-19-valuation-refusal-anatomy/pypl_route_probe.py`):
    # 0 of the trailing 20 quarters carry non-positive TTM free cash flow, and
    # the fcf_yield band lands at `confidence: high` with no caveats — against
    # `medium` plus a "no sector on file" caveat under the pooled default PYPL
    # has today. An upgrade on the status quo, not a rescue of it.
    #
    # What is NOT claimed: that fcf_yield was validated on PYPL specifically. It
    # was measured pooled (+0.0457, t 3.64). Calling PayPal a platform is a
    # judgement about the business, and it is recorded as one.
    "PYPL": "platform_scale",
}

#: Vendor sector -> company_type. A SEPARATE map from `SECTOR_TO_TYPE`, and the
#: separation is load-bearing rather than tidiness: the two vocabularies collide
#: on the word `Energy`. Argon's chain taxonomy means power generation by it and
#: routes it to `power_infra`/EV-EBITDA; the vendor vocabulary (GICS-style, as
#: `research_universe.sector` and UW's `/stock/{t}/info` both report it) means
#: oil and gas. Feeding vendor sectors through the chain map would silently
#: reprice every energy name.
#:
#: Exact match, not prefix: vendor sector strings are a closed vocabulary, so a
#: prefix rule would only create the chance of an accidental hit.
#:
#: Deliberately holds ONE rule. This map exists to answer a question the chain
#: taxonomy cannot ("is this a bank?"), not to reclassify the universe — every
#: other vendor sector falls through to `UNCLASSIFIED` exactly as before.
VENDOR_SECTOR_TO_TYPE: dict[str, str] = {
    "Financial Services": FINANCIALS,
}


def seed_company_types(
    conn: psycopg.Connection, *, schema: str = "uw_scan"
) -> dict[str, int]:
    """Route every universe ticker: name override, chain, vendor, else default.

    Idempotent and safe to re-run: `assign` refuses to overwrite a row marked
    `manual`, so the seeding pass never undoes a correction. It also lets a real
    sector match REPLACE a previous default, which is the direction that matters
    — a name that acquires a sector should stop being unclassified.

    The default is not a convenience. Re-measured 2026-08-19 on the widened
    universe: of 450 names, 185 carry a `watchlist` chain sector and 4 more are
    reachable only through `research_universe` — 261 carry none. Without a
    default those render an empty valuation block forever, not because the band
    cannot be computed but because nothing has classified them.

    The name override is checked first and holds one entry; see `TICKER_TO_TYPE`
    for why a per-name rule is legitimate here and when it is not.

    The vendor sector is the third pass and answers exactly one question the
    chain taxonomy cannot: is this a deposit-funded financial? It is read from
    `company_sector`, which `company_sector_refresh` fills — deliberately not
    fetched here, because this function runs inside `fundamental_refresh` and
    that chain's documented property is zero provider spend.
    """
    repo = FundamentalAnchorsRepository(conn, schema=schema)
    with conn.cursor() as cur:
        cur.execute(
            # LEFT JOIN, not JOIN: the point is to reach the names with no
            # watchlist row at all. DISTINCT because fundamental_universe carries
            # one row per TIER — a plain join visits a core+ranked ticker twice
            # and reports routing counts that do not match the tickers routed.
            # Two sector columns, deliberately NOT coalesced in SQL: the two
            # vocabularies route through different maps, so the caller has to
            # know WHICH one matched. Coalescing here would send a vendor sector
            # through the chain map and mean `Energy` twice.
            f"""SELECT DISTINCT f.ticker, w.sector, v.sector
                  FROM {schema}.fundamental_universe f
                  LEFT JOIN {schema}.watchlist w ON w.ticker = f.ticker
                  LEFT JOIN {schema}.company_sector v ON v.ticker = f.ticker
                 WHERE f.removed_at IS NULL"""
        )
        pairs = cur.fetchall()

    counters = {
        "seen": len(pairs),
        "routed": 0,
        "routed_vendor": 0,
        "routed_ticker": 0,
        "changed": 0,
        "defaulted": 0,
    }
    for ticker, sector, vendor_sector in pairs:
        # Chain sector first: it is hand-curated for THIS desk and strictly more
        # specific than a vendor sector (it separates Foundry from Memory, which
        # GICS calls one thing). The vendor sector only answers what the chain
        # taxonomy has no bucket for.
        matches = [k for k in SECTOR_TO_TYPE if sector and sector.startswith(k)]
        if ticker in TICKER_TO_TYPE:
            company_type = TICKER_TO_TYPE[ticker]
            note = f"ticker override (sector={sector!r})"
            counters["routed_ticker"] += 1
        elif matches:
            best = max(matches, key=len)
            company_type, note = SECTOR_TO_TYPE[best], f"sector={sector}"
            counters["routed"] += 1
        elif vendor_sector in VENDOR_SECTOR_TO_TYPE:
            company_type = VENDOR_SECTOR_TO_TYPE[vendor_sector]
            note = f"vendor_sector={vendor_sector}"
            counters["routed_vendor"] += 1
        else:
            company_type = UNCLASSIFIED
            note = f"no rule for sector={sector!r}" if sector else "no sector on file"
            counters["defaulted"] += 1
        counters["changed"] += repo.assign(
            ticker, company_type, source="seeded", note=note
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
        "inputs_hash": anchor_inputs_hash(
            company_type=company_type,
            engine=engine,
            fundamental=None,
            net_debt=None,
            shares=None,
            history_n=0,
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
    fx_root: Path,
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
        c: load_fx(fx_root, c)
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
        "financials": 0,
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
            if company_type == FINANCIALS:
                # PERSIST the refusal rather than skipping it. A skipped ticker
                # writes no row, and the card's no-row branch says "it has no
                # company_type, so no valuation method is routed to it — a gap
                # in our coverage, not a judgement about the company". For a
                # bank every clause of that is wrong: the type is known, the
                # omission is deliberate, and it IS a judgement about what can
                # be priced this way. The refusal is the finding, so it has to
                # reach the screen.
                spot_date, spot = px[-1]
                counters["financials"] += 1
                rows.append(
                    _refusal_row(
                        ticker=ticker,
                        as_of=as_of or spot_date,
                        engine=engine,
                        company_type=company_type,
                        # No method, and not a sentinel: see migration 124.
                        method=None,
                        spot=spot,
                        reasons=[FINANCIALS_REFUSAL],
                    )
                )
                continue
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
                # The band's OWN inputs, its routing and the rules that produced
                # it — see anchor_inputs_hash for why scoring.inputs_hash cannot
                # be reused here (it hashes the seven scoring features by name,
                # which a band has none of).
                "inputs_hash": anchor_inputs_hash(
                    company_type=company_type,
                    engine=engine,
                    fundamental=latest.get(METHOD_NUMERATOR[method]),
                    net_debt=latest.get("net_debt"),
                    shares=latest.get("shares"),
                    history_n=len(hist),
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

    # A run that computed bands and stored none of them is not a quiet no-op, it
    # is the identity key failing to notice that the answer changed — which is
    # exactly how the anchor hash bug hid: 233 bands computed, 0 written, and the
    # only symptom was a card showing yesterday's wrong JPM band. A same-day
    # re-run over genuinely unchanged inputs writes 0 too, so this is a WARN and
    # not an error, but it must never pass silently.
    if rows and counters["written"] == 0:
        log.warning(
            "anchors: %d rows computed and 0 written — every row collided on "
            "(ticker, as_of, engine_version, inputs_hash). Expected only when "
            "re-running over unchanged inputs; otherwise the hash is not seeing "
            "an input or rule that changed",
            len(rows),
        )

    # Fires on the SHARE, not on any one name. A handful of names whose own
    # history cannot anchor a price is expected; a third of the book reading that
    # way means the percentile window is wrong, which is exactly what the
    # full-history window was before 2026-08-12 with nothing in the pipeline
    # saying so.
    attempted = counters["banded"] + counters["refused"]
    if attempted and counters["refused"] / attempted > REFUSAL_ALERT_SHARE:
        log.warning(
            "anchors: %d/%d attempted bands refused (>%.0f%%) — check the "
            "percentile window before trusting the ones that did render",
            counters["refused"],
            attempted,
            REFUSAL_ALERT_SHARE * 100,
        )
    log.info("anchors: %s", counters)
    return counters
