"""POST /api/stock/{ticker}/technicals/refresh — on-demand EOD technicals compute.

apex is unreachable in tests, so fetch_daily_bars is monkeypatched to a
deterministic labeled ramp (a test double — not market data presented as real).
The real compute + store + read-back path runs otherwise unchanged.
"""

from __future__ import annotations

import math

import pandas as pd

from uw_scan.worker.jobs import technical_daily_refresh as tdr_mod


def _ramp_bars(n: int = 600, start: float = 100.0) -> list[dict]:
    out = []
    for i in range(n):
        d = pd.Timestamp("2020-01-01", tz="UTC") + pd.Timedelta(days=i)
        close = start * (1.0007**i) * (1 + 0.01 * math.sin(i / 7))
        out.append(
            {
                "time": d.isoformat(),
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000,
                "vwap": None,
            }
        )
    return out


def test_refresh_endpoint_computes_empty_to_ready(
    client, seeded_db_empty_cards, monkeypatch
):
    # Precondition: no technical_daily rows for IWM -> empty.
    assert client.get("/api/stock/IWM/technicals").json()["backfill_status"] == "empty"

    monkeypatch.setattr(tdr_mod, "fetch_daily_bars", lambda t, **k: _ramp_bars())
    resp = client.post("/api/stock/IWM/technicals/refresh")

    assert resp.status_code == 200
    body = resp.json()
    assert body["backfill_status"] == "ready"
    assert body["series"], "series should be populated after compute"
    assert body["series"][-1]["fast_macd_hist_atr"] is not None
    assert body["detail"]["dual_macd"]["trend_state"] in {
        "BULLISH",
        "BEARISH",
        "IMPROVING",
        "DETERIORATING",
    }


def test_refresh_endpoint_thin_history_stays_empty(
    client, seeded_db_empty_cards, monkeypatch
):
    monkeypatch.setattr(tdr_mod, "fetch_daily_bars", lambda t, **k: _ramp_bars(n=150))
    resp = client.post("/api/stock/IWM/technicals/refresh")

    assert resp.status_code == 200
    assert resp.json()["backfill_status"] == "empty"


def test_refresh_endpoint_survives_midjob_write_failure(
    client, seeded_db_empty_cards, monkeypatch
):
    # If the detail write raises AFTER upsert_series has committed, the per-ticker
    # except must rollback so the shared request connection isn't left in an
    # aborted-transaction state — otherwise the follow-up read 500s.
    from uw_scan.storage.technicals_repository import TechnicalsRepository

    monkeypatch.setattr(tdr_mod, "fetch_daily_bars", lambda t, **k: _ramp_bars())

    def boom(self, *a, **k):
        # A real mid-statement DB error aborts the psycopg transaction (unlike a
        # plain Python raise, which leaves the connection usable).
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1 / 0")

    monkeypatch.setattr(TechnicalsRepository, "set_latest_detail", boom)
    resp = client.post("/api/stock/IWM/technicals/refresh")

    assert resp.status_code == 200  # graceful, not a 500 from an aborted txn


_LOCK_SQL = "('x' || substr(md5('technicals_refresh:' || %s), 1, 16))::bit(64)::bigint"


def test_refresh_endpoint_single_flight(client, seeded_db_empty_cards, monkeypatch):
    # A concurrent compute for the same ticker (lock held on another session)
    # must short-circuit — no duplicate apex fetch / redundant recompute.
    called: list[str] = []
    monkeypatch.setattr(
        tdr_mod, "fetch_daily_bars", lambda t, **k: called.append(t) or _ramp_bars()
    )
    conn = seeded_db_empty_cards.conn
    with conn.cursor() as cur:
        cur.execute(f"SELECT pg_try_advisory_lock({_LOCK_SQL})", ("IWM",))
        assert cur.fetchone()[0] is True
    try:
        resp = client.post("/api/stock/IWM/technicals/refresh")
        assert resp.status_code == 200
        assert resp.json()["backfill_status"] == "empty"  # did not recompute
        assert called == []  # technical_daily_refresh never ran
    finally:
        with conn.cursor() as cur:
            cur.execute(f"SELECT pg_advisory_unlock({_LOCK_SQL})", ("IWM",))
