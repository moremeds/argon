"""Parquet reader for the market-warehouse data lake.

Supports two backends via the LakeRoot abstraction in lake_resolver:
- Local filesystem (Path) — used by the existing nightly sync jobs
- Cloudflare R2 — used by new EOD/backfill code per the 2026-05-25 standing
  rule (see [[feedback-r2-primary-for-eod-backfill]])

Public functions accept either a Path or a LakeRoot for backward
compatibility with existing Path-based callers. No business logic — pure I/O.
R2 reads go through pyarrow.fs.S3FileSystem with the account-scoped
endpoint override; auth is access-key / secret-key Sig V4.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow.fs as pa_fs
import pyarrow.parquet as pq

from uw_scan.sources.lake_resolver import LakeRoot

VOL_INDEX_FILENAME = "1d.parquet"


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
