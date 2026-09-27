"""fetch_bulk_daily_closes: request shape, parser, never-raise.

_BULK is a REAL response of apex GET /v1/equity/bars captured 2026-09-26:
XLK adjusted closes at adjustment_revision 80, and TWTR filed under `missing`
with apex's own reason. _SP500_FIRST_200 is the first 200 tickers, sorted,
of livewire presets/sp500.json (the list vendored in this task); only their
count matters to the chunking test. No network: httpx.MockTransport.
"""

from __future__ import annotations

from datetime import date

import httpx

from uw_scan.sources.apex import fetch_bulk_daily_closes

_START, _END = date(2026, 9, 10), date(2026, 9, 11)
_XLK_BARS = [
    {
        "time": "2026-09-10T00:00:00+00:00",
        "open": 185.02438884683545,
        "high": 186.3028989835443,
        "low": 184.35017451693037,
        "close": 185.00441212594936,
        "volume": 5571344,
    },
    {
        "time": "2026-09-11T00:00:00+00:00",
        "open": 187.13193290031646,
        "high": 188.42043139746835,
        "low": 186.66247995949368,
        "close": 187.45156043449367,
        "volume": 6535157,
    },
]
_BULK = {
    "price_mode": "adjusted",
    "basis": "split+dividend",
    "adjustment_revision": 80,
    "silver_revision": None,
    "timeframe": "1d",
    "window": {
        "start": "2026-09-10T00:00:00+00:00",
        "end": "2026-09-11T23:59:59+00:00",
    },
    "symbols": {
        "XLK": {"listing_status": "listed", "truncated": False, "bars": _XLK_BARS}
    },
    "missing": {"TWTR": "no Silver for delisted names; use price_mode=raw"},
    "generated_at": "2026-09-26T15:18:06.083800+00:00",
}
_XLK_CLOSES = {
    date(2026, 9, 10): 185.00441212594936,
    date(2026, 9, 11): 187.45156043449367,
}
_SP500_FIRST_200 = tuple(
    "A,AAPL,ABBV,ABNB,ABT,ACGL,ACN,ADBE,ADI,ADM,ADP,ADSK,AEE,AEP,AES,AFL,AIG,AIZ,AJG,AKAM"
    ",ALB,ALGN,ALL,ALLE,AMAT,AMCR,AMD,AME,AMGN,AMP,AMT,AMZN,ANET,AON,AOS,APA,APD,APH,APO,"
    "APP,APTV,ARE,ARES,ATO,AVGO,AVY,AWK,AXON,AXP,AZO,BA,BAC,BALL,BAX,BBY,BDX,BEN,BF.B,BG,"
    "BIIB,BKNG,BKR,BLDR,BLK,BMY,BNY,BR,BRK.B,BRO,BSX,BX,BXP,C,CAH,CARR,CASY,CAT,CB,CBOE,C"
    "BRE,CCI,CCL,CDNS,CDW,CEG,CF,CFG,CHD,CHRW,CHTR,CI,CIEN,CINF,CL,CLX,CMCSA,CME,CMG,CMI,"
    "CMS,CNC,CNP,COF,COHR,COIN,COO,COP,COR,COST,CPAY,CPRT,CPT,CRH,CRL,CRM,CRWD,CSCO,CSGP,"
    "CSX,CTAS,CTSH,CTVA,CVNA,CVS,CVX,D,DAL,DASH,DD,DDOG,DE,DECK,DELL,DG,DGX,DHI,DHR,DIS,D"
    "LR,DLTR,DOC,DOV,DOW,DPZ,DRI,DTE,DUK,DVA,DVN,DXCM,EBAY,ECHO,ECL,ED,EFX,EG,EIX,EL,ELV,"
    "EME,EMR,EOG,EQIX,EQT,ERIE,ES,ESS,ETN,ETR,EVRG,EW,EXC,EXE,EXPD,EXPE,EXR,F,FANG,FAST,F"
    "CX,FDS,FDX,FDXF,FE,FERG,FFIV,FICO,FIS,FISV,FITB,FIX,FLEX,FOX,FOXA,FRT,FSLR,FTNT,FTV,"
    "GD,GDDY".split(",")
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_nested_shape_parses_and_missing_symbols_are_absent():
    out = fetch_bulk_daily_closes(
        ["XLK", "TWTR"],
        start=_START,
        end=_END,
        client=_client(lambda req: httpx.Response(200, json=_BULK)),
    )
    # TWTR is in `missing` (delisted: no Silver) → absent, never an empty or zero series
    assert out == {"XLK": _XLK_CLOSES}


def test_request_is_one_tz_aware_adjusted_full_window_call():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=_BULK)

    fetch_bulk_daily_closes(
        ["xlk", "XLK", "TWTR"], start=_START, end=_END, client=_client(handler)
    )
    assert len(seen) == 1
    q = seen[0].url.params
    assert seen[0].url.path == "/v1/equity/bars"
    assert q["symbols"] == "XLK,TWTR"  # upper-cased, deduped, order kept
    assert q["timeframe"] == "1d"
    assert q["price_mode"] == "adjusted"
    assert q["listing"] == "any"
    assert q["limit"] == "0"
    # apex answers 400 invalid_parameter for a bare date or naive timestamp
    # ("start must carry a UTC offset"), so the client must send an explicit Z
    assert q["start"] == "2026-09-10T00:00:00Z"
    assert q["end"] == "2026-09-11T23:59:59Z"


def test_201_symbols_are_two_calls_of_200_and_1():
    seen: list[list[str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.params["symbols"].split(","))
        return httpx.Response(200, json={**_BULK, "symbols": {}, "missing": {}})

    fetch_bulk_daily_closes(
        [*_SP500_FIRST_200, "XLK"], start=_START, end=_END, client=_client(handler)
    )
    assert [len(s) for s in seen] == [200, 1]
    assert seen[1] == ["XLK"]


def test_a_failed_chunk_costs_only_that_chunk():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params["symbols"] == "XLK":
            return httpx.Response(200, json=_BULK)
        return httpx.Response(
            503, json={"error": {"code": "adjusted_unavailable", "message": "mocked"}}
        )

    out = fetch_bulk_daily_closes(
        [*_SP500_FIRST_200, "XLK"], start=_START, end=_END, client=_client(handler)
    )
    assert out == {"XLK": _XLK_CLOSES}


def test_transport_error_and_garbage_never_raise():
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    def html(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy page</html>")

    def wrong_shape(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"symbols": ["XLK"], "missing": []})

    def bad_request(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": "invalid_parameter", "message": "mocked"}}
        )

    for h in (boom, html, wrong_shape, bad_request):
        assert (
            fetch_bulk_daily_closes(["XLK"], start=_START, end=_END, client=_client(h))
            == {}
        )
    assert (
        fetch_bulk_daily_closes([], start=_START, end=_END, client=_client(boom)) == {}
    )
