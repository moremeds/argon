"""Which datasets may be re-fetched under a historical ``market_date``.

A dataset is replay-safe ONLY if UW's response for one date differs from its
response for another. Where the endpoint ignores ``date`` and always returns the
latest session, writing that payload under a past ``market_date`` would present
today's numbers as history — fabrication, which CLAUDE.md forbids outright. The
refusal therefore lives here, in code, rather than in a comment a future caller
can miss.

Evidence: probed live 2026-08-16 (AAPL, ``date=2026-08-11`` vs ``date=2026-08-13``
vs undated, standard tier), comparing sha256 of the raw response body. Full
matrix and method: ``docs/research/2026-08-16-replay-endpoint-matrix.md``.

Note the trap this guards against: all three refused endpoints answer HTTP 200
with a plausible, fully-populated row set for any date you ask for. Only the hash
differential distinguishes "served me that session" from "served me today again".
"""

from __future__ import annotations


class ReplayRefused(ValueError):
    """Raised when a caller asks to replay a dataset that cannot be dated."""


#: Datasets whose UW endpoint was measured to return a different body per date.
REPLAY_SAFE: frozenset[str] = frozenset(
    {
        "iv_term_snapshots",
        "interpolated_iv_snapshots",
        "exposures_summary",
        "exposures_by_expiry_strike",
        "greeks_by_expiry_strike",
        "oi_by_strike",
        "oi_change_events",
        "max_pain_by_expiry",
        "option_contract_snapshots",
        "dark_pool_events",
        "pcr_history",
    }
)

#: dataset -> why it can never be replayed. Every reason cites the date it was
#: measured, because an undated reason is an assumption and the assumptions in
#: this codebase's dataset registry have been wrong before.
REPLAY_REFUSED: dict[str, str] = {
    "options_volume_daily": (
        "UW /api/stock/{ticker}/options-volume ignores `date` — measured "
        "2026-08-16, byte-identical response body (sha256 59d1552e57) for "
        "date=2026-08-11, date=2026-08-13 and undated"
    ),
    "short_interest_snapshots": (
        "UW /api/shorts/{ticker}/data ignores `date` — measured 2026-08-16, "
        "byte-identical response body (sha256 71d58bc350) for date=2026-08-11, "
        "date=2026-08-13 and undated"
    ),
    "uw_positioning": (
        "UW /api/shorts/{ticker}/interest-float/v2 ignores `date` — measured "
        "2026-08-16, byte-identical response body (sha256 9415c845e7) for "
        "date=2026-08-11, date=2026-08-13 and undated"
    ),
}


def assert_replayable(dataset: str) -> None:
    """Raise :class:`ReplayRefused` if ``dataset`` must not be written at a past date."""
    reason = REPLAY_REFUSED.get(dataset)
    if reason is not None:
        raise ReplayRefused(f"{dataset}: {reason}")
