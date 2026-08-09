"""Invariants the chain seeder and the filter rail both depend on."""

from __future__ import annotations

from uw_scan.watchlist_taxonomy import (
    LAYERS,
    SELECTED_ADDS,
    all_chains,
    chains_for,
    memberships,
)


def test_every_selected_add_lands_in_at_least_one_chain() -> None:
    """An add with no chain would be scanned but unreachable by any filter."""
    placed = {ticker for ticker, _, _ in memberships()}
    assert not sorted(SELECTED_ADDS - placed)


def test_chain_names_are_unique_across_layers() -> None:
    """`chain` is the filter key and half of the join-table PK.

    Two layers sharing a chain name would make (ticker, chain) ambiguous and
    silently merge two different chains in the UI.
    """
    names = [chain for _, _, chain in all_chains()]
    assert len(names) == len(set(names))


def test_no_duplicate_ticker_within_a_chain() -> None:
    """A repeat would violate the (ticker, chain) primary key on insert."""
    for layer in LAYERS:
        for chain, tickers in layer.chains.items():
            assert len(tickers) == len(set(tickers)), f"{layer.key}/{chain}"


def test_multi_chain_membership_is_expressible() -> None:
    """The whole reason the join table exists — a single sector column can't."""
    assert chains_for("NVDA") == [
        "Computer/GPU",
        "Foundation-Model-Proxy",
        "M7",
    ]
    assert chains_for("ARM") == ["Computer/GPU", "Semi-Logic/ASIC", "Semi-Cap/EDA"]
    # IBM in both its layer chain and the new Thematic/Quantum chain.
    assert chains_for("IBM") == ["Cloud/Hyperscaler", "Quantum"]


def test_foundation_model_proxy_is_fully_covered() -> None:
    """All five are already on the watchlist tagged M7.

    This chain reads as empty under a single-tag schema while every member is
    on screen — the concrete bug the join table fixes.
    """
    proxy = dict(next(layer for layer in LAYERS if layer.key == "L5").chains)
    assert set(proxy["Foundation-Model-Proxy"]) <= set(
        dict(next(layer for layer in LAYERS if layer.key == "X").chains)["M7"]
    )


def test_selected_adds_count_is_pinned() -> None:
    """Budget is computed from this count; a silent change moves the UW spend."""
    assert len(SELECTED_ADDS) == 59


def test_case_insensitive_lookup() -> None:
    assert chains_for("nvda") == chains_for("NVDA")
