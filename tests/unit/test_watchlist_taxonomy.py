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
    assert len(SELECTED_ADDS) == 60


def test_case_insensitive_lookup() -> None:
    assert chains_for("nvda") == chains_for("NVDA")


def test_no_layer_is_empty() -> None:
    """Every chain names its members.

    IDX/THM/DEF used to hold empty tuples and seed from `watchlist.sector`.
    That capped those names at ONE chain each, because `sector` is one column —
    silently excluding them from the many-to-many the join table exists for.
    An empty tuple here means a chain has quietly gone back to that.
    """
    empty = [
        f"{layer.key}/{chain}"
        for layer in LAYERS
        for chain, tickers in layer.chains.items()
        if not tickers
    ]
    assert not empty


def test_merged_legacy_tags_can_hold_a_second_chain() -> None:
    """The point of merging the sector-inherited tags into the module.

    Under sector-inheritance each of these could hold exactly one chain.
    """
    # Bitcoin miners that pivoted to AI datacenters: both, not either.
    assert chains_for("MARA") == ["AI-Cloud/NeoCloud", "Crypto"]
    assert chains_for("RIOT") == ["AI-Cloud/NeoCloud", "Crypto"]
    # SpaceX is M7 by operator decision and Space by what it is.
    assert chains_for("SPCX") == ["M7", "Space"]


def test_novo_nordisk_not_national_oilwell_varco() -> None:
    """NVO is Novo Nordisk. NOV is National Oilwell Varco — oil drilling
    equipment, UW sector Energy — and was a typo carrying a Healthcare tag.
    """
    assert chains_for("NVO") == ["Healthcare"]
    assert chains_for("NOV") == []
    # ELV (Elevance Health, a common stock) was a typo for the XLV ETF.
    assert chains_for("ELV") == []
    assert chains_for("XLV") == ["Sector-ETF"]


def test_sector_etfs_are_not_cross_listed_into_company_chains() -> None:
    """A chain answers "which companies are in this value chain".

    A fund tracking it is a different question, so SMH/SOXX/IGV/MAGS carry
    Sector-ETF and nothing else. Deliberate — revisit only on purpose.
    """
    for etf in ("SMH", "SOXX", "SOXL", "IGV", "MAGS"):
        assert chains_for(etf) == ["Sector-ETF"], etf
