"""current_macro_signal_live — intraday VIX -> live vrp_z vs the EOD distribution.

DB-backed (load_index_vol). Reuses the SPX/VIX seeding + settings helper from the
sibling EOD reports test so the >=252-row z-window is available."""

from __future__ import annotations

import pytest

from tests.integration.reports.test_vrp_macro_signal import (
    _seed_spx_vix_varied,
    _settings,
)
from uw_scan.reports.vrp_macro_signal import (
    WINNER,
    current_macro_signal,
    current_macro_signal_live,
)


def test_live_matches_eod_when_fed_eod_inputs(seeded_db_empty_cards) -> None:
    """Invariant: live(eod_spot, eod_iv) reproduces the EOD signal's vrp_z exactly."""
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    eod = current_macro_signal(repo, _settings(), "SPX", WINNER)
    live = current_macro_signal_live(
        repo, _settings(), "SPX", WINNER, live_spot=eod.spot, live_iv=eod.iv
    )
    assert eod.vrp_z is not None
    assert live.vrp_z == pytest.approx(eod.vrp_z, abs=1e-9)
    assert live.action == eod.action


def test_high_live_iv_triggers_trade(seeded_db_empty_cards) -> None:
    """A live IV well above the EOD distribution pushes vrp_z up -> TRADE, w>0."""
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    eod = current_macro_signal(repo, _settings(), "SPX", WINNER)
    live = current_macro_signal_live(
        repo, _settings(), "SPX", WINNER, live_spot=eod.spot, live_iv=eod.iv + 0.10
    )
    assert live.vrp_z > (eod.vrp_z or 0)
    assert live.action == "TRADE" and live.weight > 0
    assert live.short_put is not None and live.max_loss is not None


def test_bad_tick_raises(seeded_db_empty_cards) -> None:
    """Zero/negative VIX (live_iv<=0) or spot must raise -> endpoint/worker fall back."""
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    with pytest.raises(ValueError):
        current_macro_signal_live(
            repo, _settings(), "SPX", WINNER, live_spot=7500.0, live_iv=0.0
        )
    with pytest.raises(ValueError):
        current_macro_signal_live(
            repo, _settings(), "SPX", WINNER, live_spot=0.0, live_iv=0.16
        )
