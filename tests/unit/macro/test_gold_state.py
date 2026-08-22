"""The gold evidence manifest: every declared input, present or explained.

The defect under test is a manifest that named four inputs while the orchestrator read
ten and passed two more as deliberately empty. Naming four of twelve is worse than
naming none, because it reads as a complete audit trail.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from uw_scan.macro.gold import (
    GOLD_INPUTS,
    GoldInput,
    InputReading,
    evidence_manifest,
    read_gold_inputs,
)

AS_OF = date(2026, 8, 14)
STAMP = datetime(2026, 8, 15, tzinfo=UTC)

#: The four the old manifest named, kept as a literal so the test states the gap.
LEGACY_MANIFEST_KEYS = {"DFII10", "GLD_CLOSE", "T5YIFR", "CPIAUCSL"}


class FakeRepo:
    """Answers every declared read with one plausible row, or nothing when asked.

    Every method REQUIRES ``as_of_max``. A fake with a wider signature than the real
    repository is how a missing retrieval bound stays invisible: the registry could stop
    passing it and these tests would still pass, while a replay silently read vintages
    published after the instant it describes.
    """

    def __init__(self, *, empty: set[str] | None = None) -> None:
        self.empty = empty or set()
        self.calls: list[str] = []
        self.as_of_max_seen: list[datetime] = []

    def _rows(self, key: str, period_field: str, as_of_max, **extra):
        self.calls.append(key)
        assert as_of_max is not None, (
            f"{key} was read without an as_of_max bound; the row returned may have been "
            "retrieved after the instant the replay describes"
        )
        self.as_of_max_seen.append(as_of_max)
        if key in self.empty:
            return []
        return [{period_field: AS_OF, "as_of": STAMP, **extra}]

    def fetch_macro_series_daily(self, series_id, *, to_date=None, as_of_max=None):
        return self._rows(series_id, "obs_date", as_of_max, value=Decimal("100"))

    def fetch_macro_series_monthly(self, series_id, *, to_month=None, as_of_max=None):
        return self._rows(series_id, "obs_month", as_of_max, value=Decimal("100"))

    def fetch_cb_gold_reserves_monthly(self, *, from_month=None, as_of_max=None):
        return self._rows(
            "cb_gold_reserves_monthly",
            "obs_month",
            as_of_max,
            country_iso3="CHN",
            reserves_t=Decimal("2280"),
            bucket="official",
        )

    def fetch_etf_holdings_daily(self, ticker, *, from_date=None, as_of_max=None):
        return self._rows(
            "etf_holdings_daily",
            "obs_date",
            as_of_max,
            holdings_oz=Decimal("33402755.16"),
        )

    def fetch_etf_flows_daily(
        self, ticker, *, from_date=None, to_date=None, as_of_max=None
    ):
        return self._rows(
            "etf_flows_daily", "obs_date", as_of_max, share_change=Decimal("100000")
        )

    def fetch_exchange_inventory_daily(
        self, exchange, *, from_date=None, as_of_max=None
    ):
        key = (
            "lbma_inventory_daily" if exchange == "LBMA" else "exchange_inventory_daily"
        )
        return self._rows(key, "obs_date", as_of_max, registered_oz=Decimal("18000000"))

    def fetch_cot_gold_weekly(
        self, *, from_release_date=None, to_release_date=None, as_of_max=None
    ):
        return self._rows("cot_gold_weekly", "release_date", as_of_max, mm_net=137662)

    def fetch_uw_gold_options_daily(self, ticker, *, from_date=None, as_of_max=None):
        return self._rows(
            "uw_gold_options_daily",
            "obs_date",
            as_of_max,
            skew_25d_30d=Decimal("0.0182"),
        )


class TestTheRegistryIsTheDeclaration:
    def test_every_declared_input_reaches_the_manifest(self) -> None:
        """The invariant. Nothing declared may be silently absent from the record."""
        manifest = evidence_manifest(read_gold_inputs(FakeRepo(), AS_OF))
        assert set(manifest) == {item.key for item in GOLD_INPUTS}

    def test_the_manifest_is_materially_wider_than_the_one_it_replaces(self) -> None:
        manifest = evidence_manifest(read_gold_inputs(FakeRepo(), AS_OF))
        assert LEGACY_MANIFEST_KEYS < set(manifest)
        # Sixteen, not twelve: the first registry missed four reads that sit below the
        # lens calls, in the section assembling the UI payload.
        assert len(manifest) >= 16

    def test_an_input_that_is_neither_read_nor_explained_is_refused(self) -> None:
        """The registry cannot express the gap it exists to eliminate."""
        with pytest.raises(ValueError, match="exactly one of read/not_read_reason"):
            GoldInput(
                key="gpr",
                lens=("L1",),
                causal_role="curve",
                source="gpr",
                period_field="obs_date",
            )

    def test_an_input_cannot_be_both_read_and_explained_away(self) -> None:
        with pytest.raises(ValueError, match="exactly one of read/not_read_reason"):
            GoldInput(
                key="gpr",
                lens=("L1",),
                causal_role="curve",
                source="gpr",
                period_field="obs_date",
                read=lambda repo, as_of: [],
                not_read_reason="also explained",
            )

    def test_a_reading_absent_from_the_map_is_refused(self) -> None:
        readings = read_gold_inputs(FakeRepo(), AS_OF)
        del readings["cot_gold_weekly"]
        with pytest.raises(ValueError, match="cot_gold_weekly"):
            evidence_manifest(readings)


class TestOmissionsAreEvidence:
    def test_a_source_with_no_rows_carries_a_reason_not_silence(self) -> None:
        manifest = evidence_manifest(
            read_gold_inputs(FakeRepo(empty={"cot_gold_weekly"}), AS_OF)
        )
        entry = manifest["cot_gold_weekly"]
        assert entry["row_count"] == 0
        assert entry["obs_date"] is None
        assert entry["omission_reason"]

    def test_an_empty_source_does_not_borrow_a_neighbour(self) -> None:
        manifest = evidence_manifest(
            read_gold_inputs(FakeRepo(empty={"cot_gold_weekly"}), AS_OF)
        )
        assert (
            "substituting a neighbour" in manifest["cot_gold_weekly"]["omission_reason"]
        )

    @pytest.mark.parametrize("key", ["fx", "spx"])
    def test_the_never_read_inputs_are_declared_with_a_reason(self, key: str) -> None:
        """An empty list reaching a lens is indistinguishable from a flat input.

        ``fx_rows=[]`` and ``spx_series=[]`` are passed to the lens functions today. The
        lens output cannot tell "no FX leg is ingested" from "the currency did not move",
        so the distinction has to be carried by the manifest or it is lost.
        """
        manifest = evidence_manifest(read_gold_inputs(FakeRepo(), AS_OF))
        assert manifest[key]["omission_reason"]
        assert manifest[key]["required"] is False

    def test_a_declared_not_read_input_is_never_queried(self) -> None:
        repo = FakeRepo()
        read_gold_inputs(repo, AS_OF)
        assert "fx" not in repo.calls
        assert "spx" not in repo.calls

    def test_a_present_input_carries_no_omission_reason(self) -> None:
        manifest = evidence_manifest(read_gold_inputs(FakeRepo(), AS_OF))
        assert manifest["GLD_CLOSE"]["omission_reason"] is None
        assert manifest["GLD_CLOSE"]["obs_date"] == AS_OF.isoformat()


class TestABrokenReadIsNotAnEmptyRead:
    def test_a_raising_read_propagates(self) -> None:
        """A broken query must not be reported as a source that published nothing.

        That is the same conflation the four-entry manifest made, one level down: the
        record would say "no rows" and be wrong about why.
        """

        class Broken(FakeRepo):
            def fetch_cot_gold_weekly(self, **kw):
                raise RuntimeError("relation does not exist")

        with pytest.raises(RuntimeError, match="relation does not exist"):
            read_gold_inputs(Broken(), AS_OF)


class TestManifestShape:
    def test_each_entry_names_its_lens_and_role(self) -> None:
        manifest = evidence_manifest(read_gold_inputs(FakeRepo(), AS_OF))
        entry = manifest["cb_gold_reserves_monthly"]
        assert entry["lens"] == ["L1"]
        assert entry["causal_role"] == "positioning"
        assert entry["source"] == "wgc"

    def test_the_price_is_read_by_all_three_lenses(self) -> None:
        manifest = evidence_manifest(read_gold_inputs(FakeRepo(), AS_OF))
        assert manifest["GLD_CLOSE"]["lens"] == ["L1", "L2", "L3"]

    def test_monthly_series_report_their_month_as_the_period(self) -> None:
        # These tables disagree on the column: obs_date, obs_month and release_date all
        # appear, and a manifest that looked for one of them would report None for the
        # other two while the rows were right there.
        manifest = evidence_manifest(read_gold_inputs(FakeRepo(), AS_OF))
        assert manifest["CPIAUCSL"]["obs_date"] == AS_OF.isoformat()
        assert manifest["cot_gold_weekly"]["obs_date"] == AS_OF.isoformat()

    def test_a_reading_reports_presence_honestly(self) -> None:
        readings = read_gold_inputs(FakeRepo(empty={"M2SL"}), AS_OF)
        assert readings["GLD_CLOSE"].rows
        assert readings["GLD_CLOSE"].omission_reason is None
        # Absent AND explained -- the two halves that must always travel together.
        assert not readings["M2SL"].rows
        assert readings["M2SL"].omission_reason
        assert isinstance(readings["M2SL"], InputReading)


class TestEveryGoldTableIsAppendOnly:
    """The property that makes a gold row quotable as evidence at all.

    Part A refused to source ``supply``, ``positioning`` and ``plumbing`` from
    ``rates_treasury_auctions`` and friends because those key on
    ``(series_id, obs_date, source)`` and UPDATE on conflict -- a value read back may
    already have been overwritten, and promoting one would launder a mutated number into
    the evidence store. Gold's tables are the opposite shape, and this test is what keeps
    them that way: they key on ``(..., as_of)`` and insert DO NOTHING, so each retrieval
    is its own immutable row.

    ``wgc_etf_monthly`` in the same module DOES update on conflict. No declared input
    reads it, and the assertion below is what would notice if one started to.
    """

    STORAGE = (
        Path(__file__).parents[3] / "src" / "uw_scan" / "storage",
        ("gold.py", "gold_etf.py"),
    )

    @staticmethod
    def _conflict_clauses() -> dict[str, list[str]]:
        """Every INSERT's ON CONFLICT clause, per table.

        Chunk-split rather than one regex: the SQL literals differ enough in shape
        (executemany vs execute, RETURNING or not) that a single pattern matched some
        and silently skipped others -- and a check that silently covers nothing is worse
        than no check, which is the same defect this whole module is about.
        """
        out: dict[str, list[str]] = {}
        root, names = TestEveryGoldTableIsAppendOnly.STORAGE
        # Two prefixes in the same package: gold.py writes a literal ``uw_scan.`` and
        # gold_etf.py interpolates ``{self._schema}``. Matching only one covered half
        # the tables and reported the other half as "no INSERT found".
        marker = re.compile(r"INSERT INTO (?:\{self\._schema\}|uw_scan)\.(\w+)")
        for name in names:
            text = (root / name).read_text(encoding="utf-8")
            for match in marker.finditer(text):
                statement = text[match.end() :].split('"""')[0]
                conflict = re.search(r"ON CONFLICT(.*)", statement, re.S)
                out.setdefault(match.group(1), []).append(
                    conflict.group(1) if conflict else ""
                )
        return out

    def test_the_declared_tables_are_the_ones_the_lenses_read(self) -> None:
        declared = {item.table for item in GOLD_INPUTS if item.table}
        assert declared == {
            "macro_series_daily",
            "macro_series_monthly",
            "cb_gold_reserves_monthly",
            "etf_holdings_daily",
            "etf_flows_daily",
            "exchange_inventory_daily",
            "cot_gold_weekly",
            "uw_gold_options_daily",
        }

    @pytest.mark.parametrize(
        "table", sorted({item.table for item in GOLD_INPUTS if item.table})
    )
    def test_each_read_table_inserts_do_nothing_keyed_on_as_of(
        self, table: str
    ) -> None:
        clauses = self._conflict_clauses().get(table)
        assert clauses, (
            f"no INSERT found for {table}; the check silently covered nothing"
        )
        for clause in clauses:
            assert "DO NOTHING" in clause, (
                f"{table} updates on conflict, so a value read back may already have "
                "been overwritten. A gold lens must not quote it as evidence."
            )
            assert "as_of" in clause, (
                f"{table} does not key on as_of, so a re-fetch replaces the earlier "
                "retrieval instead of accruing beside it."
            )

    def test_the_mutable_neighbour_is_not_declared(self) -> None:
        # wgc_etf_monthly updates on conflict. Asserted so the exclusion is deliberate
        # rather than an accident of which fetcher happened to be wired up.
        assert "wgc_etf_monthly" not in {item.table for item in GOLD_INPUTS}
        clauses = self._conflict_clauses().get("wgc_etf_monthly") or []
        assert clauses and all("DO UPDATE" in clause for clause in clauses)
