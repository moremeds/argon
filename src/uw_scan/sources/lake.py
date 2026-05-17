"""Parquet reader for ~/market-warehouse/data-lake.

Used by the nightly vol_index_lake_sync job. No business logic — pure I/O.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

VOL_INDEX_FILENAME = "1d.parquet"


def list_vol_index_symbols(root: Path) -> list[str]:
    """Return all symbols under root/symbol=<TICKER>/1d.parquet."""
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


def read_vol_index_parquet(
    root: Path,
    symbol: str,
    *,
    since: date | None = None,
) -> list[dict]:
    """Read symbol=<S>/1d.parquet → list[dict] with normalized columns.

    Output dicts contain: symbol, trade_date, open, high, low, close,
    adj_close, volume. Rows are sorted by trade_date ascending.
    """
    path = root / f"symbol={symbol}" / VOL_INDEX_FILENAME
    if not path.exists():
        return []
    table = pq.read_table(path)
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
