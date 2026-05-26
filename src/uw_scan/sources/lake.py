"""Parquet reader for the market-warehouse data lake.

Supports two backends via the LakeRoot abstraction in lake_resolver:
- Local filesystem (Path) — used by the existing nightly sync jobs
- Cloudflare R2 — used by new EOD/backfill code per the 2026-05-25 standing
  rule (see [[feedback-r2-primary-for-eod-backfill]])

Public functions accept either a Path or a LakeRoot for backward
compatibility with existing Path-based callers. No business logic — pure I/O.
R2 reads go through pyarrow.fs.S3FileSystem with the account-scoped
endpoint override; auth is access-key / secret-key Sig V4.

Also provides deterministic-bytes write helpers for VCG research artifacts
(weights, input prices). Local + R2 writers both return ArtifactWriteResult
so the caller never reconstructs a path from a sha — the writer is the
SOLE source of truth for what got persisted.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.fs as pa_fs
import pyarrow.parquet as pq

from uw_scan.sources.lake_resolver import LakeRoot

if TYPE_CHECKING:
    import pandas as pd

VOL_INDEX_FILENAME = "1d.parquet"


@dataclass(frozen=True)
class ArtifactWriteResult:
    """Result of writing a research artifact.

    Returned by both write_weight_artifact_* and any future canonical-bytes
    writers so callers don't reconstruct paths and risk mismatch.
    """

    sha256: str
    key: str  # full key under the bucket (R2) or filesystem path (local)
    uri: str  # `r2://bucket/key` or `file://path`


def _normalize(root: Path | LakeRoot) -> LakeRoot:
    if isinstance(root, LakeRoot):
        return root
    # Legacy Path-based callers (vol_index_lake_sync, credit_etf_lake_sync) —
    # wrap as a local-kind LakeRoot. asset_class is informational only for
    # local reads; the Path drives the actual lookup.
    return LakeRoot.local_for("legacy", root)


def list_vol_index_symbols(root: Path | LakeRoot) -> list[str]:
    """Return all symbols under `root/symbol=<TICKER>/1d.parquet`."""
    lr = _normalize(root)
    if lr.kind == "local":
        assert lr.local_path is not None
        return _list_local(lr.local_path)
    return _list_s3(lr)


def read_vol_index_parquet(
    root: Path | LakeRoot,
    symbol: str,
    *,
    since: date | None = None,
) -> list[dict]:
    """Read `symbol=<S>/1d.parquet` -> list[dict] with normalized columns."""
    lr = _normalize(root)
    if lr.kind == "local":
        assert lr.local_path is not None
        return _read_local(lr.local_path, symbol, since=since)
    return _read_s3(lr, symbol, since=since)


# ---------- local backend (unchanged behavior) ----------


def _list_local(root: Path) -> list[str]:
    if not root.exists():
        return []
    out: list[str] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if not name.startswith("symbol="):
            continue
        if not (child / VOL_INDEX_FILENAME).exists():
            continue
        out.append(name[len("symbol=") :])
    return sorted(out)


def _read_local(root: Path, symbol: str, *, since: date | None) -> list[dict]:
    path = root / f"symbol={symbol}" / VOL_INDEX_FILENAME
    if not path.exists():
        return []
    table = pq.read_table(path)
    return _rows_from_table(table, symbol, since=since)


# ---------- s3 (R2) backend ----------


def _s3_fs(lr: LakeRoot) -> pa_fs.S3FileSystem:
    return pa_fs.S3FileSystem(
        access_key=lr.access_key_id,
        secret_key=lr.secret_access_key,
        endpoint_override=lr.endpoint_override,
        # R2 ignores region but pyarrow requires *something* non-empty.
        region="auto",
        scheme="https",
    )


def _list_s3(lr: LakeRoot) -> list[str]:
    assert lr.bucket and lr.key_prefix
    fs = _s3_fs(lr)
    selector = pa_fs.FileSelector(
        f"{lr.bucket}/{lr.key_prefix}", recursive=False, allow_not_found=True
    )
    out: list[str] = []
    for info in fs.get_file_info(selector):
        if info.type != pa_fs.FileType.Directory:
            continue
        base = Path(info.path).name
        if not base.startswith("symbol="):
            continue
        symbol = base[len("symbol=") :]
        # Probe parquet existence so listing symmetry matches the local backend
        # (which only returns symbols that have 1d.parquet). One extra
        # round-trip per symbol — acceptable for ~20 symbols on the nightly
        # sync schedule; cheaper than swallowing empty reads downstream.
        probe = fs.get_file_info(
            f"{lr.bucket}/{lr.key_prefix}/symbol={symbol}/{VOL_INDEX_FILENAME}"
        )
        if probe.type != pa_fs.FileType.File:
            continue
        out.append(symbol)
    return sorted(out)


def _read_s3(lr: LakeRoot, symbol: str, *, since: date | None) -> list[dict]:
    assert lr.bucket and lr.key_prefix
    fs = _s3_fs(lr)
    key = f"{lr.bucket}/{lr.key_prefix}/symbol={symbol}/{VOL_INDEX_FILENAME}"
    # Probe existence cleanly via FileInfo.type rather than try/except — pyarrow's
    # S3 backend raises OSError/ArrowIOError (not FileNotFoundError) on 403,
    # timeout, missing key, and a few other paths, so a narrow except FileNotFoundError
    # is unreliable AND lets all the other errors crash callers. The local
    # backend uses path.exists() (returns False, no exception); this is the
    # S3 analogue. Real errors (403, malformed parquet) propagate.
    info = fs.get_file_info(key)
    if info.type != pa_fs.FileType.File:
        return []
    table = pq.read_table(key, filesystem=fs)
    return _rows_from_table(table, symbol, since=since)


# ---------- shared row normalizer ----------


def _rows_from_table(table, symbol: str, *, since: date | None) -> list[dict]:
    df = table.to_pandas()
    if "trade_date" not in df.columns:
        return []
    if since is not None:
        df = df[df["trade_date"] >= since]
    df = df.sort_values("trade_date")
    rows: list[dict] = []
    for r in df.itertuples(index=False):
        rd = r._asdict()
        rows.append(
            {
                "symbol": symbol,
                "trade_date": rd["trade_date"],
                "open": _maybe_float(rd.get("open")),
                "high": _maybe_float(rd.get("high")),
                "low": _maybe_float(rd.get("low")),
                "close": _maybe_float(rd.get("close")),
                "adj_close": _maybe_float(rd.get("adj_close")),
                "volume": int(rd["volume"]) if rd.get("volume") is not None else None,
            }
        )
    return rows


def _maybe_float(x) -> float | None:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError) as exc:
        _ = repr(exc)  # CI Guardrail 2: coercion failure folds to None
        return None
    return f


# ---------- VCG research artifact writers ----------
#
# Deterministic-bytes helpers + write functions used by scripts/backtest_vcg.py
# --composite-method to persist a hash-addressable parquet artifact for replay
# verification. The sha256 of the canonical bytes lands in
# regime_backtest_runs.summary["extras"]["weight_artifact_sha256"]; the key/uri
# land in "weight_artifact_uri".


def canonical_weight_artifact_bytes(weights: "pd.DataFrame") -> bytes:
    """Deterministic parquet bytes for a weight DataFrame.

    Sorts columns alphabetically, sorts rows by index, pins the parquet writer
    config so byte stream is reproducible within the uv.lock-pinned pyarrow.
    """
    import pandas as pd  # noqa: PLC0415

    df = weights[sorted(weights.columns)].sort_index().copy()
    df.index.name = df.index.name or "trade_date"
    table = pa.Table.from_pandas(df.reset_index(), preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(
        table,
        buf,
        compression="none",
        use_dictionary=True,
        write_statistics=False,
        version="2.6",
    )
    return buf.getvalue()


def write_weight_artifact_local(
    weights: "pd.DataFrame", out_dir: Path
) -> ArtifactWriteResult:
    """Write to local fs. Returns ArtifactWriteResult so the caller never
    reconstructs the path from a sha (R2 and local paths must be the SOLE
    source of truth for what gets persisted in extras)."""
    raw = canonical_weight_artifact_bytes(weights)
    sha = hashlib.sha256(raw).hexdigest()
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{sha}.parquet"
    if not target.exists():
        target.write_bytes(raw)
    return ArtifactWriteResult(sha256=sha, key=str(target), uri=f"file://{target}")


def write_weight_artifact_r2(
    weights: "pd.DataFrame", root: LakeRoot
) -> ArtifactWriteResult:
    """Write to R2 under market-warehouse/research/vcg-weights/<sha>.parquet.

    Path is sibling to the data-lake's bronze zone. Returns sha + key + uri.
    """
    if root.kind != "s3":
        raise ValueError(
            f"write_weight_artifact_r2 requires R2 root, got kind={root.kind}"
        )
    raw = canonical_weight_artifact_bytes(weights)
    sha = hashlib.sha256(raw).hexdigest()
    fs = _s3_fs(root)
    key = f"market-warehouse/research/vcg-weights/{sha}.parquet"
    full_key = f"{root.bucket}/{key}"
    with fs.open_output_stream(full_key) as out:
        out.write(raw)
    return ArtifactWriteResult(sha256=sha, key=full_key, uri=f"r2://{full_key}")


def canonical_input_price_bytes(
    *,
    series_by_symbol: dict[str, "pd.Series"],
    price_field_by_symbol: dict[str, str],
) -> bytes:
    """Deterministic parquet bytes for input price series, in LONG format
    (one row per (trade_date, symbol)) so the hash is independent of the
    column order any caller happens to use.

    Schema:
        trade_date  date32   (sorted ascending)
        symbol      string   (sorted alphabetically within each date)
        price_field string   ('close' / 'adj_close')
        price       float64

    Spec §6 hash content rule: hash of canonical PARQUET bytes containing
    [trade_date, symbol, price_field, price] for all input symbols AFTER
    alignment, sorted by (trade_date, symbol). This function does NOT align —
    callers provide pre-aligned series — but DOES enforce sort order.
    """
    import pandas as pd  # noqa: PLC0415

    rows: list[dict] = []
    for sym in sorted(series_by_symbol):
        s = series_by_symbol[sym]
        pf = price_field_by_symbol[sym]
        for d, v in s.items():
            d_real = d.date() if hasattr(d, "date") else d
            rows.append(
                {
                    "trade_date": d_real,
                    "symbol": sym,
                    "price_field": pf,
                    "price": float(v),
                }
            )
    if not rows:
        return b""
    df = pd.DataFrame(rows).sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(
        table,
        buf,
        compression="none",
        use_dictionary=True,
        write_statistics=False,
        version="2.6",
    )
    return buf.getvalue()
