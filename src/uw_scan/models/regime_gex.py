"""GEX response models — over-the-wire contract for the regime GEX API.

Keep stable; update `openapi-typescript` regen when fields change.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from ._api_coerce import _to_float

# ─── GEX (regime port from xenon 2026-05-16) ─────────────────────────────


class RegimeGexLevel(BaseModel):
    strike: float | None = None
    gamma: float | None = None
    distance: float | None = None
    distance_pct: float | None = None

    _coerce_floats = field_validator(
        "strike", "gamma", "distance", "distance_pct", mode="before"
    )(_to_float)


class GexLevels(BaseModel):
    gex_flip: RegimeGexLevel | None = None
    max_magnet: RegimeGexLevel | None = None
    second_magnet: RegimeGexLevel | None = None
    max_accelerator: RegimeGexLevel | None = None
    put_wall: RegimeGexLevel | None = None
    call_wall: RegimeGexLevel | None = None


class GexBucket(BaseModel):
    strike: float | None = None
    call_gex: float | None = None
    put_gex: float | None = None
    net_gex: float | None = None
    pct_from_spot: float | None = None
    tag: str | None = None

    _coerce_floats = field_validator(
        "strike", "call_gex", "put_gex", "net_gex", "pct_from_spot", mode="before"
    )(_to_float)


class GexFlipMigrationEntry(BaseModel):
    date: str
    flip: float | None = None

    _coerce_floats = field_validator("flip", mode="before")(_to_float)


class GexBias(BaseModel):
    direction: str | None = None
    reasons: list[str] = Field(default_factory=list)
    days_above_flip: int | None = None
    flip_migration: list[GexFlipMigrationEntry] = Field(default_factory=list)


class GexExpectedRange(BaseModel):
    low: float | None = None
    high: float | None = None
    iv_1d: float | None = None

    _coerce_floats = field_validator("low", "high", "iv_1d", mode="before")(_to_float)


class GexHistoryEntry(BaseModel):
    date: str
    net_gex: float | None = None
    net_dex: float | None = None
    gex_flip: float | None = None
    spot: float | None = None
    atm_iv: float | None = None
    vol_pc: float | None = None
    bias: str | None = None

    _coerce_floats = field_validator(
        "net_gex", "net_dex", "gex_flip", "spot", "atm_iv", "vol_pc", mode="before"
    )(_to_float)


class GexIvData(BaseModel):
    iv30d: float | None = None
    iv_rank: float | None = None
    hv30: float | None = None
    mq_iv30d: float | None = None
    mq_iv_rank: str | None = None
    source: str | None = None

    _coerce_floats = field_validator(
        "iv30d", "iv_rank", "hv30", "mq_iv30d", mode="before"
    )(_to_float)


class GexMqLevels(BaseModel):
    source_date: str | None = None
    spot: float | None = None
    hvl: float | None = None
    call_resistance_all: float | None = None
    call_resistance_0dte: float | None = None
    put_support_all: float | None = None
    put_support_0dte: float | None = None
    expected_high: float | None = None
    expected_low: float | None = None
    distance_to_hvl_pct: str | None = None
    iv30d: float | None = None
    hv30: float | None = None
    iv_rank: str | None = None
    top_gex_strikes: list[float] = Field(default_factory=list)

    _coerce_floats = field_validator(
        "spot",
        "hvl",
        "call_resistance_all",
        "call_resistance_0dte",
        "put_support_all",
        "put_support_0dte",
        "expected_high",
        "expected_low",
        "iv30d",
        "hv30",
        mode="before",
    )(_to_float)


class GexSourceDeltaEntry(BaseModel):
    uw: float | None = None
    mq: float | None = None
    delta: float | None = None

    _coerce_floats = field_validator("uw", "mq", "delta", mode="before")(_to_float)


class GexSourceDelta(BaseModel):
    flip_vs_hvl: GexSourceDeltaEntry | None = None
    put_wall_vs_support_all: GexSourceDeltaEntry | None = None
    put_wall_vs_support_0dte: GexSourceDeltaEntry | None = None
    call_wall_vs_resistance_all: GexSourceDeltaEntry | None = None
    call_wall_vs_resistance_0dte: GexSourceDeltaEntry | None = None


class GexResponse(BaseModel):
    scan_time: str = ""
    market_open: bool = False
    ticker: str = "SPX"
    spot: float | None = None
    close: float | None = None
    prev_close: float | None = None
    market_time: str | None = None
    tape_time: str | None = None
    spot_source: str | None = None
    day_change: float | None = None
    day_change_pct: float | None = None
    data_date: str | None = None
    net_gex: float | None = None
    net_dex: float | None = None
    atm_iv: float | None = None
    vol_pc: float | None = None
    levels: GexLevels = Field(default_factory=GexLevels)
    profile: list[GexBucket] = Field(default_factory=list)
    expected_range: GexExpectedRange = Field(default_factory=GexExpectedRange)
    bias: GexBias = Field(default_factory=GexBias)
    history: list[GexHistoryEntry] = Field(default_factory=list)
    iv: GexIvData | None = None
    mq: GexMqLevels | None = None
    source_delta: GexSourceDelta | None = None

    _coerce_floats = field_validator(
        "spot",
        "close",
        "prev_close",
        "day_change",
        "day_change_pct",
        "net_gex",
        "net_dex",
        "atm_iv",
        "vol_pc",
        mode="before",
    )(_to_float)


EMPTY_GEX_RESPONSE = GexResponse()


# ─── GEX intraday (5-session RTH tape from gex_snapshots) ────────


class GexIntradayPoint(BaseModel):
    """One row from gex_snapshots inside a single ET trading session."""

    ts: datetime  # scanned_at, ISO timestamp (UTC on the wire)
    spot: float | None = None
    net_gex: float | None = None
    gex_flip: float | None = None
    iv30d: float | None = None


class GexIntradaySession(BaseModel):
    et_date: date
    points: list[GexIntradayPoint] = Field(default_factory=list)


class GexIntradayResponse(BaseModel):
    """Last N RTH sessions of intraday GEX snapshots for a ticker.

    Sessions are ordered oldest→newest so the chart can scan left-to-right.
    Points within each session are also ASC by ``ts``.
    """

    ticker: str
    sessions: list[GexIntradaySession] = Field(default_factory=list)
    as_of: datetime | None = None
