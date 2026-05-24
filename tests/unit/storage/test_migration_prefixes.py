from pathlib import Path

from scripts.check_migration_prefixes import (
    duplicate_prefixes,
    unexpected_duplicate_prefixes,
)


def test_duplicate_prefixes_detected(tmp_path: Path) -> None:
    (tmp_path / "001_first.sql").write_text("", encoding="utf-8")
    (tmp_path / "001_second.sql").write_text("", encoding="utf-8")
    assert duplicate_prefixes(tmp_path) == {
        "001": ["001_first.sql", "001_second.sql"]
    }


def test_duplicate_prefixes_accepts_unique_prefixes(tmp_path: Path) -> None:
    (tmp_path / "001_first.sql").write_text("", encoding="utf-8")
    (tmp_path / "002_second.sql").write_text("", encoding="utf-8")
    assert duplicate_prefixes(tmp_path) == {}


def test_unexpected_duplicate_prefixes_grandfathers_existing_prefixes(
    tmp_path: Path,
) -> None:
    (tmp_path / "037_gex_snapshots.sql").write_text("", encoding="utf-8")
    (tmp_path / "037_gold_macro_series.sql").write_text("", encoding="utf-8")
    assert unexpected_duplicate_prefixes(tmp_path) == {}


def test_unexpected_duplicate_prefixes_rejects_new_collisions(
    tmp_path: Path,
) -> None:
    (tmp_path / "099_first.sql").write_text("", encoding="utf-8")
    (tmp_path / "099_second.sql").write_text("", encoding="utf-8")
    assert unexpected_duplicate_prefixes(tmp_path) == {
        "099": ["099_first.sql", "099_second.sql"]
    }
