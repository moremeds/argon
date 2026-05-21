"""Per-ticker dealer regime classifier.

Combines the existing dealer Greek aggregates into a single Amplifying ↔
Dampening label with a headline copy block. Pure functions — no DB or
network. Inputs come from rows the report assembler already fetches:

  - ``market_structure.net_gex`` (current net dealer Γ)
  - ``greek_exposure_daily`` previous-close net Γ (for Γ vs prev close)
  - ``exposures_summary[]`` net_vanna / net_charm per expiry
  - ``strike_gex_curve`` per-strike, per-expiry gamma (for 0DTE + decay)
  - ``market_structure_levels`` (call wall, put wall, gex flip)
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

# Normalization scales — tuned for the dollar-gamma magnitudes seen in
# production (`SUM(call_gex+put_gex)` for SPY/NVDA/AAPL/TSLA is in the
# 80k–650k range, verified 2026-05-21). tanh keeps the signal smooth.
# Direction matters more than the exact magnitude.
GAMMA_SCALE = 5e5
VANNA_SCALE = 5e5
CHARM_SCALE = 5e5

# Per-asset-class overrides — populated post v1; empty here so v1 uses the
# defaults for every ticker.
SCALE_BY_CLASS: dict[str, tuple[float, float, float]] = {}

# Anything inside this band is reported as "neutral" rather than committing
# to a Long/Short Γ headline. Keeps the panel quiet on thin days.
NEUTRAL_BAND = 0.05

# Γ dominates (it's the first-order delta-hedge signal); V and C are
# tie-breakers. The linear blend is a HINT, not a verdict — raw Γ/V/C
# are always rendered alongside.
GAMMA_WEIGHT = 0.7
VANNA_WEIGHT = 0.2
CHARM_WEIGHT = 0.1


@dataclass
class _Signal:
    label: str
    score: float
    gamma_score: float
    vanna_score: float
    charm_score: float
    headline: str
    subtitle: str


@dataclass
class _ClosestLevel:
    """A ranked level near spot. Two rankings: by |distance_pct| (nearest)
    and by |gamma| (dominant). UI renders both; subtitle keys off dominant."""

    label: str
    direction: str | None
    role: str | None
    strike: float
    distance_pct: float
    gamma: float | None
    rank_kind: str = "nearest"


@dataclass
class _GammaDecayBucket:
    """One DTE bucket. Carries both net (signed; direction) and gross
    (sum of |row gamma|; magnitude) so a near-zero NET bucket with huge
    gross is not hidden."""

    dte: int
    expiry: str
    net_gex: float | None
    share_pct: float | None
    gross_abs_gex: float | None = None
    gross_share_pct: float | None = None


@dataclass
class DealerRegimeOutput:
    """Plain dataclass mirroring `DealerRegimeResponse` fields. The router
    converts this to the Pydantic model for the HTTP boundary."""

    ticker: str
    spot: float | None
    net_gex: float | None
    prev_close_net_gex: float | None
    signal: _Signal
    closest_levels: list[_ClosestLevel]
    odte_gex: float | None
    odte_share_pct: float | None
    gamma_decay: list[_GammaDecayBucket]


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize_score(value: float | None, *, scale: float) -> float:
    """tanh-shaped score in [-1, 1]. Cheap, smooth, monotonic, sign-preserving."""

    if value is None or scale <= 0:
        return 0.0
    return math.tanh(value / scale)


def classify_regime(*, gamma: float, vanna: float, charm: float) -> _Signal:
    """Combine Γ/V/C scores into a single regime label + headline copy."""

    score = GAMMA_WEIGHT * gamma + VANNA_WEIGHT * vanna + CHARM_WEIGHT * charm

    if abs(score) < NEUTRAL_BAND:
        label = "neutral"
    elif score > 0:
        label = "dampening"
    else:
        label = "amplifying"

    if gamma > 0:
        gamma_phrase = "Long Γ"
    elif gamma < 0:
        gamma_phrase = "Short Γ"
    else:
        gamma_phrase = "Flat Γ"

    if label == "neutral":
        headline = f"{gamma_phrase} → Neutral regime"
    elif label == "dampening":
        headline = f"{gamma_phrase} → Dampening regime"
    else:
        headline = f"{gamma_phrase} → Amplifying regime"

    return _Signal(
        label=label,
        score=score,
        gamma_score=gamma,
        vanna_score=vanna,
        charm_score=charm,
        headline=headline,
        subtitle="",
    )


def _sum_decimal(values: Iterable[Any]) -> float:
    total = 0.0
    for v in values:
        f = _to_float(v)
        if f is not None:
            total += f
    return total


def _row_net_gex(row: Mapping[str, Any]) -> float | None:
    """Coalesce ``net_gex`` (canonical) and ``gamma`` (legacy snapshot key)."""
    for k in ("net_gex", "gamma"):
        v = row.get(k)
        if v is not None:
            f = _to_float(v)
            if f is not None:
                return f
    return None


def compute_gamma_decay(
    strike_gex_curve: Iterable[Mapping[str, Any]],
    *,
    today: _date,
) -> list[_GammaDecayBucket]:
    """Sum per-expiry net + gross gamma, sorted by DTE.

    - Carries BOTH ``net_gex`` (signed; direction) and ``gross_abs_gex``
      (sum of |row gamma|; magnitude). A bucket where call and put gamma
      cancel out can show a tiny net but a huge gross.
    - Filters expired buckets (``dte < 0``) — already-rolled-off stale data.
    - All-zero buckets return ``share_pct = None`` so UI renders "—".
    """

    by_expiry_net: dict[_date, float] = {}
    by_expiry_gross: dict[_date, float] = {}
    for row in strike_gex_curve:
        expiry = row.get("expiry")
        if expiry is None:
            continue
        if not isinstance(expiry, _date):
            try:
                expiry = _date.fromisoformat(str(expiry))
            except ValueError:
                continue
        g = _row_net_gex(row)
        if g is None:
            continue
        by_expiry_net[expiry] = by_expiry_net.get(expiry, 0.0) + g
        by_expiry_gross[expiry] = by_expiry_gross.get(expiry, 0.0) + abs(g)

    if not by_expiry_net:
        return []

    valid = [(e, n) for e, n in by_expiry_net.items() if (e - today).days >= 0]
    if not valid:
        return []

    total_abs_net = sum(abs(n) for _, n in valid)
    total_gross = sum(by_expiry_gross[e] for e, _ in valid)

    buckets: list[_GammaDecayBucket] = []
    for expiry, net in sorted(valid):
        gross = by_expiry_gross[expiry]
        buckets.append(
            _GammaDecayBucket(
                dte=(expiry - today).days,
                expiry=expiry.isoformat(),
                net_gex=net,
                share_pct=(abs(net) / total_abs_net) if total_abs_net > 0 else None,
                gross_abs_gex=gross,
                gross_share_pct=(gross / total_gross) if total_gross > 0 else None,
            )
        )
    return buckets


def _normalize_levels(levels: Mapping[str, Any] | None) -> dict[str, dict] | None:
    """Coalesce ``{net_gex|gamma}`` and ``{max_accel|max_accelerator}``.

    Output always uses ``net_gex`` and ``max_accel`` regardless of input.
    """
    if not levels:
        return None

    out: dict[str, dict] = {}
    accel = levels.get("max_accel") or levels.get("max_accelerator")
    if accel:
        out["max_accel"] = dict(accel)

    for key in ("gex_flip", "call_wall", "put_wall"):
        lv = levels.get(key)
        if not lv:
            continue
        lv_copy = dict(lv)
        if "net_gex" not in lv_copy and "gamma" in lv_copy:
            lv_copy["net_gex"] = lv_copy["gamma"]
        out[key] = lv_copy
    return out


def _build_closest_levels(
    *,
    spot: float | None,
    levels: Mapping[str, Any] | None,
) -> list[_ClosestLevel]:
    """Build BOTH "nearest" (by |distance_pct|) and "dominant" (by |gamma|)
    ranked lists. Subtitle keys off dominant."""

    if spot is None or spot <= 0:
        return []

    norm = _normalize_levels(levels)
    if norm is None:
        return []

    spec = [
        ("gex_flip", "Gamma Flip", "flip", "flip"),
        ("call_wall", "Call Wall", "up", "resistance"),
        ("put_wall", "Put Wall", "down", "support"),
        ("max_accel", "Accel ↑", "up", "accelerator"),
    ]

    base: list[_ClosestLevel] = []
    for key, label, direction, role in spec:
        lv = norm.get(key)
        if not lv:
            continue
        strike = _to_float(lv.get("strike"))
        if strike is None:
            continue
        gamma = _to_float(lv.get("net_gex"))
        base.append(
            _ClosestLevel(
                label=label,
                direction=direction,
                role=role,
                strike=strike,
                distance_pct=(strike - spot) / spot,
                gamma=gamma,
            )
        )

    nearest = [_ClosestLevel(**{**l.__dict__, "rank_kind": "nearest"}) for l in base]
    nearest.sort(key=lambda l: abs(l.distance_pct))

    dominant = [
        _ClosestLevel(**{**l.__dict__, "rank_kind": "dominant"})
        for l in base
        if l.gamma is not None
    ]
    dominant.sort(key=lambda l: -abs(l.gamma or 0.0))

    return nearest + dominant


def _subtitle_from_closest(closest: list[_ClosestLevel], label: str) -> str:
    """Subtitle anchors on the DOMINANT level (largest |gamma|), not nearest."""
    if not closest:
        return ""
    dominant = next((l for l in closest if l.rank_kind == "dominant"), None)
    top = dominant or closest[0]
    side = (
        "resistance"
        if top.role == "resistance"
        else ("support" if top.role == "support" else top.role or "")
    )
    side_phrase = f" ({side})" if side else ""
    if label == "dampening":
        verb = "dealers may sell into rallies as price approaches it"
    elif label == "amplifying":
        verb = "dealers may chase moves through it"
    else:
        verb = "dealer flow is mixed near it"
    return (
        f"Largest level is the {top.label.lower()}{side_phrase} at "
        f"${top.strike:.2f} — {verb}."
    )


def compute_dealer_regime(
    *,
    ticker: str,
    spot: float | None,
    net_gex: float | None,
    prev_close_net_gex: float | None,
    per_expiry_vanna: Iterable[Any],
    per_expiry_charm: Iterable[Any],
    strike_gex_curve: Iterable[Mapping[str, Any]],
    levels: Mapping[str, Any] | None,
    today: _date,
) -> DealerRegimeOutput:
    curve = list(strike_gex_curve)

    net_gex_f = _to_float(net_gex)
    spot_f = _to_float(spot)
    prev_close_f = _to_float(prev_close_net_gex)

    gamma_score = normalize_score(net_gex_f, scale=GAMMA_SCALE)
    vanna_total = _sum_decimal(per_expiry_vanna)
    charm_total = _sum_decimal(per_expiry_charm)
    vanna_score = normalize_score(vanna_total, scale=VANNA_SCALE)
    charm_score = normalize_score(charm_total, scale=CHARM_SCALE)

    signal = classify_regime(gamma=gamma_score, vanna=vanna_score, charm=charm_score)
    closest = _build_closest_levels(spot=spot_f, levels=levels)
    signal.subtitle = _subtitle_from_closest(closest, signal.label)

    decay = compute_gamma_decay(curve, today=today)
    odte_bucket = next((b for b in decay if b.dte == 0), None)

    return DealerRegimeOutput(
        ticker=ticker,
        spot=spot_f,
        net_gex=net_gex_f,
        prev_close_net_gex=prev_close_f,
        signal=signal,
        closest_levels=closest,
        odte_gex=odte_bucket.net_gex if odte_bucket else None,
        odte_share_pct=odte_bucket.share_pct if odte_bucket else None,
        gamma_decay=decay,
    )


# ----------------------------------------------------------------------
# Shared input gather — used by both /regime/dealer and the report assembler
# to guarantee one source of truth. REV 3 patched data sources after
# verifying that MarketAggregates does NOT contain spot/net_gex.
# ----------------------------------------------------------------------


def _et_today() -> _date:
    """Market date in US/Eastern — what dealers price into 0DTE buckets."""
    return datetime.now(ZoneInfo("America/New_York")).date()


def _prev_close_net_gex(history_rows: list[dict], today: _date) -> float | None:
    """Most recent row strictly before ``today``.

    `GreekExposureDailyRepository.fetch_history` returns rows ASCENDING by
    trade_date, so we scan from the tail.
    """
    for r in reversed(history_rows):
        d = r.get("trade_date")
        if d is None:
            continue
        if isinstance(d, str):
            d = _date.fromisoformat(d)
        if d < today:
            net = r.get("net_gex")
            return _to_float(net) if net is not None else None
    return None


def gather_inputs(repo: Any, *, ticker: str, today: _date | None = None) -> dict:
    """Single source of truth for ``compute_dealer_regime`` inputs.

    Both the report assembler and the /regime/dealer endpoint call this so
    they share one upstream path. Reads from the same primitives the
    existing report uses (``fetch_realized_vol_latest``,
    ``fetch_exposures_aggregate``, ``fetch_exposures_summary``,
    ``get_strike_gex_curve``) and augments with ``greek_exposure_daily``
    for prev-close.

    Returns: ``run_id``, ``spot``, ``net_gex``, ``prev_close_net_gex``,
    ``per_expiry_vanna``, ``per_expiry_charm``, ``strike_gex_curve``,
    ``levels``, ``today``. ``run_id`` is 0 if no scan exists.
    """
    from uw_scan.cards.gex import compute_market_structure_levels
    from uw_scan.models import StrikeGexBucket
    from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository

    t = ticker.upper()
    today = today or _et_today()
    run_id = repo.latest_run_id(t)
    if run_id == 0:
        return {
            "run_id": 0,
            "spot": None,
            "net_gex": None,
            "prev_close_net_gex": None,
            "per_expiry_vanna": [],
            "per_expiry_charm": [],
            "strike_gex_curve": [],
            "levels": None,
            "today": today,
        }

    strike_curve_raw = repo.get_strike_gex_curve(run_id) or []
    exposures = repo.fetch_exposures_summary(run_id, t) or []

    rv_row = repo.fetch_realized_vol_latest(t) or {}
    spot_raw = rv_row.get("price")
    spot_f = _to_float(spot_raw)

    exp_agg = repo.fetch_exposures_aggregate(run_id, t) or {}
    total_call_gex = exp_agg.get("total_call_gex")
    total_put_gex = exp_agg.get("total_put_gex")
    net_gex_f: float | None = None
    if total_call_gex is not None and total_put_gex is not None:
        net_gex_f = _to_float(total_call_gex) + _to_float(total_put_gex)

    curve_typed: list[StrikeGexBucket] = []
    for row in strike_curve_raw:
        if row.get("strike") is None or row.get("expiry") is None:
            continue
        expiry = row["expiry"]
        if isinstance(expiry, str):
            try:
                expiry = _date.fromisoformat(expiry)
            except ValueError:
                continue
        curve_typed.append(
            StrikeGexBucket(
                strike=Decimal(str(row["strike"])),
                expiry=expiry,
                net_gex=Decimal(str(row["net_gex"]))
                if row.get("net_gex") is not None
                else None,
                call_gex=Decimal(str(row["call_gex"]))
                if row.get("call_gex") is not None
                else None,
                put_gex=Decimal(str(row["put_gex"]))
                if row.get("put_gex") is not None
                else None,
            )
        )

    spot_dec = Decimal(str(spot_f)) if spot_f is not None else None
    levels_model = compute_market_structure_levels(curve_typed, spot_dec)
    levels = levels_model.model_dump(mode="json") if levels_model else None

    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    history = g.fetch_history(t, days=5)
    prev_close = _prev_close_net_gex(history, today)

    return {
        "run_id": run_id,
        "spot": spot_f,
        "net_gex": net_gex_f,
        "prev_close_net_gex": prev_close,
        "per_expiry_vanna": [e.get("net_vanna") for e in exposures],
        "per_expiry_charm": [e.get("net_charm") for e in exposures],
        "strike_gex_curve": strike_curve_raw,
        "levels": levels,
        "today": today,
    }
