"""Unit tests for the local-filesystem branch of write_weight_artifact and
the canonical-bytes helpers. R2 path is exercised by an opt-in live test
in tests/integration/."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from uw_scan.sources.lake import (
    ArtifactWriteResult,
    canonical_input_price_bytes,
    canonical_weight_artifact_bytes,
    write_weight_artifact_local,
)


def test_canonical_bytes_are_deterministic(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {"HYG": [0.34, 0.33], "JNK": [0.33, 0.34], "LQD": [0.33, 0.33]},
        index=pd.bdate_range("2024-01-01", periods=2),
    )
    b1 = canonical_weight_artifact_bytes(df)
    b2 = canonical_weight_artifact_bytes(df)
    assert b1 == b2  # byte-identical for identical input

    df2 = df[["LQD", "HYG", "JNK"]]  # different column order
    b3 = canonical_weight_artifact_bytes(df2)
    assert b1 == b3  # canonical orders columns alphabetically


def test_write_weight_artifact_local_returns_artifact_write_result(
    tmp_path: Path,
) -> None:
    df = pd.DataFrame(
        {"HYG": [0.34], "JNK": [0.33], "LQD": [0.33]},
        index=pd.bdate_range("2024-01-01", periods=1),
    )
    result = write_weight_artifact_local(df, tmp_path / "vcg-weights")
    assert isinstance(result, ArtifactWriteResult)
    artifact = tmp_path / "vcg-weights" / f"{result.sha256}.parquet"
    assert artifact.exists()
    assert (
        result.sha256 == hashlib.sha256(canonical_weight_artifact_bytes(df)).hexdigest()
    )
    assert result.uri == f"file://{artifact}"
    assert result.key == str(artifact)


def test_write_weight_artifact_local_is_idempotent(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {"HYG": [0.34], "JNK": [0.33], "LQD": [0.33]},
        index=pd.bdate_range("2024-01-01", periods=1),
    )
    out_dir = tmp_path / "vcg-weights"
    r1 = write_weight_artifact_local(df, out_dir)
    mtime_before = (out_dir / f"{r1.sha256}.parquet").stat().st_mtime_ns
    r2 = write_weight_artifact_local(df, out_dir)
    mtime_after = (out_dir / f"{r1.sha256}.parquet").stat().st_mtime_ns
    assert r1 == r2
    # File already existed - writer should NOT touch it (mtime unchanged)
    assert mtime_before == mtime_after


def test_canonical_input_price_bytes_long_format_deterministic() -> None:
    s_hyg = pd.Series(
        {
            pd.Timestamp("2024-01-02").date(): 100.0,
            pd.Timestamp("2024-01-03").date(): 101.0,
        }
    )
    s_vix = pd.Series(
        {
            pd.Timestamp("2024-01-02").date(): 15.0,
            pd.Timestamp("2024-01-03").date(): 16.0,
        }
    )
    b1 = canonical_input_price_bytes(
        series_by_symbol={"HYG": s_hyg, "VIX": s_vix},
        price_field_by_symbol={"HYG": "adj_close", "VIX": "close"},
    )
    # Reversed insertion order — should produce IDENTICAL bytes (canonical sort)
    b2 = canonical_input_price_bytes(
        series_by_symbol={"VIX": s_vix, "HYG": s_hyg},
        price_field_by_symbol={"VIX": "close", "HYG": "adj_close"},
    )
    assert b1 == b2


def test_canonical_input_price_bytes_empty_returns_empty() -> None:
    b = canonical_input_price_bytes(series_by_symbol={}, price_field_by_symbol={})
    assert b == b""
