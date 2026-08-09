-- 113_watchlist_chain.sql — many-to-many industry-chain membership. Idempotent.
--
-- `uw_scan.watchlist.sector` is a single TEXT column, so a ticker can hold exactly
-- one tag. The taxonomy it is being asked to express is not one-to-one: NVDA is
-- genuinely in Computer/GPU, M7 AND Foundation-Model-Proxy; ARM is in three L1
-- chains; IBM is both Cloud/Hyperscaler and Quantum. Under one column those are
-- mutually exclusive, and the consequence is visible on the dashboard today —
-- the Foundation-Model-Proxy chain reads as EMPTY while all five of its members
-- sit on the page tagged `M7`.
--
-- ADDITIVE, not a replacement. `watchlist.sector` stays and keeps its job: it is
-- the ticker's single PRIMARY tag and decides which one section a card renders
-- under. This table carries the full membership set that FILTERING selects on.
-- Filtering Computer/GPU shows NVDA; the unfiltered grid still shows NVDA exactly
-- once, under its sector. Without that split, a naive many-to-many render draws
-- NVDA's card three times and ARM's three times — ~114 tickers becoming ~150
-- cards for the same names.
--
-- No date column, deliberately. This is a dimension, not a temporal fact table,
-- so it is not a data-gap-healer dataset and needs no DatasetRegistryEntry.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.watchlist_chain (
    ticker     TEXT NOT NULL,
    -- Layer key from uw_scan.watchlist_taxonomy (L1..L5, X, IDX, THM, DEF).
    -- Stored rather than derived from `chain` so a chain can be re-parented
    -- between layers without rewriting every row's meaning.
    layer      TEXT NOT NULL,
    chain      TEXT NOT NULL,
    -- Where the row came from: 'taxonomy' (enumerated in the module) or
    -- 'sector' (inherited from the legacy watchlist.sector value). Kept because
    -- a re-seed must be able to replace taxonomy rows without destroying the
    -- inherited ones, and because it answers "why is this ticker here?".
    source     TEXT NOT NULL DEFAULT 'taxonomy',
    added_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- (ticker, chain) not (ticker, layer, chain): chain names are unique across
    -- layers by construction, and this PK is what makes re-seeding idempotent.
    PRIMARY KEY (ticker, chain)
);

COMMENT ON TABLE uw_scan.watchlist_chain IS
    'Many-to-many ticker -> industry chain membership. Additive to '
    'watchlist.sector, which remains the single primary/display tag. See '
    '113_watchlist_chain.sql for why both exist.';

-- The filter reads "which tickers are in this chain", so lead with chain.
CREATE INDEX IF NOT EXISTS ix_watchlist_chain_chain
    ON uw_scan.watchlist_chain (chain, ticker);

-- The card payload reads "which chains is this ticker in" for every row of the
-- watchlist response, so that direction needs to be indexed too.
CREATE INDEX IF NOT EXISTS ix_watchlist_chain_ticker
    ON uw_scan.watchlist_chain (ticker);

CREATE INDEX IF NOT EXISTS ix_watchlist_chain_layer
    ON uw_scan.watchlist_chain (layer, chain);
