"""Do demand clusters exist in fundamental growth, once the common boom is removed?

    uv run python scripts/research/growth_factor_clusters.py [--metric=revenue|capex]

Every previous round of the capex demand ledger was contaminated the same way:
2021-2026 is one enormous common factor ("all AI moved together"), and any
correlation measured inside it is mostly that factor wearing a chain's name.
Round 2b sized it directly -- the hardware-vs-software gap fell +0.304 -> +0.085
when the window changed -- but never removed it.

So remove it first, then ask what is left:

1. Per-ticker quarterly YoY LOG growth. Within-ticker YoY is inherently
   matched, so this sidesteps the balanced-panel survivorship trap that
   manufactured half of Round 1's signal.
2. The common factor is the cross-sectional mean of standardised growth at each
   quarter. Its share of total variance is the honest size of the confound and
   is reported as a headline number, not a footnote.
3. Residualise every ticker on it, then cluster the RESIDUALS. A cluster here
   means "these names share a demand cycle beyond the boom", which is the only
   version of the claim worth testing.
4. The null comes from the domain, not from a shuffle: same-chain pairs should
   correlate more than different-chain pairs. If they do not, the hand-authored
   taxonomy in watchlist_taxonomy.py is not measurable in fundamentals, and
   spec section 8's ruling ("propagation needs edges we do not have") is
   confirmed with evidence instead of assumption.

Deliberately NOT done here: a balanced panel (selects on survivorship), and a
returns test (daily_ohlc is capped at ~5y by massive, so it cannot see a
downturn in the variable whose downturn is the test).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from scipy.cluster.hierarchy import fcluster, linkage  # noqa: E402
from scipy.spatial.distance import squareform  # noqa: E402

from uw_scan.config import Settings  # noqa: E402

#: Fiscal quarters that end in Jan/Apr/Jul/Oct (NVDA, AVGO, ...) belong to the
#: PRIOR calendar quarter's demand. Shifting back one month before truncating
#: aligns them; this is the bucket ROUND2-matched-growth.md established.
BUCKET = "date_trunc('quarter', period_end - interval '1 month')::date"

METRICS = {
    "revenue": ("income", "total_revenue"),
    "capex": ("cash_flow", "capital_expenditures"),
}

MIN_QUARTERS = 24  # per ticker, after growth
MIN_OVERLAP = 20  # common quarters before a pair's correlation is used
MIN_XS = 30  # tickers required in a quarter to trust its cross-section
WINSOR = 0.02  # two-sided, cross-sectional, per quarter
N_CLUSTERS = 8
#: Reporting default only. There is no principled value -- `knn_sweep` measures
#: quality against a null at every k, and that table is the evidence, not this
#: constant. Its first value was lifted from a number in a conversational
#: example and applied to two unrelated parameters; do not treat it as chosen.
KNN = 8
PERM = 2000
MIN_CHAIN_MEMBERS = 4  # below this a chain mean is one or two names wearing a label
MAX_LAG = 4  # quarters, both directions

OUT = (
    Path(__file__).resolve().parents[2]
    / "docs/research/2026-08-13-ai-capex-demand-ledger"
)


def load_series(
    conn, schema: str, statement: str, key: str
) -> dict[str, dict[Any, float]]:
    """{ticker: {quarter_bucket: value}}, restatement-deduped to the latest row."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT ON (ticker, {BUCKET})
                   ticker, {BUCKET} AS q, (raw_jsonb ->> %s)::float8
              FROM {schema}.fundamental_statement_obs
             WHERE statement = %s
               AND period_type = 'quarterly'
               AND raw_jsonb ? %s
               AND (raw_jsonb ->> %s) ~ '^-?[0-9.eE+]+$'
             ORDER BY ticker, {BUCKET}, last_seen_at DESC
            """,
            (key, statement, key, key),
        )
        out: dict[str, dict[Any, float]] = defaultdict(dict)
        for tkr, q, val in cur.fetchall():
            if val is not None:
                out[tkr][q] = abs(val)  # capex is signed by provider convention
    return out


def yoy_log_growth(per_q: dict[Any, float]) -> dict[Any, float]:
    """log(v[t] / v[t-4]) on the ticker's own history.

    Log rather than simple growth: simple YoY is bounded at -1 but unbounded
    above, so a single 5x quarter dominates a correlation. Log is symmetric and
    is what makes a Pearson correlation over these series meaningful at all.
    """
    quarters = sorted(per_q)
    idx = {q: i for i, q in enumerate(quarters)}
    out: dict[Any, float] = {}
    for q in quarters:
        i = idx[q]
        if i < 4:
            continue
        base = quarters[i - 4]
        # Only a true 4-quarter step; a gap in the filing history is not a base.
        if (q.year - base.year) * 4 + (q.month - base.month) // 3 != 4:
            continue
        now, then = per_q[q], per_q[base]
        if now > 0 and then > 0:
            out[q] = float(np.log(now / then))
    return out


def build_panel(
    growth: dict[str, dict[Any, float]],
) -> tuple[list[str], list[Any], np.ndarray]:
    """Tickers x quarters matrix with NaN holes. Never balanced -- see module docstring."""
    tickers = sorted(t for t, g in growth.items() if len(g) >= MIN_QUARTERS)
    quarters = sorted({q for t in tickers for q in growth[t]})
    mat = np.full((len(tickers), len(quarters)), np.nan)
    qidx = {q: j for j, q in enumerate(quarters)}
    for i, t in enumerate(tickers):
        for q, v in growth[t].items():
            mat[i, qidx[q]] = v
    # Drop quarters whose cross-section is too thin to define a common factor.
    keep = np.array(
        [np.count_nonzero(~np.isnan(mat[:, j])) >= MIN_XS for j in range(mat.shape[1])]
    )
    return tickers, [q for q, k in zip(quarters, keep) if k], mat[:, keep]


def winsorise(mat: np.ndarray) -> np.ndarray:
    """Clip each quarter's cross-section. Growth has genuine outliers (a name
    lapping a near-zero base); they are real but they are not what a correlation
    should be measuring."""
    out = mat.copy()
    for j in range(out.shape[1]):
        col = out[:, j]
        ok = ~np.isnan(col)
        if ok.sum() < MIN_XS:
            continue
        lo, hi = np.nanquantile(col[ok], [WINSOR, 1 - WINSOR])
        out[ok, j] = np.clip(col[ok], lo, hi)
    return out


def common_factor(mat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cross-sectional mean of standardised growth per quarter, and the loadings.

    Chosen over an eigen-decomposition for the FACTOR itself because the panel
    is unbalanced by design: an equal-weight cross-sectional mean is defined at
    every quarter over whoever exists, whereas PC1 scores need imputation. The
    eigen-decomposition still runs below, on the correlation matrix, to report
    how much variance the leading components carry.
    """
    z = mat.copy()
    # Standardise each TICKER over time, never each quarter's cross-section.
    # Standardising a column subtracts that quarter's cross-sectional mean --
    # which IS the common factor -- so the subsequent cross-sectional mean is
    # identically zero and the whole residualisation silently becomes a no-op.
    # The symptom is raw and residual results agreeing to two decimals.
    for i in range(z.shape[0]):
        row = z[i]
        ok = ~np.isnan(row)
        if ok.sum() < MIN_OVERLAP:
            z[i, :] = np.nan
            continue
        mu, sd = row[ok].mean(), row[ok].std()
        z[i, ok] = (row[ok] - mu) / sd if sd > 0 else 0.0
    factor = np.nanmean(z, axis=0)
    loadings = np.full(mat.shape[0], np.nan)
    for i in range(mat.shape[0]):
        ok = ~np.isnan(mat[i])
        if ok.sum() >= MIN_OVERLAP and np.std(factor[ok]) > 0:
            loadings[i] = np.polyfit(factor[ok], mat[i, ok], 1)[0]
    return factor, loadings


def residualise(mat: np.ndarray, factor: np.ndarray) -> np.ndarray:
    """Strip each ticker's exposure to the common factor. This is the growth
    analogue of the market residualisation the returns test applied to prices --
    the step that study did and this side of the ledger never had."""
    out = np.full_like(mat, np.nan)
    for i in range(mat.shape[0]):
        ok = ~np.isnan(mat[i])
        if ok.sum() < MIN_OVERLAP:
            continue
        b, a = np.polyfit(factor[ok], mat[i, ok], 1)
        out[i, ok] = mat[i, ok] - (a + b * factor[ok])
    return out


def pairwise_corr(mat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pairwise-complete Pearson. Returns (corr, overlap counts)."""
    n = mat.shape[0]
    corr = np.full((n, n), np.nan)
    olap = np.zeros((n, n), dtype=int)
    ok = ~np.isnan(mat)
    for i in range(n):
        corr[i, i] = 1.0
        for j in range(i + 1, n):
            m = ok[i] & ok[j]
            c = int(m.sum())
            olap[i, j] = olap[j, i] = c
            if c < MIN_OVERLAP:
                continue
            a, b = mat[i, m], mat[j, m]
            sa, sb = a.std(), b.std()
            if sa > 0 and sb > 0:
                r = float(((a - a.mean()) * (b - b.mean())).mean() / (sa * sb))
                corr[i, j] = corr[j, i] = r
    return corr, olap


def eigen_share(corr: np.ndarray, k: int = 5) -> list[float]:
    """Variance share of the leading components of the correlation matrix.

    Pairwise-complete correlation is not guaranteed positive semi-definite, so
    negative eigenvalues are clipped. That is a real approximation and the
    reason this reports shares rather than reconstructing factor scores.
    """
    c = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(c, 1.0)
    vals = np.linalg.eigvalsh((c + c.T) / 2)[::-1]
    vals = np.clip(vals, 0, None)
    tot = vals.sum()
    return [float(v / tot) for v in vals[:k]] if tot > 0 else []


def chain_map(conn, schema: str) -> dict[str, set[str]]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT ticker, chain FROM {schema}.watchlist_chain")
        out: dict[str, set[str]] = defaultdict(set)
        for t, c in cur.fetchall():
            out[t].add(c)
    return out


def taxonomy_test(
    tickers: list[str],
    corr: np.ndarray,
    chains: dict[str, set[str]],
    rng: np.random.Generator,
    sectors: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Do same-chain pairs correlate more than different-chain pairs?

    This is the domain null, and it is stronger than the shuffled-owner control
    every earlier round used: the taxonomy asserts WHICH pairs should be linked,
    so the unlinked pairs are a null drawn from the same data rather than a
    synthetic rearrangement. Many-to-many membership is handled natively -- a
    pair counts as linked if it shares ANY chain -- which a hard partition
    metric like adjusted Rand could not do.
    """
    have = [i for i, t in enumerate(tickers) if chains.get(t)]
    if len(have) < 3:
        return {"error": "fewer than 3 tickers carry chain membership"}

    all_chains = sorted({c for t in tickers for c in chains.get(t, ())})
    cidx = {c: k for k, c in enumerate(all_chains)}
    # Membership as a matrix, so "shares any chain" is one product and a
    # permutation is a row shuffle. Written as a literal double loop this is
    # PERM x ~27k pair comparisons -- minutes of pure Python per call.
    mem = np.zeros((len(have), len(all_chains)), dtype=np.float32)
    for k, i in enumerate(have):
        for c in chains[tickers[i]]:
            mem[k, cidx[c]] = 1.0

    iu = np.triu_indices(len(have), 1)
    r_all = corr[np.ix_(have, have)][iu]
    valid = ~np.isnan(r_all)
    if sectors is not None:
        # The confound this exists to kill: same-chain pairs are also
        # same-industry pairs, so a raw delta could be "semis correlate with
        # semis". Restricting to pairs already IN the same sector asks whether
        # chain membership adds anything beyond the industry they share.
        sec = np.array([sectors.get(tickers[i]) or "" for i in have], dtype=object)
        has = sec != ""
        valid = (
            valid & ((sec[:, None] == sec[None, :]) & has[:, None] & has[None, :])[iu]
        )
    r = r_all[valid]
    linked = ((mem @ mem.T) > 0)[iu][valid]
    if not linked.any() or linked.all():
        return {"error": "degenerate linkage"}
    obs = float(r[linked].mean() - r[~linked].mean())

    # Permute which ticker owns which membership row; the pair geometry and
    # every correlation stay fixed, so the null isolates the taxonomy itself.
    hits = 0
    for _ in range(PERM):
        pm = mem[rng.permutation(len(have))]
        lp = ((pm @ pm.T) > 0)[iu][valid]
        if lp.any() and not lp.all() and (r[lp].mean() - r[~lp].mean()) >= obs:
            hits += 1
    return {
        "n_same_pairs": int(linked.sum()),
        "n_diff_pairs": int((~linked).sum()),
        "mean_r_same": float(r[linked].mean()),
        "mean_r_diff": float(r[~linked].mean()),
        "delta": obs,
        "perm_p": (hits + 1) / (PERM + 1),
    }


def cluster(tickers: list[str], corr: np.ndarray) -> dict[str, Any]:
    d = 1.0 - np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(d, 0.0)
    d = (d + d.T) / 2
    link = linkage(squareform(d, checks=False), method="average")
    labels = fcluster(link, N_CLUSTERS, criterion="maxclust")
    members: dict[int, list[str]] = defaultdict(list)
    for t, lab in zip(tickers, labels):
        members[int(lab)].append(t)
    # kNN neighbourhoods: overlapping by construction, which the many-to-many
    # chain table is too. A hard partition would contradict that structure.
    # Carry the correlation with each neighbour. kNN returns k names whether or
    # not any of them mean anything -- AMAT's peers are the real semi-cap
    # complex, MSFT's are noise it happened to correlate with -- and only the
    # strength distinguishes them. Any display needs this to gate on.
    knn: dict[str, list[tuple[str, float]]] = {}
    for i, t in enumerate(tickers):
        row = corr[i].copy()
        row[i] = -np.inf
        order = np.argsort(np.nan_to_num(row, nan=-np.inf))[::-1][:KNN]
        knn[t] = [(tickers[j], round(float(corr[i, j]), 4)) for j in order]
    # Neighbourhood coherence: do a ticker's peers correlate with EACH OTHER?
    # Top-1 r cannot answer whether a peer set is real -- it is the max over
    # ~370 candidates and is selection-biased upward even under pure noise. A
    # genuine peer group closes the triangle (AMAT's peers are each other's
    # peers); a spurious one is a star with no edges between its points.
    idx = {t: i for i, t in enumerate(tickers)}
    coh: dict[str, float] = {}
    for t, peers in knn.items():
        ids = [idx[p] for p, _ in peers]
        vals = [corr[a, b] for x, a in enumerate(ids) for b in ids[x + 1 :]]
        vals = [v for v in vals if not np.isnan(v)]
        if vals:
            coh[t] = round(float(np.mean(vals)), 4)
    return {
        "coherence": coh,
        "labels": {t: int(lab) for t, lab in zip(tickers, labels)},
        "members": dict(members),
        "knn": knn,
    }


def coherence_at_k(corr: np.ndarray, k: int) -> np.ndarray:
    """Mean correlation AMONG each point's k nearest neighbours."""
    out = []
    for i in range(corr.shape[0]):
        row = corr[i].copy()
        row[i] = -np.inf
        ids = np.argsort(np.nan_to_num(row, nan=-np.inf))[::-1][:k]
        vals = [corr[a, b] for x, a in enumerate(ids) for b in ids[x + 1 :]]
        vals = [v for v in vals if not np.isnan(v)]
        if vals:
            out.append(float(np.mean(vals)))
    return np.array(out)


def knn_sweep(
    corr: np.ndarray,
    resid: np.ndarray,
    rng: np.random.Generator,
    ks: range,
    reps: int = 6,
) -> dict[str, Any]:
    """Peer-set quality at every k, each measured against its OWN null.

    k cannot be picked by taste: coherence falls with k mechanically (more pairs,
    weaker ones), so a raw coherence-vs-k curve always favours the smallest k and
    proves nothing. The null falls too, so the only honest read is the EXCESS
    over a null computed at the same k.

    Null = each series rolled by its own random offset. That destroys
    cross-ticker alignment while preserving each series' autocorrelation and
    marginal distribution, so surviving coherence is shared timing rather than
    shared shape. A plain shuffle would break autocorrelation too and be far too
    easy to beat.
    """
    nulls = []
    for _ in range(reps):
        sh = np.empty_like(resid)
        for i in range(resid.shape[0]):
            sh[i] = np.roll(resid[i], int(rng.integers(1, resid.shape[1])))
        nulls.append(pairwise_corr(sh)[0])
    rows: dict[str, Any] = {}
    for k in ks:
        obs = coherence_at_k(corr, k)
        nul = np.concatenate([coherence_at_k(c, k) for c in nulls])
        p90 = float(np.nanquantile(nul, 0.9))
        rows[str(k)] = {
            "obs_p50": float(np.nanmedian(obs)),
            "null_p50": float(np.nanmedian(nul)),
            "null_p90": p90,
            "share_above_null_p90": float(np.mean(obs > p90)),
        }
    return rows


def natural_k(corr: np.ndarray, ks: range) -> dict[str, float]:
    """Mean silhouette over a precomputed distance, per candidate k.

    N_CLUSTERS was a constant somebody typed, and every cluster size reported
    downstream inherits that choice. This asks the data instead. Silhouette is
    hand-rolled because sklearn is not a dependency here.
    """
    d = 1.0 - np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(d, 0.0)
    d = (d + d.T) / 2
    link = linkage(squareform(d, checks=False), method="average")
    out: dict[str, float] = {}
    for k in ks:
        lab = fcluster(link, k, criterion="maxclust")
        sils = []
        for i in range(len(lab)):
            own = lab == lab[i]
            if own.sum() < 2:
                continue
            a = d[i, own].sum() / (own.sum() - 1)
            b = min(d[i, lab == o].mean() for o in set(lab) if o != lab[i])
            if max(a, b) > 0:
                sils.append((b - a) / max(a, b))
        out[str(k)] = float(np.mean(sils)) if sils else float("nan")
    return out


def sector_map(conn, schema: str) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT ticker, sector FROM {schema}.watchlist WHERE sector IS NOT NULL"
        )
        return {t: s for t, s in cur.fetchall()}


def chain_series(
    tickers: list[str], resid: np.ndarray, chains: dict[str, set[str]]
) -> dict[str, np.ndarray]:
    """Equal-weight mean residual growth per chain, per quarter.

    Aggregating BEFORE the cross-correlation is the point. Round 2 measured
    per-ticker peak lags agreeing only 15/52 across windows -- the argmax of a
    weak correlation is the argmax of noise. A chain mean has a far better
    signal-to-noise ratio, so its argmax is a lag rather than a coin flip.
    """
    idx = {t: i for i, t in enumerate(tickers)}
    out: dict[str, np.ndarray] = {}
    per_chain: dict[str, list[int]] = defaultdict(list)
    for t, cs in chains.items():
        if t in idx:
            for c in cs:
                per_chain[c].append(idx[t])
    for c, rows in per_chain.items():
        if len(rows) < MIN_CHAIN_MEMBERS:
            continue
        block = resid[rows]
        with np.errstate(invalid="ignore"):
            mean = np.where(
                np.isnan(block).all(axis=0), np.nan, np.nanmean(block, axis=0)
            )
        if np.count_nonzero(~np.isnan(mean)) >= MIN_OVERLAP:
            out[c] = mean
    return out


def _corr_at_lag(a: np.ndarray, b: np.ndarray, lag: int) -> tuple[float, int]:
    """corr(a[t], b[t+lag]). Positive lag = b FOLLOWS a, i.e. a leads."""
    n = len(a)
    t = np.arange(n)
    u = t + lag
    ok = (u >= 0) & (u < n)
    t, u = t[ok], u[ok]
    x, y = a[t], b[u]
    m = ~np.isnan(x) & ~np.isnan(y)
    if m.sum() < MIN_OVERLAP:
        return float("nan"), int(m.sum())
    x, y = x[m], y[m]
    if x.std() == 0 or y.std() == 0:
        return float("nan"), int(m.sum())
    return float(((x - x.mean()) * (y - y.mean())).mean() / (x.std() * y.std())), int(
        m.sum()
    )


def lead_lag(series: dict[str, np.ndarray]) -> dict[str, Any]:
    """Cross-correlate every chain pair at lags -4..+4, and test peak-lag stability.

    Two questions, and only the second is evidence. (1) Does the peak sit off
    lag 0 -- necessary for propagation, but a 9-point profile over noise puts
    its peak off-zero most of the time by construction. (2) Does the SAME pair
    peak at the SAME lag in both halves of the sample? Noise cannot do that.
    Chance agreement is ~1/9 exact, ~1/3 within one quarter.
    """
    names = sorted(series)
    lags = list(range(-MAX_LAG, MAX_LAG + 1))
    profiles: dict[str, dict[str, float]] = {}
    peaks: dict[str, int] = {}
    at_zero = 0
    half = len(next(iter(series.values()))) // 2
    half_peaks: dict[str, tuple[int, int]] = {}

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = series[names[i]], series[names[j]]
            prof = {str(lg): _corr_at_lag(a, b, lg)[0] for lg in lags}
            vals = [prof[str(lg)] for lg in lags]
            if all(np.isnan(v) for v in vals):
                continue
            key = f"{names[i]}|{names[j]}"
            profiles[key] = prof
            pk = lags[int(np.nanargmax(vals))]
            peaks[key] = pk
            at_zero += pk == 0
            p1 = [_corr_at_lag(a[:half], b[:half], lg)[0] for lg in lags]
            p2 = [_corr_at_lag(a[half:], b[half:], lg)[0] for lg in lags]
            if not all(np.isnan(v) for v in p1) and not all(np.isnan(v) for v in p2):
                half_peaks[key] = (
                    lags[int(np.nanargmax(p1))],
                    lags[int(np.nanargmax(p2))],
                )

    exact = sum(x == y for x, y in half_peaks.values())
    within1 = sum(abs(x - y) <= 1 for x, y in half_peaks.values())
    lag0 = [p["0"] for p in profiles.values() if not np.isnan(p["0"])]
    best = [max(v for v in p.values() if not np.isnan(v)) for p in profiles.values()]
    return {
        "n_chains": len(names),
        "n_pairs": len(profiles),
        "peak_at_lag0_share": at_zero / len(profiles) if profiles else None,
        "mean_r_at_lag0": float(np.mean(lag0)) if lag0 else None,
        "mean_peak_r": float(np.mean(best)) if best else None,
        "split_half_n": len(half_peaks),
        "split_half_exact_agree": exact / len(half_peaks) if half_peaks else None,
        "split_half_within1_agree": within1 / len(half_peaks) if half_peaks else None,
        "chance_exact": 1 / len(lags),
        "chance_within1": 3 / len(lags),
        "peak_lags": peaks,
        "profiles": profiles,
    }


def main() -> int:
    argv = sys.argv[1:]
    metric = next(
        (a.split("=", 1)[1] for a in argv if a.startswith("--metric=")), "revenue"
    )
    statement, key = METRICS[metric]
    rng = np.random.default_rng(20260813)

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        schema = settings.db_schema
        raw = load_series(conn, schema, statement, key)
        chains = chain_map(conn, schema)
        sectors = sector_map(conn, schema)

    growth = {t: g for t, g in ((t, yoy_log_growth(v)) for t, v in raw.items()) if g}
    tickers, quarters, mat = build_panel(growth)
    mat = winsorise(mat)
    print(
        f"{metric}: {len(tickers)} tickers x {len(quarters)} quarters "
        f"{quarters[0]}..{quarters[-1]}  fill={np.count_nonzero(~np.isnan(mat)) / mat.size:.1%}"
    )

    factor, loadings = common_factor(mat)
    resid = residualise(mat, factor)

    corr_raw, _ = pairwise_corr(mat)
    corr_res, olap = pairwise_corr(resid)

    share_raw = eigen_share(corr_raw)
    share_res = eigen_share(corr_res)
    print(
        f"leading eigenvalue share  raw={share_raw[0]:.1%}  residual={share_res[0]:.1%}"
    )

    tax_raw = taxonomy_test(tickers, corr_raw, chains, rng)
    tax_res = taxonomy_test(tickers, corr_res, chains, rng)
    tax_sec = taxonomy_test(tickers, corr_res, chains, rng, sectors=sectors)
    print(
        f"taxonomy delta  raw={tax_raw['delta']:+.4f} (p={tax_raw['perm_p']:.4f})  "
        f"residual={tax_res['delta']:+.4f} (p={tax_res['perm_p']:.4f})"
    )
    if "delta" in tax_sec:
        print(
            f"  same-sector-only control: delta={tax_sec['delta']:+.4f} "
            f"(p={tax_sec['perm_p']:.4f})  pairs {tax_sec['n_same_pairs']}/{tax_sec['n_diff_pairs']}"
        )
    else:
        print(f"  same-sector-only control: {tax_sec}")

    ll = lead_lag(chain_series(tickers, resid, chains))
    print(
        f"lead-lag  {ll['n_chains']} chains / {ll['n_pairs']} pairs  "
        f"peak@0={ll['peak_at_lag0_share']:.1%}  "
        f"r@0={ll['mean_r_at_lag0']:+.3f}  peak_r={ll['mean_peak_r']:+.3f}"
    )
    print(
        f"  split-half peak-lag agreement: exact {ll['split_half_exact_agree']:.1%} "
        f"(chance {ll['chance_exact']:.1%})  within1 {ll['split_half_within1_agree']:.1%} "
        f"(chance {ll['chance_within1']:.1%})  n={ll['split_half_n']}"
    )

    nk = natural_k(corr_res, range(2, 16))
    best_k = max(nk, key=lambda k: nk[k])
    print(
        f"natural k: best={best_k} (silhouette {nk[best_k]:+.4f})  "
        f"k=8 gives {nk['8']:+.4f}  |  "
        + " ".join(f"{k}:{v:+.3f}" for k, v in list(nk.items())[:8])
    )

    cl = cluster(tickers, corr_res)
    peer_r = [v[0][1] for v in cl["knn"].values() if v]
    qs = np.nanquantile(peer_r, [0.1, 0.25, 0.5, 0.75, 0.9])
    print(
        "best-peer r distribution  p10=%.2f p25=%.2f p50=%.2f p75=%.2f p90=%.2f  "
        "share below 0.30: %.1f%%"
        % (*qs, 100 * float(np.mean(np.array(peer_r) < 0.30)))
    )
    co = np.array(list(cl["coherence"].values()))
    cq = np.nanquantile(co, [0.1, 0.25, 0.5, 0.75, 0.9])
    print(
        "peer-set COHERENCE (mean r among the 8 peers)  "
        "p10=%.2f p25=%.2f p50=%.2f p75=%.2f p90=%.2f" % (*cq,)
    )
    for t in ("AMAT", "VRT", "NVDA", "MSFT", "ANET"):
        if t in cl["coherence"]:
            print(f"    {t:5s} coherence {cl['coherence'][t]:+.3f}")
    sweep = knn_sweep(corr_res, resid, rng, range(2, 17))
    print("  k   obs_p50  null_p50  null_p90  share>null_p90 (chance 10%)")
    for k, r in sweep.items():
        star = (
            " <-"
            if r["share_above_null_p90"]
            == max(v["share_above_null_p90"] for v in sweep.values())
            else ""
        )
        print(
            f"  {k:>2}   {r['obs_p50']:6.3f}   {r['null_p50']:7.3f}   "
            f"{r['null_p90']:7.3f}   {r['share_above_null_p90']:12.1%}{star}"
        )
    for lab, mem in sorted(cl["members"].items(), key=lambda kv: -len(kv[1])):
        print(
            f"  cluster {lab}: n={len(mem):3d}  {', '.join(mem[:12])}"
            f"{' ...' if len(mem) > 12 else ''}"
        )

    trace = {
        "metric": metric,
        "n_tickers": len(tickers),
        "quarters": [str(q) for q in quarters],
        "fill_rate": float(np.count_nonzero(~np.isnan(mat)) / mat.size),
        "common_factor": {str(q): float(v) for q, v in zip(quarters, factor)},
        "loadings": {
            t: (None if np.isnan(v) else float(v)) for t, v in zip(tickers, loadings)
        },
        "eigen_share_raw": share_raw,
        "eigen_share_residual": share_res,
        "taxonomy_test_raw": tax_raw,
        "taxonomy_test_residual": tax_res,
        "taxonomy_test_same_sector_only": tax_sec,
        "lead_lag": ll,
        "clusters": cl["members"],
        "natural_k_silhouette": nk,
        "knn_sweep": sweep,
        "knn": cl["knn"],
        "mean_overlap": float(olap[np.triu_indices_from(olap, 1)].mean()),
        "params": {
            "MIN_QUARTERS": MIN_QUARTERS,
            "MIN_OVERLAP": MIN_OVERLAP,
            "MIN_XS": MIN_XS,
            "WINSOR": WINSOR,
            "N_CLUSTERS": N_CLUSTERS,
            "KNN": KNN,
            "PERM": PERM,
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"growth_clusters_{metric}.json"
    path.write_text(json.dumps(trace, indent=1, sort_keys=True))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
