#!/usr/bin/env python3
"""Backtest VCG (Volatility-Credit Gap) across the full available history.

Reads:
  - vol_index_daily for VIX, VVIX, and the credit proxy or composite proxies

Recomputes VCG for every aligned trading day. The aligned window is bounded
by the shortest series — usually the credit proxy. Uses adj_close for credit
ETFs (HYG/JNK/LQD distribute monthly; raw close would surface every
ex-dividend drop as a log-return spike).

Three modes, mutually exclusive:
  --proxy HYG               # production single-proxy, run_scope='production'
  --research-proxy JNK      # research single-proxy baseline, run_scope='research'
  --composite-method ...    # research composite basket, run_scope='research'

Persists:
  - uw_scan.regime_backtest_runs (one row per invocation)
  - uw_scan.regime_backtest_daily (one row per aligned trading day post-burn-in)

Usage:
  uv run python scripts/backtest_vcg.py
  uv run python scripts/backtest_vcg.py --proxy LQD --note "LQD proxy A/B"
  uv run python scripts/backtest_vcg.py --research-proxy JNK \
      --note "single-proxy baseline"
  uv run python scripts/backtest_vcg.py --composite-method risk_parity_3 \
      --note "RP3 candidate"
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import math
import sys
from collections import Counter
from datetime import date as _date
from pathlib import Path

import numpy as np
import psycopg

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from uw_scan.cards import vcg_scoring  # noqa: E402
from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION, MIN_BARS  # noqa: E402
from uw_scan.config import Settings  # noqa: E402
from uw_scan.storage.regime_backtest_repository import (  # noqa: E402
    RegimeBacktestRepository,
)

log = logging.getLogger("backtest_vcg")

# Same named events as the CRI backtest — symmetry across indicators.
NAMED_CRASH_DATES = {
    "2008-09-15": "Lehman bankruptcy",
    "2008-10-10": "GFC bottom area",
    "2010-05-06": "Flash crash",
    "2011-08-08": "US credit downgrade",
    "2015-08-24": "Black Monday (China)",
    "2018-02-05": "Volmageddon",
    "2018-12-24": "Q4 selloff trough",
    "2020-02-28": "COVID early break",
    "2020-03-16": "COVID circuit breaker",
    "2022-06-13": "Rate-hike vol",
    "2024-08-05": "Yen-carry unwind",
}

_VALID_PROXIES = ("HYG", "JNK", "LQD")
_COMPOSITE_METHODS = (
    "risk_parity_3",
    "risk_parity_hyjk",
    "hy_minus_ig_spread",
    "equal_weight_3",
)


def _detect_adj_close(conn: psycopg.Connection, schema: str) -> bool:
    """Return True if vol_index_daily has an adj_close column."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema = %s
               AND table_name = 'vol_index_daily'
               AND column_name = 'adj_close'
            """,
            (schema,),
        )
        return cur.fetchone() is not None


def fetch_aligned_series(
    conn: psycopg.Connection,
    schema: str,
    start: _date,
    end: _date,
    symbols: list[str],
    use_adj_close: bool,
    credit_symbols: tuple[str, ...] = _VALID_PROXIES,
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Fetch and align VIX, VVIX, and any credit symbols on shared dates.

    Credit ETFs use COALESCE(adj_close, close) when adj_close is present;
    indices (VIX/VVIX) use raw close. Returns dict of symbol -> np.array
    plus the aligned ISO date list.
    """
    series: dict[str, dict[_date, float]] = {}
    with conn.cursor() as cur:
        for sym in symbols:
            is_credit = sym in credit_symbols
            price_col = (
                "COALESCE(adj_close, close)" if use_adj_close and is_credit else "close"
            )
            cur.execute(
                f"SELECT trade_date, {price_col} FROM {schema}.vol_index_daily "
                "WHERE symbol = %s AND trade_date BETWEEN %s AND %s "
                f"AND {price_col} IS NOT NULL ORDER BY trade_date",
                (sym, start, end),
            )
            series[sym] = {r[0]: float(r[1]) for r in cur.fetchall()}

    if not series:
        return {}, []
    common: set[_date] | None = None
    for sym in symbols:
        keys = set(series.get(sym, {}).keys())
        common = keys if common is None else common & keys
    assert common is not None
    sorted_dates = sorted(common)
    aligned = {
        sym: np.array([series[sym][d] for d in sorted_dates], dtype=float)
        for sym in symbols
    }
    return aligned, [d.isoformat() for d in sorted_dates]


def _single_proxy_daily_rows(
    model: dict[str, np.ndarray],
    dates: list[str],
) -> tuple[list[dict], Counter[str], int, int, int]:
    """Walk every aligned bar from MIN_BARS onward and assemble daily rows
    for the single-proxy path. Returns (rows, interp_counter, ro_count,
    edr_count, bounce_count)."""
    daily_rows: list[dict] = []
    interp_counter: Counter[str] = Counter()
    ro_count = edr_count = bounce_count = 0
    for i in range(MIN_BARS, len(model["residuals"])):
        date_idx = i + 1
        if date_idx >= len(dates):
            break
        day = vcg_scoring._interpretation_for_index(model, i)
        interp = day["interpretation"]
        interp_counter[interp] += 1
        if day["ro"]:
            ro_count += 1
        if day["edr"]:
            edr_count += 1
        if day["bounce"]:
            bounce_count += 1
        raw_score = day.get("vcg_adj")
        score = (
            float(raw_score)
            if raw_score is not None and not math.isnan(float(raw_score))
            else 0.0
        )
        daily_rows.append(
            {
                "trade_date": _date.fromisoformat(dates[date_idx]),
                "score": score,
                "level": interp,
                "payload": {
                    "vcg": day["vcg"],
                    "vcg_adj": day["vcg_adj"],
                    "residual": day["residual"],
                    "beta1_vvix": day["beta1_vvix"],
                    "beta2_vix": day["beta2_vix"],
                    "alpha": day["alpha"],
                    "vix": day["vix"],
                    "vvix": day["vvix"],
                    "credit_price": day["credit_price"],
                    "sign_ok": day["sign_ok"],
                    "ro": day["ro"],
                    "edr": day["edr"],
                    "tier": day["tier"],
                    "bounce": day["bounce"],
                    "pi_panic": day["pi_panic"],
                    "regime": day["regime"],
                },
            }
        )
    return daily_rows, interp_counter, ro_count, edr_count, bounce_count


def _named_crash_window(
    model: dict[str, np.ndarray],
    dates: list[str],
) -> dict[str, list[dict]]:
    iso_to_date_idx = {d: idx for idx, d in enumerate(dates)}
    named: dict[str, list[dict]] = {}
    for iso, _name in NAMED_CRASH_DATES.items():
        if iso not in iso_to_date_idx:
            continue
        date_idx = iso_to_date_idx[iso]
        model_idx = date_idx - 1  # model arrays are length N-1
        window: list[dict] = []
        for offset in (-5, -3, -1, 0, 1, 3, 5):
            mi = model_idx + offset
            if mi < MIN_BARS or mi >= len(model["residuals"]):
                continue
            d = vcg_scoring._interpretation_for_index(model, mi)
            window.append(
                {
                    "offset_d": offset,
                    "vcg": d["vcg"],
                    "vcg_adj": d["vcg_adj"],
                    "beta1": d["beta1_vvix"],
                    "beta2": d["beta2_vix"],
                    "sign_ok": d["sign_ok"],
                    "interpretation": d["interpretation"],
                    "vix": d["vix"],
                }
            )
        if window:
            named[iso] = window
    return named


def _log_named_crash(proxy_label: str, named: dict[str, list[dict]]) -> None:
    log.info("=== VCG ±5d named-crash window (proxy=%s) ===", proxy_label)
    for iso, window in named.items():
        log.info("--- %s %s ---", iso, NAMED_CRASH_DATES[iso])
        log.info("  offset  vcg     vcg_adj  beta1   beta2   sign_ok  interp")
        for w in window:
            vcg_s = f"{w['vcg']:+.2f}" if w["vcg"] is not None else "  nan"
            adj_s = f"{w['vcg_adj']:+.2f}" if w["vcg_adj"] is not None else "  nan"
            b1_s = f"{w['beta1']:+.2f}" if w["beta1"] is not None else "  nan"
            b2_s = f"{w['beta2']:+.2f}" if w["beta2"] is not None else "  nan"
            log.info(
                "  %+d      %s    %s    %s   %s   %s    %s",
                w["offset_d"],
                vcg_s,
                adj_s,
                b1_s,
                b2_s,
                str(w["sign_ok"]).lower(),
                w["interpretation"],
            )


def _build_argparser() -> argparse.ArgumentParser:
    """Argparse construction is factored so the CLI tests can import it
    without invoking main()."""
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2007-01-01")
    p.add_argument("--end", default=_date.today().isoformat())
    p.add_argument("--note", default=None)

    mode = p.add_mutually_exclusive_group(required=False)
    mode.add_argument(
        "--proxy",
        choices=_VALID_PROXIES,
        help="Production single-proxy run (run_scope=production). Default HYG.",
    )
    mode.add_argument(
        "--research-proxy",
        choices=_VALID_PROXIES,
        help=(
            "Research single-proxy baseline for the comparator (run_scope=research)."
        ),
    )
    mode.add_argument(
        "--composite-method",
        choices=_COMPOSITE_METHODS,
        help="Research composite run (run_scope=research).",
    )

    p.add_argument(
        "--vol-window",
        type=int,
        default=63,
        help="Only used with --composite-method (default 63).",
    )
    p.add_argument(
        "--weight-lag",
        type=int,
        default=1,
        help="Only used with --composite-method (default 1).",
    )
    p.add_argument(
        "--weight-artifact-dir",
        default=str(_PROJECT_ROOT / ".artifacts" / "vcg-weights"),
        help="Local dir for composite weight artifact (default .artifacts/vcg-weights).",
    )
    return p


def _composite_daily_rows(
    method: str,
    aligned: dict[str, np.ndarray],
    dates: list[str],
    vol_window: int,
    weight_lag: int,
) -> tuple[
    list[dict],
    Counter[str],
    int,
    int,
    int,
    dict[str, np.ndarray],
    "object",
]:
    """Build composite basket history, run canonical OLS once, walk per-bar.

    Returns (daily_rows, interp_counter, ro_count, edr_count, bounce_count,
    canonical_model, weight_history_df).
    """
    import pandas as pd  # noqa: PLC0415

    from uw_scan.cards.vcg_basket import METHOD_METADATA, build_basket  # noqa: PLC0415
    from uw_scan.cards.vcg_scoring import _compute_vcg_from_returns  # noqa: PLC0415

    meta = METHOD_METADATA[method]
    idx = pd.to_datetime([_date.fromisoformat(d) for d in dates])
    prices_by_proxy = {
        sym: pd.Series(aligned[sym], index=idx, name=sym) for sym in meta.proxies
    }
    basket_ret, weight_history = build_basket(
        prices_by_proxy, method=method, window=vol_window, weight_lag=weight_lag
    )

    # Align VIX/VVIX onto basket's valid-return index
    vix_s = pd.Series(aligned["VIX"], index=idx)
    vvix_s = pd.Series(aligned["VVIX"], index=idx)
    common = basket_ret.dropna().index
    common = common.intersection(vix_s.index).intersection(vvix_s.index)
    common = common.sort_values()

    vix_levels_aligned = vix_s.reindex(common).values
    vvix_levels_aligned = vvix_s.reindex(common).values
    basket_ret_aligned = basket_ret.reindex(common).values
    vix_ret_aligned = np.diff(np.log(vix_levels_aligned), prepend=np.nan)
    vvix_ret_aligned = np.diff(np.log(vvix_levels_aligned), prepend=np.nan)
    basket_levels_aligned = 100.0 * np.exp(np.nan_to_num(basket_ret_aligned).cumsum())

    canonical = _compute_vcg_from_returns(
        vix_ret_aligned,
        vvix_ret_aligned,
        basket_ret_aligned,
        vix_levels_aligned,
        vvix_levels_aligned,
        basket_levels_aligned,
    )
    # canonical model arrays are length len(common), aligned with `common` dates.
    common_iso = [pd.Timestamp(d).date().isoformat() for d in common]

    daily_rows: list[dict] = []
    interp_counter: Counter[str] = Counter()
    ro_count = edr_count = bounce_count = 0
    for i in range(MIN_BARS, len(canonical["residuals"])):
        if i >= len(common_iso):
            break
        day = vcg_scoring._interpretation_for_index(canonical, i)
        interp = day["interpretation"]
        interp_counter[interp] += 1
        if day["ro"]:
            ro_count += 1
        if day["edr"]:
            edr_count += 1
        if day["bounce"]:
            bounce_count += 1
        raw_score = day.get("vcg_adj")
        score = (
            float(raw_score)
            if raw_score is not None and not math.isnan(float(raw_score))
            else 0.0
        )
        weights_today = {
            sym: float(weight_history.reindex(common).iloc[i].get(sym, 0.0))
            if not pd.isna(weight_history.reindex(common).iloc[i].get(sym, np.nan))
            else None
            for sym in meta.proxies
        }
        daily_rows.append(
            {
                "trade_date": _date.fromisoformat(common_iso[i]),
                "score": score,
                "level": interp,
                "payload": {
                    "signal": {
                        "vcg": day["vcg"],
                        "vcg_adj": day["vcg_adj"],
                        "residual": day["residual"],
                        "beta1_vvix": day["beta1_vvix"],
                        "beta2_vix": day["beta2_vix"],
                        "alpha": day["alpha"],
                        "vix": day["vix"],
                        "vvix": day["vvix"],
                        "credit_price": day["credit_price"],
                        "sign_ok": day["sign_ok"],
                        "ro": day["ro"],
                        "edr": day["edr"],
                        "tier": day["tier"],
                        "bounce": day["bounce"],
                        "pi_panic": day["pi_panic"],
                        "regime": day["regime"],
                    },
                    "weights": weights_today,
                },
            }
        )
    return (
        daily_rows,
        interp_counter,
        ro_count,
        edr_count,
        bounce_count,
        canonical,
        weight_history,
    )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = _build_argparser().parse_args()

    # Mode resolution
    if args.composite_method is not None:
        run_scope = "research"
        composite_method = args.composite_method
        selected_proxy: str | None = None
    elif args.research_proxy is not None:
        run_scope = "research"
        composite_method = "single_proxy"
        selected_proxy = args.research_proxy
    else:
        run_scope = "production"
        composite_method = "single_proxy"
        selected_proxy = args.proxy or "HYG"

    start = _date.fromisoformat(args.start)
    end = _date.fromisoformat(args.end)

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        use_adj_close = _detect_adj_close(conn, settings.db_schema)
        if not use_adj_close:
            log.warning(
                "vol_index_daily lacks adj_close column — falling back to raw "
                "close; expect dividend-noise spikes in residuals."
            )

        # Composite path needs all three proxies; single-proxy path only one.
        if composite_method == "single_proxy":
            assert selected_proxy is not None
            symbols = ["VIX", "VVIX", selected_proxy]
        else:
            from uw_scan.cards.vcg_basket import METHOD_METADATA  # noqa: PLC0415

            symbols = ["VIX", "VVIX", *METHOD_METADATA[composite_method].proxies]

        aligned, dates = fetch_aligned_series(
            conn, settings.db_schema, start, end, symbols, use_adj_close
        )

    n = len(dates)
    log.info(
        "aligned %d trading days for run_scope=%s composite_method=%s proxy=%s",
        n,
        run_scope,
        composite_method,
        selected_proxy or composite_method,
    )
    if n < MIN_BARS + 10:
        log.error("not enough data: %d days, need at least %d", n, MIN_BARS + 10)
        return 1

    if composite_method == "single_proxy":
        assert selected_proxy is not None
        model = vcg_scoring.compute_vcg(
            aligned["VIX"], aligned["VVIX"], aligned[selected_proxy]
        )
        (
            daily_rows,
            interp_counter,
            ro_count,
            edr_count,
            bounce_count,
        ) = _single_proxy_daily_rows(model, dates)
        named_crash_window = _named_crash_window(model, dates)
        credit_proxy_label = selected_proxy
        composite_version = str(COMPOSITE_VERSION)
        weight_artifact_extras: dict[str, str | None] = {}
    else:
        (
            daily_rows,
            interp_counter,
            ro_count,
            edr_count,
            bounce_count,
            canonical_model,
            weight_history,
        ) = _composite_daily_rows(
            composite_method,
            aligned,
            dates,
            args.vol_window,
            args.weight_lag,
        )
        # Named-crash window uses the canonical composite model; offsets are
        # relative to the composite's aligned index, not the raw dates list.
        # Reuse helper by passing dates aligned to canonical model.
        from uw_scan.cards.vcg_scoring import (
            RESEARCH_COMPOSITE_VERSIONS,  # noqa: PLC0415
        )

        composite_version = RESEARCH_COMPOSITE_VERSIONS[composite_method]
        from uw_scan.cards.vcg_basket import METHOD_METADATA  # noqa: PLC0415

        meta = METHOD_METADATA[composite_method]
        credit_proxy_label = {
            "risk_parity_3": "COMPOSITE_RP3",
            "risk_parity_hyjk": "COMPOSITE_RP_HYJK",
            "hy_minus_ig_spread": "COMPOSITE_HY_MINUS_IG",
            "equal_weight_3": "COMPOSITE_EQ3",
        }[composite_method]

        # For composite, derive aligned ISO dates from the canonical model's
        # length. canonical_model arrays are length N where N == len(common)
        # in _composite_daily_rows. Reconstruct via per-row dates from
        # daily_rows for named-crash mapping.
        composite_dates_iso = [r["trade_date"].isoformat() for r in daily_rows]
        # named-crash needs the FULL aligned date list (including pre-burn-in
        # rows). Reconstruct by walking canonical model.
        # Simpler: skip named-crash for composite — composite_dates_iso has
        # only post-burn-in rows, sufficient to surface windows around named
        # crashes that fall in-sample.
        idx_lookup = {d: i for i, d in enumerate(composite_dates_iso)}
        named_crash_window = {}
        for iso, _label in NAMED_CRASH_DATES.items():
            if iso not in idx_lookup:
                continue
            i = idx_lookup[iso]
            window: list[dict] = []
            for offset in (-5, -3, -1, 0, 1, 3, 5):
                j = i + offset
                if j < 0 or j >= len(daily_rows):
                    continue
                p = daily_rows[j]["payload"]["signal"]
                window.append(
                    {
                        "offset_d": offset,
                        "vcg": p["vcg"],
                        "vcg_adj": p["vcg_adj"],
                        "beta1": p["beta1_vvix"],
                        "beta2": p["beta2_vix"],
                        "sign_ok": p["sign_ok"],
                        "interpretation": daily_rows[j]["level"],
                        "vix": p["vix"],
                    }
                )
            if window:
                named_crash_window[iso] = window

        # Persist weight artifact
        from uw_scan.sources.lake import (  # noqa: PLC0415
            canonical_input_price_bytes,
            write_weight_artifact_local,
        )

        weight_artifact_dir = Path(args.weight_artifact_dir)
        # Restrict weights to the basket's proxies (drop NaN-only rows)
        wh_for_artifact = weight_history[list(meta.proxies)].dropna(how="all")
        artifact = write_weight_artifact_local(wh_for_artifact, weight_artifact_dir)

        # Input-price hash (long format)
        import pandas as pd  # noqa: PLC0415

        idx_dt = pd.to_datetime([_date.fromisoformat(d) for d in dates])
        input_series: dict[str, pd.Series] = {}
        input_price_field: dict[str, str] = {}
        for sym in symbols:
            input_series[sym] = pd.Series(
                aligned[sym], index=[d.date() for d in idx_dt], name=sym
            )
            input_price_field[sym] = (
                "adj_close" if (sym in _VALID_PROXIES and use_adj_close) else "close"
            )
        input_bytes = canonical_input_price_bytes(
            series_by_symbol=input_series,
            price_field_by_symbol=input_price_field,
        )
        input_data_sha256 = hashlib.sha256(input_bytes).hexdigest()

        weight_artifact_extras = {
            "weight_artifact_sha256": artifact.sha256,
            "weight_artifact_uri": artifact.uri,
            "weight_artifact_key": artifact.key,
            "input_data_sha256": input_data_sha256,
        }

    if not daily_rows:
        log.error("no rows after burn-in (MIN_BARS=%d)", MIN_BARS)
        return 1

    summary = {
        "oos": None,  # No defensible Y-label in V1 — see vcg-methodology.md §6.
        "extras": {
            "credit_proxy": credit_proxy_label,
            "use_adj_close": bool(use_adj_close),
            "named_crash_window": named_crash_window,
            "interpretation_distribution": dict(interp_counter),
            "ro_count": ro_count,
            "edr_count": edr_count,
            "bounce_count": bounce_count,
            "run_scope": run_scope,
            "composite_method": composite_method,
            **(
                {
                    "vol_window": args.vol_window,
                    "weight_lag": args.weight_lag,
                }
                if composite_method != "single_proxy"
                else {}
            ),
            **weight_artifact_extras,
        },
    }

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        rb = RegimeBacktestRepository(conn, schema=settings.db_schema)
        run_id = rb.insert_run(
            indicator="vcg",
            composite_version=composite_version,
            start_date=daily_rows[0]["trade_date"],
            end_date=daily_rows[-1]["trade_date"],
            window_days=vcg_scoring.OLS_WINDOW,
            n_days=len(daily_rows),
            params={
                "proxy": selected_proxy or credit_proxy_label,
                "ols_window": vcg_scoring.OLS_WINDOW,
                "z_window": vcg_scoring.Z_WINDOW,
                "use_adj_close": bool(use_adj_close),
                **(
                    {
                        "composite_method": composite_method,
                        "vol_window": args.vol_window,
                        "weight_lag": args.weight_lag,
                    }
                    if composite_method != "single_proxy"
                    else {}
                ),
            },
            summary=summary,
            note=args.note,
            run_scope=run_scope,
            composite_method=composite_method,
            credit_proxy=credit_proxy_label,
        )
        rb.bulk_insert_daily(run_id, daily_rows)
        rb.mark_run_completed(run_id)

    log.info(
        "VCG backtest persisted: run_id=%d n=%d run_scope=%s "
        "credit_proxy=%s composite_method=%s composite_version=%s",
        run_id,
        len(daily_rows),
        run_scope,
        credit_proxy_label,
        composite_method,
        composite_version,
    )

    _log_named_crash(credit_proxy_label, named_crash_window)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
