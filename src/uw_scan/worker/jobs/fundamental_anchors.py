"""Stage-3 anchor job — a price band from each name's own valuation history.

Reads the tier-1 statement panel plus split-adjusted daily closes, rebuilds
every ticker's own valuation-yield history, and persists one band per ticker per
PRICE date under the active method version.

WHY PRICES COME FROM SILVER — AND WHY THIS FILE ONCE ARGUED FOR RAW
-------------------------------------------------------------------
This section used to argue for RAW closes, on the premise that
`common_stock_shares_outstanding` is as-reported at the filing, so that raw price
and as-reported shares are both point-in-time and their product is the market cap
that was observable. The reasoning is sound. The premise is false for this
provider, and it was never checked.

UW restates share counts onto TODAY's split basis, back to the beginning of the
panel. Measured 2026-08-21 against the mini's store:

    TSLA 2021-12-31  3,100,522,833   actual then ~1,033M  (3-for-1, Aug 2022)
    KLAC 2021-12-31  1,523,310,000   actual then   ~152M  (10-for-1, Jun 2026)
    BKNG 2021-12-31  1,034,275,000   actual then    ~41M  (25-for-1, Apr 2026)

Each is the real count times the factor of a split that had not happened yet. So
`fundamental / shares` arrives already in today's units, and pairing it with a
raw price mixes exactly the two reference frames the old note set out to keep
apart — in the opposite direction, and unnoticed, because nothing downstream
compares a band against the price scale it was built from.

The damage was not subtle. On 2026-08-18, 26 of 335 bands were built across a
split inside their own window, and 12 of those rendered as sitting in the buy
zone: BKNG at $208.25 against a `buy_below` of $4,702.64 read as cheap, because
20 quarters of its sales yield were 25x too low. A reverse split runs the same
error the other way and buries a name under a band it can never reach.

So price has to be put on the same basis the share counts already use, and the
producer already does it: livewire's SILVER tier publishes fully back-adjusted
daily bars with `price_adjustment_factor` and `split_volume_factor` per session.
Argon reads those rather than adjusting bronze itself. Silver is better than
anything reconstructable here on three counts:

* It repairs a defect argon cannot see around. Bronze's legacy segment was
  back-adjusted by an old backfill and its newer rows are raw as-traded,
  concatenated unreconciled — TSLA steps 203.37 -> 609.89 on 2021-06-11, WMT
  46.63 -> 140.75 the same day, both `source='legacy'`, in opposite directions.
  Silver starts TSLA/WMT/CTAS exactly at 2021-06-11 and carries KLAC, whose bronze
  basis is clean throughout, all the way back to 1980.
* It is per-symbol rather than a global cutoff. An earlier version of this job
  clamped every series to 2021-06-11, which is livewire's boundary for the
  ambiguous symbols and nobody else's — it silently cost KLAC forty years.
* Where livewire cannot establish a basis it publishes NOTHING (18 of 450 on
  2026-08-21, `price_basis='unknown'` on bronze), which is a refusal argon can
  read, not a wrong number it has to detect.

`corporate_actions` still earns its keep, in a smaller role: for those 18, it is
the evidence for whether raw bronze is usable anyway — see
`_bronze_basis_refusal`.
Its splits come from massive's `/v3/reference/splits`, an authoritative event
list, never a price-gap heuristic. That distinction matters: DOCU fell 42% in a
day on 2021-12-03 and SOUN 48% on 2022-12-30, and any cliff detector wide enough
to catch a 2-for-1 also eats those, deleting real valuation history.

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
    WINDOW_QUARTERS,
    anchor_inputs_hash,
    build_anchors,
    quarter_inputs,
    yield_at,
)
from uw_scan.storage.company_identity import (
    STATUS_DEFAULTED,
    STATUS_EVIDENCED,
    CompanyIdentityRepository,
)
from uw_scan.storage.corporate_actions import CorporateActionsRepository
from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.storage.fundamental_observation_panels import current_statement_panel
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.worker.jobs.fundamental_scoring import _knowledge_date

log = logging.getLogger(__name__)

BAR_FILENAME = "1d.parquet"

#: Share of attempted bands refused that means the METHOD is wrong rather than
#: the names being unusual.
REFUSAL_ALERT_SHARE = 0.30


#: Columns the silver tier adds on top of bronze's raw OHLCV. `close` there is
#: already back-adjusted for BOTH splits and dividends; dividing it back out by
#: `price_adjustment_factor * split_volume_factor` leaves a SPLIT-ONLY series,
#: which is the one a valuation yield needs — see `load_closes`.
_SILVER_COLUMNS = [
    "trade_date",
    "close",
    "price_adjustment_factor",
    "split_volume_factor",
]


def load_closes(
    root: Path, tickers: list[str], *, adjusted: bool
) -> dict[str, list[tuple[date, float]]]:
    """Daily closes per ticker from one tier of the parquet lake.

    Points pyarrow at the explicit `1d.parquet` rather than the symbol directory:
    the directory also holds intraday parquets and zero-byte `.lock` markers, and
    a dataset read picks them up and fails on the lock file.

    Rows with a null trade_date are dropped — some symbols carry an
    alternate-schema partition mixed in, and the non-null rows are the clean
    series.

    `adjusted=True` reads livewire's SILVER tier, whose closes are already
    restated onto today's corporate-action basis, and divides each by
    `price_adjustment_factor * split_volume_factor` to undo the DIVIDEND half of
    that restatement. Both halves matter and they pull opposite ways:

    * Splits must be adjusted for. The provider restates historical share counts
      onto today's post-split basis, so `fundamental/shares` is already in
      today's units while a raw price is not, and the yield the two form is wrong
      by the split factor for every quarter before the split. BKNG's 1-for-25 on
      2026-04-06 put 20 quarters of sales yield 25x too low, which set
      `buy_below` at $4,702.64 against a $208.25 spot and rendered the name as
      sitting in its buy zone. 26 of 335 bands carried a split inside their own
      window on 2026-08-18 and 12 of those were on the buy list.
    * Dividends must NOT be. A cash dividend genuinely lowers market cap; nothing
      restates the share count for it. Leaving silver's dividend adjustment in
      understates every historical market cap on a payer, inflates the historical
      yields, and biases the whole band cheap against an unadjusted spot.

    `market_cap(t) = shares_restated(t) * split_only_close(t)` is the identity
    this reconstructs, and it is exact: for BKNG on 2026-04-02 it returns 167.77
    against a raw close of 4194.25 and a 25.0 split factor.

    `adjusted=False` reads BRONZE closes verbatim. That is only correct for a
    ticker with no split inside the window being priced — the caller must
    establish that, because bronze carries no corporate-action treatment of its
    own and its legacy rows may be on any basis (`price_basis='unknown'`).
    """
    import pyarrow.parquet as pq

    out: dict[str, list[tuple[date, float]]] = {}
    for t in tickers:
        path = root / f"symbol={t}" / BAR_FILENAME
        if not path.exists():
            continue
        try:
            tab = pq.read_table(
                str(path),
                columns=_SILVER_COLUMNS if adjusted else ["trade_date", "close"],
            ).to_pydict()
        except (OSError, ValueError, KeyError) as exc:
            log.warning("anchors: unreadable bars for %s: %s", t, repr(exc))
            continue
        if adjusted:
            rows = [
                (d, float(c) / (float(pf) * float(svf)))
                for d, c, pf, svf in zip(
                    tab["trade_date"],
                    tab["close"],
                    tab["price_adjustment_factor"],
                    tab["split_volume_factor"],
                )
                if d is not None and c is not None and pf and svf
            ]
        else:
            rows = [
                (d, float(c))
                for d, c in zip(tab["trade_date"], tab["close"])
                if d is not None and c is not None
            ]
        if rows:
            out[t] = sorted(rows)
    return out


def _bronze_basis_refusal(
    per: dict[str, Any],
    periods: list[str],
    events: list[tuple[date, float]],
    *,
    ingested: bool,
) -> str | None:
    """Why a bronze-priced name cannot be banded, or None when it may be.

    A split OUTSIDE the window is harmless even on an unknown price basis: the
    shares restated to today equal the shares as-filed across the whole window,
    so any consistent basis is today's basis. Inside it, the two disagree by the
    split factor and the yield series is not on one basis at all.

    That argument only holds while "no split on record" means the ingest looked
    and found none. Where it never looked, an empty list is an absence of
    evidence and this refuses instead — see
    `CorporateActionsRepository.ingested_tickers` for why zero rows is a sound
    proxy for never-looked, and for the 15 names it silently mispriced before.
    """
    if not ingested:
        return (
            "no corporate-action history is on record for this name, which is "
            "indistinguishable from never having asked, so a split inside the "
            "window being priced cannot be ruled out and the lake has no "
            "corporate-action-adjusted series to fall back on"
        )
    if not periods or not events:
        return None
    start = _knowledge_date(per, periods[-WINDOW_QUARTERS:][0])[0]
    if any(d >= start for d, _ in events):
        return (
            "this name split inside the window being priced and the lake has no "
            "corporate-action-adjusted series for it, so its history and its "
            "quote are on different share bases"
        )
    return None


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
    identity = CompanyIdentityRepository(conn, schema=schema)
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT ticker, cik FROM {schema}.sec_cik_map"""
        )
        ciks = dict(cur.fetchall())
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
                  -- upper(): `company_sector` stores the uppercase ticker, so a
                  -- lowercase universe row would silently never match its own
                  -- cached sector and stay unrouted forever.
                  LEFT JOIN {schema}.company_sector v ON v.ticker = upper(f.ticker)
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
        "identity_intervals": 0,
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
        # M1.4: the same routing decision, recorded as a HISTORY interval with
        # its evidence status. `defaulted` is not a type — it is the record that
        # nothing matched and the pooled fallback applied, which is what makes
        # the coverage figure mean something rather than count rows.
        counters["identity_intervals"] += identity.assign(
            ticker,
            company_type=company_type,
            status=(
                STATUS_DEFAULTED if company_type == UNCLASSIFIED else STATUS_EVIDENCED
            ),
            evidence=note,
            sector=sector or vendor_sector,
            issuer_cik=ciks.get(ticker.upper()),
            note=note,
        )
    log.info("company_type seeding: %s", counters)
    return counters


def _refusal_row(
    *,
    ticker: str,
    as_of: date,
    engine: str,
    company_type: str,
    # NULL when the refusal is that NO method applies to the type at all
    # (`financials`); a real method name for every refusal taken UNDER one.
    method: str | None,
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
    silver_root: Path,
    schema: str = "uw_scan",
    tickers: list[str] | None = None,
    as_of: date | None = None,
    fx_root: Path,
) -> dict[str, int]:
    """Compute and persist anchor bands. Returns counters, never raises per ticker."""
    # First, and before any DB work: the whole tier absent is a mount or a path
    # error, never a data gap, and it is the one failure that would put every
    # name back on unadjusted bronze — silently reinstating the bug this job was
    # fixed for. Refuse the run. The rows already written stay readable and
    # yesterday's bands stand, which beats minting a universe of wrong ones.
    if not silver_root.is_dir():
        raise RuntimeError(
            f"anchors: no silver tier at {silver_root} — refusing to price the "
            "universe from unadjusted bronze"
        )

    scores = FundamentalScoresRepository(conn, schema=schema)
    anchors_repo = FundamentalAnchorsRepository(conn, schema=schema)

    engine = scores.active_version()
    if engine is None:
        log.warning("anchors: no active method version, nothing computed")
        return {"skipped_no_engine": 1}

    types = anchors_repo.company_types()
    # Current panel, explicitly. Anchors describe a name's own valuation history
    # as it stands today; gating them on availability evidence would empty the
    # buy-zone surface for every name whose claims are only capture-bounded.
    panel = current_statement_panel(conn, tickers, schema=schema)
    universe = sorted(t for t in panel if t in types)
    ca_repo = CorporateActionsRepository(conn, schema=schema)
    splits = ca_repo.split_factors(universe)
    ingested = ca_repo.ingested_tickers(universe)
    closes = load_closes(silver_root, universe, adjusted=True)

    # ponytail: bronze fallback for names livewire cannot yet adjust. Silver is
    # absent exactly when bronze's own `price_basis` is `unknown`, i.e. the
    # producer refuses to guess what basis its legacy rows are on — 18 of the
    # 450-name universe on 2026-08-21, including HON, CMCSA and MSTR. Bronze is
    # nonetheless provably equivalent for a name with NO split inside the window
    # being priced, because an unknown-but-consistent basis is today's basis when
    # nothing has restated the shares since. The per-ticker guard below enforces
    # that, and once the ingest covers the universe it refuses 4 of the 18 —
    # CXAI, HON, MSTR, TRI, the four with a real in-window split. Drop this whole
    # branch when livewire resolves `price_basis` for them.
    on_bronze = set(universe) - set(closes)
    if on_bronze:
        closes |= load_closes(lake_root, sorted(on_bronze), adjusted=False)
        log.info(
            "anchors: %d names have no silver series, priced from bronze if a "
            "clean split record proves the basis (%d of them have one)",
            len(on_bronze),
            len(on_bronze & ingested),
        )

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
        # Names refused because they have no silver series AND a split inside
        # their own window, so no price series on today's basis exists for them.
        # Falls to zero as livewire resolves `price_basis`; a RISE means the
        # producer is losing ground, so it is counted rather than assumed away.
        "unadjustable_prices": 0,
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

        # A bronze-priced name whose window spans one of its own splits cannot be
        # put on a single basis at all: the shares are restated to today and the
        # price is on whatever basis the legacy backfill left. REFUSE rather than
        # band it — CXAI's 50-for-1 on 2026-08-18 left `buy_below` at $0.107
        # against a $4.59 spot, and TRI's buyback consolidations put it on the
        # buy list 24% below a band it had not earned.
        unadjustable = (
            _bronze_basis_refusal(
                per,
                periods,
                splits.get(ticker, ()),
                ingested=ticker in ingested,
            )
            if ticker in on_bronze
            else None
        )
        if unadjustable:
            counters["unadjustable_prices"] += 1
            rows.append(
                _refusal_row(
                    ticker=ticker,
                    as_of=as_of or spot_date,
                    engine=engine,
                    company_type=company_type,
                    method=method,
                    spot=spot,
                    reasons=[unadjustable],
                )
            )
            continue

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
