from __future__ import annotations

from datetime import date, datetime

from uw_scan.scanners import top_net_impact


class _Conn:
    def rollback(self) -> None:
        pass


class _Repo:
    _schema = "uw_scan"

    def __init__(self) -> None:
        self.conn = _Conn()
        self.finished: list[tuple[int, str]] = []

    def insert_scan_run(self, ticker: str, notes: str) -> int:
        return 123

    def finish_scan_run(self, run_id: int, status: str) -> None:
        self.finished.append((run_id, status))


def test_top_net_impact_uses_explicit_trading_date(monkeypatch):
    captured = {}

    def fake_fetch(client, repo, run_id, *, trading_date, limit):
        captured["trading_date"] = trading_date
        return [{"ticker": "SPY", "net_premium": 1}]

    class FakeSink:
        def __init__(self, conn, schema):
            pass

        def upsert_rows(self, rows):
            captured["rows"] = rows
            return len(rows)

    monkeypatch.setattr(top_net_impact.uw_source, "fetch_top_net_impact", fake_fetch)
    monkeypatch.setattr(top_net_impact, "TopNetImpactRepository", FakeSink)

    n = top_net_impact.run(object(), _Repo(), trading_date=date(2026, 6, 26), limit=40)

    assert n == 1
    assert captured["trading_date"] == date(2026, 6, 26)
    assert captured["rows"][0]["data_date"] == date(2026, 6, 26)


def test_top_net_impact_implicit_date_uses_et_market_date(monkeypatch):
    captured = {}

    class FakeDateTime:
        @classmethod
        def now(cls, tz):
            return datetime(2026, 6, 26, 10, 0, tzinfo=tz)

    def fake_fetch(client, repo, run_id, *, trading_date, limit):
        captured["trading_date"] = trading_date
        return [{"ticker": "SPY", "net_premium": 1}]

    class FakeSink:
        def __init__(self, conn, schema):
            pass

        def upsert_rows(self, rows):
            captured["rows"] = rows
            return len(rows)

    monkeypatch.setattr(top_net_impact, "datetime", FakeDateTime)
    monkeypatch.setattr(top_net_impact.uw_source, "fetch_top_net_impact", fake_fetch)
    monkeypatch.setattr(top_net_impact, "TopNetImpactRepository", FakeSink)

    top_net_impact.run(object(), _Repo(), trading_date=None, limit=40)

    assert captured["trading_date"] is None
    assert captured["rows"][0]["data_date"] == date(2026, 6, 26)
