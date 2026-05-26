"""Loader for canary-calibration-v<N>.json. Read-only at runtime.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §7.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

COMPOSITE_VERSION = 1

# Default location — overridable for tests.
DEFAULT_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "research"
    / "regime"
    / f"canary-calibration-v{COMPOSITE_VERSION}.json"
)

ScoreForm = Literal["linear", "convex", "concave", "sigmoid"]


@dataclass(frozen=True)
class SignalThresholds:
    floor: float
    ceiling: float
    max_points: int
    extras: dict[str, float | int]


@dataclass(frozen=True)
class Calibration:
    composite_version: int
    score_form: ScoreForm
    vix_spike_revert: SignalThresholds
    vix_vix3m_back: SignalThresholds
    vrp: SignalThresholds
    cor1m_decay: SignalThresholds
    vvix_vix_recovery: SignalThresholds


def load_calibration(path: Path = DEFAULT_PATH) -> Calibration:
    raw = json.loads(path.read_text())
    t = raw["thresholds"]

    def _read(name: str) -> SignalThresholds:
        d = dict(t[name])
        floor = float(d.pop("floor"))
        ceiling = float(d.pop("ceiling"))
        max_points = int(d.pop("max_points"))
        return SignalThresholds(
            floor=floor, ceiling=ceiling, max_points=max_points, extras=d
        )

    return Calibration(
        composite_version=int(raw["composite_version"]),
        score_form=raw["score_form"],
        vix_spike_revert=_read("vix_spike_revert"),
        vix_vix3m_back=_read("vix_vix3m_back"),
        vrp=_read("vrp"),
        cor1m_decay=_read("cor1m_decay"),
        vvix_vix_recovery=_read("vvix_vix_recovery"),
    )
