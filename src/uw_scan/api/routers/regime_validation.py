"""Read-only endpoints for the /regime/validation sub-page + guidance.

GET /api/regime/validation — returns the warm-store backtest markdown +
  CSV row count + a hand-curated OOS summary loaded from
  docs/research/regime/oos-summary.json.

GET /api/regime/guidance — added in a follow-on commit (T9). Returns the
  active regime-state guidance rule selected from
  docs/research/regime/guidance.md based on the current CRI snapshot.
"""

from __future__ import annotations

import csv
from pathlib import Path

from fastapi import APIRouter, HTTPException

from uw_scan.api.models.regime_validation import (
    OosSummary,
    ValidationResponse,
)

router = APIRouter(prefix="/regime", tags=["regime"])

# src/uw_scan/api/routers/regime_validation.py
# parents[0]=routers  [1]=api  [2]=uw_scan  [3]=src → .parent = repo root
_DOCS_REGIME = (
    Path(__file__).resolve().parents[3].parent / "docs" / "research" / "regime"
).resolve()


def _safe_doc_path(filename: str) -> Path:
    """Resolve docs/research/regime/<filename> with four guards.

    1. No directory components in `filename`.
    2. The literal path must NOT be a symlink (check BEFORE resolve —
       resolve follows links and erases the symlink-ness).
    3. Resolved target stays within `_DOCS_REGIME` (defense in depth).
    4. Resolved target is a regular file.
    """
    if "/" in filename or filename.startswith("."):
        raise HTTPException(400, f"invalid filename: {filename!r}")
    raw = _DOCS_REGIME / filename
    if raw.is_symlink():
        raise HTTPException(404, f"{filename}: not a regular file (symlink)")
    if not raw.exists():
        raise HTTPException(404, f"{filename}: not found")
    candidate = raw.resolve()
    if not candidate.is_relative_to(_DOCS_REGIME):
        raise HTTPException(400, "path escapes docs/research/regime/")
    if not candidate.is_file():
        raise HTTPException(404, f"{filename}: not a regular file")
    return candidate


def _read_oos_summary() -> OosSummary | None:
    try:
        path = _safe_doc_path("oos-summary.json")
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise
    try:
        return OosSummary.model_validate_json(path.read_text())
    except Exception as exc:
        raise HTTPException(500, f"oos-summary.json malformed: {exc!r}") from exc


def _count_csv_rows(filename: str) -> int:
    try:
        path = _safe_doc_path(filename)
    except HTTPException as exc:
        if exc.status_code == 404:
            return 0
        raise
    with path.open() as f:
        return sum(1 for _ in csv.DictReader(f))


@router.get("/validation", response_model=ValidationResponse)
def get_validation() -> ValidationResponse:
    # _safe_doc_path raises 404 with a precise reason (not-found vs symlink
    # vs not-regular-file) — let it propagate.
    md_path = _safe_doc_path("cri-backtest.md")
    return ValidationResponse(
        backtest_md=md_path.read_text(),
        backtest_csv_rows=_count_csv_rows("cri-backtest.csv"),
        oos=_read_oos_summary(),
    )
