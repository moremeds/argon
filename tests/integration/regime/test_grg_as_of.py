"""grg.run(as_of=...) must truncate its inputs, not restamp today's answer (E6).

vrp_macro_signal_daily accepted a snapshot_date it did not honour: backfilling
four dates produced four byte-identical rows. Any date-looped heal over a
non-date-aware writer produces lookahead-contaminated history that looks like a
successful backfill.
"""

from __future__ import annotations

from datetime import date, timedelta

from uw_scan.scanners import grg

# Synthetic deterministic series, same construction as tests/unit/test_grg_scoring.py
# — this exercises z-score math, so nothing here is (or claims to be) observed
# market data. grg_scoring.MIN_OBSERVATIONS is 70 aligned points and Z_WINDOW is
# 63, so a 3-row fixture cannot reach the compute at all; both as_of dates below
# must clear 70 or the scanner legitimately returns None for thin data.
#
# The row key is `date` and the VALUE key is `net_gex` — parse_greek_exposure_history
# emits both, and run_analysis reads r["net_gex"] (call_gex/put_gex alone would
# coerce to None and every row would be dropped as unaligned). Using `trade_date`
# would make the test pass while production raises KeyError.
_LAST = date(2026, 8, 12)


def _business_days(end: date, n: int) -> list[date]:
    out: list[date] = []
    d = end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


_DATES = _business_days(_LAST, 80)
# A varying body (so stddev > 0 and the z-score is defined) plus a final spike,
# so truncating one day off the tail visibly moves grg_z.
_SPY = [
    {"date": d, "net_gex": 100.0 + (i % 7) * 5.0 + (900.0 if d == _LAST else 0.0)}
    for i, d in enumerate(_DATES)
]
_TLT = [{"date": d, "net_gex": -40.0 + (i % 5) * 3.0} for i, d in enumerate(_DATES)]


def test_two_as_of_dates_produce_different_snapshots(
    seeded_db_empty_cards, monkeypatch
) -> None:
    repo = seeded_db_empty_cards
    monkeypatch.setattr(
        "uw_scan.sources.uw.fetch_greek_exposure_history",
        lambda client, r, run_id, t, timeframe="1Y": {"ticker": t},
    )
    monkeypatch.setattr(
        "uw_scan.scanners.grg.parse_greek_exposure_history",
        lambda body: _SPY if body["ticker"] == "SPY" else _TLT,
    )

    grg.run(client=object(), repo=repo, as_of=date(2026, 8, 11))
    grg.run(client=object(), repo=repo, as_of=date(2026, 8, 12))

    with repo.conn.cursor() as cur:
        # grg_z is a STORED generated column off payload->'signal'->>'grg_z';
        # data_date (not snapshot_date) is the date key on this table.
        cur.execute(
            f"SELECT data_date, grg_z FROM {repo._schema}.grg_snapshots "
            "ORDER BY data_date"
        )
        rows = cur.fetchall()

    # data_date is derived from the truncated series' tail, so this alone
    # catches a forgotten filter on spy_rows/tlt_rows.
    assert [r[0] for r in rows] == [date(2026, 8, 11), date(2026, 8, 12)]
    assert rows[0][1] != rows[1][1], (
        "identical values across as_of dates means the inputs were NOT truncated — "
        "this is the lookahead contamination that hit vrp_macro_signal_daily"
    )


def test_spot_and_flip_are_read_as_of(seeded_db_empty_cards) -> None:
    """The gamma series is not the only input — spot/flip must be dated too."""
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        for d, spot in ((date(2026, 8, 11), 600.0), (date(2026, 8, 12), 700.0)):
            cur.execute(
                f"INSERT INTO {repo._schema}.gex_snapshots "
                "(ticker, scanned_at, payload) VALUES ('SPY', %s, %s::jsonb)",
                (
                    d,
                    '{"spot": %s, "levels": {"gex_flip": {"strike": %s}}}'
                    % (spot, spot),
                ),
            )
        repo.conn.commit()

    early = repo.fetch_latest_gex(ticker="SPY", as_of=date(2026, 8, 11))
    late = repo.fetch_latest_gex(ticker="SPY", as_of=date(2026, 8, 12))
    assert early["spot"] == 600.0, "as_of must not see the next day's snapshot"
    assert late["spot"] == 700.0
