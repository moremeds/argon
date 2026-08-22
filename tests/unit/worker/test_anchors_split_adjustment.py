"""The valuation band's price series must be on today's share basis.

Fixtures are REAL rows from livewire's silver tier, read on 2026-08-21 and
frozen here. BKNG is a dividend payer that ran a 1-for-25 forward split on
2026-04-06; TSLA pays nothing and ran a 3-for-1 on 2022-08-25. Between them
they cover both halves of the adjustment and the case where they cancel.

Reproduce the fixtures:
  ssh macmini '~/market-warehouse/.venv/bin/python -c "
  import pyarrow.parquet as pq
  print(pq.read_table(\"/Volumes/DATA_LAKE/livewire/data-lake/silver/\"
        \"asset_class=equity/symbol=BKNG/1d.parquet\").to_pydict())"'
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from uw_scan.worker.jobs.fundamental_anchors import (
    _bronze_basis_refusal,
    fundamental_anchors,
    load_closes,
)

# (trade_date, close, price_adjustment_factor, split_volume_factor)
BKNG_SILVER = [
    (date(2026, 4, 2), 167.34929786852948, 0.03989969550420921, 25.0),
    (date(2026, 4, 6), 175.7481837721655, 0.9974923876052302, 1.0),
    (date(2026, 8, 20), 209.87, 1.0, 1.0),
]
TSLA_SILVER = [
    (date(2021, 6, 11), 203.29666666666665, 0.3333333333333333, 3.0),
    (date(2022, 8, 19), 296.6666666666667, 0.3333333333333333, 3.0),
]
# The raw as-traded closes those silver rows were derived from.
BKNG_RAW = {date(2026, 4, 2): 4194.25, date(2026, 4, 6): 176.19}


def _write(root: Path, ticker: str, rows: list[tuple], columns: list[str]) -> None:
    d = root / f"symbol={ticker}"
    d.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {c: [r[i] for r in rows] for i, c in enumerate(columns)},
            schema=pa.schema(
                [(columns[0], pa.date32())]
                + [(c, pa.float64()) for c in columns[1:]]
            ),
        ),
        d / "1d.parquet",
    )


SILVER_COLS = ["trade_date", "close", "price_adjustment_factor", "split_volume_factor"]


@pytest.fixture
def silver(tmp_path: Path) -> Path:
    root = tmp_path / "silver"
    _write(root, "BKNG", BKNG_SILVER, SILVER_COLS)
    _write(root, "TSLA", TSLA_SILVER, SILVER_COLS)
    return root


def test_silver_close_is_divided_back_to_a_split_only_basis(silver: Path) -> None:
    """Splits stay adjusted; the dividend half is undone.

    Silver's own close on 2026-04-02 is 167.35 — that is the raw 4194.25 put on
    today's basis by BOTH the 25.0 split and BKNG's dividends since. Only the
    split belongs in a market cap: nothing restates a share count for a dividend,
    so leaving it in understates every historical market cap on a payer and
    biases the whole band cheap. 4194.25 / 25 is the number we want.
    """
    got = dict(load_closes(silver, ["BKNG"], adjusted=True)["BKNG"])

    assert got[date(2026, 4, 2)] == pytest.approx(BKNG_RAW[date(2026, 4, 2)] / 25.0)
    assert got[date(2026, 4, 2)] == pytest.approx(167.77)
    assert got[date(2026, 4, 2)] > 167.34929786852948  # the dividend, undone

    # Post-split there is no split left to undo, so it is the raw close again.
    assert got[date(2026, 4, 6)] == pytest.approx(BKNG_RAW[date(2026, 4, 6)])

    # And the series does not cliff across the split the way a raw one does:
    # 4194.25 -> 176.19 is a 24x drop, 167.77 -> 176.19 is a 5% gain.
    assert 0.9 < got[date(2026, 4, 6)] / got[date(2026, 4, 2)] < 1.1


def test_a_name_that_pays_no_dividend_keeps_silvers_close(silver: Path) -> None:
    """TSLA's factors are exact reciprocals, so nothing is divided out."""
    got = dict(load_closes(silver, ["TSLA"], adjusted=True)["TSLA"])

    assert got[date(2021, 6, 11)] == pytest.approx(203.29666666666665)
    # 609.89 was the raw close that day; 3-for-1 makes it 203.30 on today's basis.
    assert got[date(2021, 6, 11)] == pytest.approx(609.89 / 3, rel=1e-4)


def test_bronze_is_read_verbatim(tmp_path: Path) -> None:
    """`adjusted=False` applies nothing — the caller owns proving it is safe."""
    root = tmp_path / "bronze"
    _write(
        root,
        "BKNG",
        [(d, BKNG_RAW[d]) for d in sorted(BKNG_RAW)],
        ["trade_date", "close"],
    )

    got = dict(load_closes(root, ["BKNG"], adjusted=False)["BKNG"])

    assert got == BKNG_RAW


def test_a_symbol_with_no_artifact_is_absent(silver: Path) -> None:
    """Livewire publishes no silver for a symbol whose bronze basis is unknown.

    18 of the 450-name universe on 2026-08-21, HON and MSTR among them. The
    reader must leave them out rather than invent a series — the caller decides
    whether bronze is provably equivalent for them.
    """
    got = load_closes(silver, ["BKNG", "HON"], adjusted=True)

    assert "HON" not in got
    assert "BKNG" in got


def _panel(period_ends: list[str]) -> dict:
    return {"filing_dates": {p: f"{p}T00:00:00Z" for p in period_ends}}


class TestBronzeBasisRefusal:
    """The guard deciding whether an unadjustable bronze series may be used."""

    PERIODS = ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"]

    def _refuse(self, events, *, ingested=True):
        return _bronze_basis_refusal(
            _panel(self.PERIODS), self.PERIODS, events, ingested=ingested
        )

    def test_a_split_inside_the_window_disqualifies_bronze(self) -> None:
        """CXAI's 50-for-1 on 2026-08-18 left buy_below at $0.107 vs a $4.59 spot."""
        assert "split inside the window" in self._refuse([(date(2024, 8, 8), 10.0)])

    def test_a_split_before_the_window_is_harmless(self) -> None:
        """CMCSA last split in 2017; its window starts 2021, so any consistent
        basis IS today's basis and bronze prices it correctly."""
        assert self._refuse([(date(2017, 2, 21), 2.0)]) is None

    def test_the_boundary_date_counts_as_inside(self) -> None:
        assert self._refuse([(date(2021, 12, 31), 2.0)]) is not None

    def test_a_clean_record_with_no_splits_permits_bronze(self) -> None:
        """Ingested and empty is evidence of no split — the one case that passes."""
        assert self._refuse([]) is None

    def test_a_name_never_ingested_is_refused_even_with_no_events(self) -> None:
        """The 2026-08-22 production state for 15 of the 18 silver-less names:
        zero rows because the ingest covered 137 of 450, not because they never
        split. AIG, CMCSA, ECL and HON were all banded off unadjusted bronze."""
        reason = self._refuse([], ingested=False)
        assert reason is not None
        assert "never having asked" in reason

    def test_never_ingested_outranks_a_clean_looking_window(self) -> None:
        """An out-of-window split must not launder an unverified name into a band."""
        assert (
            self._refuse([(date(2017, 2, 21), 2.0)], ingested=False) is not None
        )

    def test_no_periods_is_safe_for_an_ingested_name(self) -> None:
        assert (
            _bronze_basis_refusal(
                {"filing_dates": {}}, [], [(date.today(), 2.0)], ingested=True
            )
            is None
        )


class TestMissingSilverTier:
    """An absent tier is a mount error, and it must not degrade to bronze.

    `load_closes` skips a symbol whose parquet is missing, so an absent tier
    used to yield an empty dict, put the whole universe on the bronze fallback,
    and reinstate the split-basis bug without raising anything. The guard runs
    before any DB work, which is why `conn=None` reaches it here.
    """

    def _call(self, silver: Path, tmp_path: Path) -> None:
        fundamental_anchors(
            conn=None,  # type: ignore[arg-type]
            lake_root=tmp_path,
            silver_root=silver,
            fx_root=tmp_path,
        )

    def test_absent_tier_refuses_the_run(self, tmp_path: Path) -> None:
        with pytest.raises(RuntimeError, match="no silver tier"):
            self._call(tmp_path / "silver", tmp_path)

    def test_a_file_where_the_tier_should_be_refuses_too(self, tmp_path: Path) -> None:
        stray = tmp_path / "silver"
        stray.write_text("")
        with pytest.raises(RuntimeError, match="no silver tier"):
            self._call(stray, tmp_path)

    def test_a_present_tier_passes_the_guard(self, tmp_path: Path) -> None:
        silver = tmp_path / "silver"
        silver.mkdir()
        # Past the guard it reaches the DB, and conn=None is what proves it got
        # there — the guard is the only thing that can raise RuntimeError first.
        with pytest.raises(AttributeError):
            self._call(silver, tmp_path)
