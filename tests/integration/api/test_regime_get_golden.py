"""Golden of every regime GET response (I-37, I-38 proof).

Written BEFORE the regime router was split: every ``GET /api/regime*`` route
the app registers is called on an empty DB and on a seeded DB (fixed-date
history + live quotes + an EOD VRP row), and again once those quotes are
stale and EOD CRI/VCG snapshots exist (the EOD branch of every live
endpoint), and status + body must equal the
committed ``golden/regime_gets.json``. Routes are discovered from the app, so
a route that disappears or appears fails the test too.

The clock is frozen, not normalised out of the bodies: the live endpoints
compare quote age to now, splice the quote's ET date as today's bar and stamp
``scan_time``. The freeze patches the ``datetime``/``date`` names of every
loaded ``uw_scan.api.routers.regime*`` module (so it still reaches the code
after it moves between modules) and of the two compute modules that read the
clock on these paths.

Floats are rounded to 9 significant digits before comparing: the live compute
goes through numpy/libm, whose last bits differ between the macOS laptop and
the Linux CI runner (225.76248716385896 vs 225.7624871638585). Nine digits
keeps every displayed value and drops only that platform noise.

Regenerate (only for an intentional response change):
``REGIME_GOLDEN_WRITE=1 uv run pytest tests/integration/api/test_regime_get_golden.py``
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from tests.integration.api.test_vrp_macro_signal_endpoint import _seed_spx_skip
from tests.integration.reports.test_vrp_macro_signal import _seed_spx_vix_varied
from tests.integration.test_regime_live_compute import LAST_BAR
from tests.integration.test_regime_live_compute import _seed as _seed_vol_history
from uw_scan.scanners import cri as cri_scanner
from uw_scan.scanners import vcg as vcg_scanner

GOLDEN = Path(__file__).resolve().parent / "golden" / "regime_gets.json"

# The live session of the fixed-date history seed (2026-06-12, a Friday).
NOW = _dt.datetime(2026, 6, 12, 15, 30, 5, tzinfo=_dt.timezone.utc)
QUOTED_AT = _dt.datetime(2026, 6, 12, 15, 30, 0, tzinfo=_dt.timezone.utc)

# Query params a route needs to return more than a 422.
PARAMS = {"ticker": "SPX"}

_CLOCK_MODULES = ("uw_scan.scanners.live_quotes", "uw_scan.reports.vrp_macro_signal")


class _FrozenDateTime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):  # type: ignore[override]
        return NOW.replace(tzinfo=None)


class _FrozenDate(_dt.date):
    @classmethod
    def today(cls):  # type: ignore[override]
        return NOW.date()


@pytest.fixture
def frozen_clock(monkeypatch, client):
    # timestamptz values render in the DB session's timezone; pin it so the
    # golden is the same on a UTC CI runner and on a local +08:00 Postgres.
    monkeypatch.setenv("PGTZ", "UTC")
    # `client` first: create_app() has imported every router module by now.
    names = [
        m
        for m in list(sys.modules)
        if m.startswith("uw_scan.api.routers.regime") or m in _CLOCK_MODULES
    ]
    for name in names:
        mod = sys.modules[name]
        for attr in ("datetime", "_datetime", "date", "_date"):
            val = getattr(mod, attr, None)
            if val is _dt.datetime:
                monkeypatch.setattr(mod, attr, _FrozenDateTime)
            elif val is _dt.date:
                monkeypatch.setattr(mod, attr, _FrozenDate)
    return client


def _regime_get_paths(client) -> list[str]:
    paths = set()
    for route in client.app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/regime") and "GET" in getattr(route, "methods", ()):
            paths.add(path)
    return sorted(paths)


def _round_floats(value):
    if isinstance(value, float):
        return float(f"{value:.9g}")
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v) for v in value]
    return value


def _sweep(client) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in _regime_get_paths(client):
        r = client.get(path, params=PARAMS)
        try:
            body = r.json()
        except ValueError:
            body = r.text
        out[path] = {"status": r.status_code, "body": _round_floats(body)}
    return out


def _seed(repo) -> None:
    _seed_vol_history(repo.conn)  # 130 fixed-date bars ending 2026-06-11
    _seed_spx_vix_varied(repo)  # 2018 SPX/VIX history for the VRP z window
    _seed_spx_skip(repo)  # one basis='eod' SPX VRP macro row
    repo.bulk_upsert_intraday_quotes(
        [
            ("VIX", Decimal("25.5"), QUOTED_AT, "xenon_ws"),
            ("VVIX", Decimal("112.0"), QUOTED_AT, "xenon_ws"),
            ("SPX", Decimal("7300.0"), QUOTED_AT, "xenon_ws"),
            ("HYG", Decimal("78.90"), QUOTED_AT, "xenon_ws"),
        ]
    )
    repo.conn.commit()


def _go_stale(repo) -> None:
    """EOD CRI/VCG snapshots for the last bar, and quotes past the max age."""
    cri_scanner.run(repo.conn, as_of=LAST_BAR)
    vcg_scanner.run(repo.conn, as_of=LAST_BAR)
    with repo.conn.cursor() as cur:
        # scanned_at defaults to now() and surfaces as scan_time: pin it.
        for table in ("cri_snapshots", "vcg_snapshots"):
            cur.execute(
                f"UPDATE uw_scan.{table} SET scanned_at = %s",
                (_dt.datetime(2026, 6, 11, 21, 0, tzinfo=_dt.timezone.utc),),
            )
        cur.execute(
            "UPDATE uw_scan.intraday_quote SET quoted_at = %s",
            (NOW - _dt.timedelta(days=2),),
        )
    repo.conn.commit()


def test_regime_gets_match_golden(frozen_clock, seeded_db_empty_cards):
    client = frozen_clock
    result = {"empty": _sweep(client)}
    _seed(seeded_db_empty_cards)
    result["seeded"] = _sweep(client)
    _go_stale(seeded_db_empty_cards)
    result["stale"] = _sweep(client)
    text = json.dumps(result, sort_keys=True, indent=1, default=str) + "\n"

    if os.environ.get("REGIME_GOLDEN_WRITE") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(text)
        pytest.skip("golden written")
    assert text == GOLDEN.read_text(), (
        "regime GET responses changed; diff against "
        "tests/integration/api/golden/regime_gets.json"
    )
