"""Pipeline orchestration for the Single-Stock Card.

Sequential fetches → persist raw + audit + typed → assemble report → score → persist.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import timedelta
from decimal import Decimal

import psycopg

from . import normalize, scoring
from .api.client import LiveDataUnavailable, UwClient
from .config import Settings
from .models import MarketAggregates, ScanReport, ScanTickerResult, SingleStockReport
from .reports.scan import assemble_scan_report
from .reports.single_stock import (
    assemble_single_stock_report,
    build_trade_plan_for_report,
)
from .reports.trade_insights import (
    ASSEMBLER_VERSION,
    _stable_payload_hash,
    assemble_trade_insights,
)
from .scan_universe import S2_UNIVERSE
from .sources import uw as uw_sources
from .storage.repository import Repository

logger = logging.getLogger(__name__)


def _next_friday(today: _date) -> _date:
    """Pick the next Friday (today + 1..7 days)."""
    days_ahead = (4 - today.weekday()) % 7 or 7
    return today + timedelta(days=days_ahead)


def _persist_trade_insights_for_run(
    *,
    repo: Repository,
    report: SingleStockReport,
) -> None:
    response = assemble_trade_insights(
        ticker=report.ticker,
        run_id=report.run_id,
        repo=repo,
        as_of=report.generated_at,
        spot=report.market_structure.spot,
    )
    payload = response.model_dump(mode="json")
    snapshot_id = repo.upsert_trade_insight_snapshot(
        run_id=report.run_id,
        ticker=report.ticker,
        as_of=response.as_of,
        assembler_version=ASSEMBLER_VERSION,
        input_hash=_stable_payload_hash(payload),
        payload=payload,
    )
    repo.replace_trade_insight_candidates(
        snapshot_id=snapshot_id,
        run_id=report.run_id,
        ticker=report.ticker,
        candidates=payload["candidate_structures"],
    )


def run_single_stock(
    ticker: str, client: UwClient, repo: Repository
) -> SingleStockReport:
    """Run the full S1 pipeline against UW for `ticker` and persist everything."""
    ticker = ticker.upper()
    run_id = repo.insert_scan_run(ticker)
    logger.info("started scan run %d for %s", run_id, ticker)

    try:
        # 1. Flow alerts (filtered to this ticker via param)
        flow_alerts = uw_sources.fetch_flow_alerts(client, repo, run_id, ticker)
        # Defensive: keep only this ticker
        ticker_alerts = [a for a in flow_alerts if a.ticker == ticker]
        repo.insert_flow_events(run_id, ticker, ticker_alerts)

        # 2. IV rank (time series)
        iv_rank_rows = uw_sources.fetch_iv_rank(client, repo, run_id, ticker)
        repo.upsert_iv_rank_rows(ticker, iv_rank_rows)

        # 3. Vol stats
        vol_stats_rows = uw_sources.fetch_volatility_stats(client, repo, run_id, ticker)
        repo.upsert_volatility_stats_rows(vol_stats_rows)

        # 4. Realized vol (time series)
        rv_rows = uw_sources.fetch_realized_volatility(client, repo, run_id, ticker)
        repo.upsert_realized_vol_rows(ticker, rv_rows)

        # 5. Term structure
        term_rows = uw_sources.fetch_term_structure(client, repo, run_id, ticker)
        repo.insert_iv_term_rows(run_id, term_rows)

        # 6. Interpolated IV
        interp_rows = uw_sources.fetch_interpolated_iv(client, repo, run_id, ticker)
        repo.insert_interpolated_iv_rows(run_id, ticker, interp_rows)

        # Pick the nearest expiry from term structure for expiry-required calls.
        nearest_expiry: _date | None = None
        if term_rows:
            sorted_term = sorted(term_rows, key=lambda r: r.expiry)
            nearest_expiry = sorted_term[0].expiry
        if nearest_expiry is None:
            nearest_expiry = _next_friday(_date.today())
        expiry_str = nearest_expiry.isoformat()

        # 7. Skew
        skew_rows = uw_sources.fetch_skew(client, repo, run_id, ticker, expiry_str)
        repo.upsert_skew_rows(ticker, skew_rows)

        # 8. Greek exposure (strike-expiry)
        ge_rows = uw_sources.fetch_greek_exposure(
            client, repo, run_id, ticker, expiry_str
        )
        repo.insert_greek_exposure_rows(run_id, ticker, ge_rows)

        # 8b. Persist the per-strike, per-expiry GEX curve as JSONB on the run row
        curve: list[dict] = []
        for r in ge_rows:
            net = None
            if r.call_gex is not None or r.put_gex is not None:
                net = str((r.call_gex or 0) + (r.put_gex or 0))
            curve.append(
                {
                    "strike": str(r.strike),
                    "expiry": r.expiry.isoformat(),
                    "net_gex": net,
                    "call_gex": str(r.call_gex) if r.call_gex is not None else None,
                    "put_gex": str(r.put_gex) if r.put_gex is not None else None,
                }
            )
        repo.set_strike_gex_curve(run_id, curve)

        # 9. Spot exposures (we already persisted in 8 via exposures table; spot row stored only as raw + audit)
        _ = uw_sources.fetch_spot_exposures(client, repo, run_id, ticker, expiry_str)

        # 10. Greeks
        greeks_rows = uw_sources.fetch_greeks(client, repo, run_id, ticker, expiry_str)
        repo.insert_greeks_rows(run_id, ticker, greeks_rows)

        # 11. OI per strike
        oi_strike_rows = uw_sources.fetch_oi_per_strike(client, repo, run_id, ticker)
        repo.upsert_oi_per_strike_rows(ticker, oi_strike_rows)

        # 12. OI change
        oi_change_rows = uw_sources.fetch_oi_change(client, repo, run_id, ticker)
        repo.insert_oi_change_rows(run_id, oi_change_rows)

        # 13. Max pain
        max_pain_rows = uw_sources.fetch_max_pain(client, repo, run_id, ticker)
        # market_date for max pain — use nearest_expiry as date hint isn't in row
        market_date = _date.today()
        repo.insert_max_pain_rows(run_id, ticker, market_date, max_pain_rows)

        # 14. Option contracts (broad)
        contracts = uw_sources.fetch_option_contracts(client, repo, run_id, ticker)
        repo.insert_option_contract_rows(run_id, ticker, contracts)

        # 15. Option contracts by symbol (pick 2 ATM contracts from previous batch)
        if contracts:
            picks = [c.option_symbol for c in contracts[:2]]
            refined = uw_sources.fetch_option_contracts_by_symbol(
                client, repo, run_id, ticker, picks
            )
            repo.insert_option_contract_rows(run_id, ticker, refined)

        # 16. Dark pool
        dp_rows = uw_sources.fetch_darkpool_ticker(client, repo, run_id, ticker)
        repo.insert_dark_pool_rows(run_id, dp_rows)

        # 17. Short data — pick latest snapshot only
        short_rows = uw_sources.fetch_short_data(client, repo, run_id, ticker)
        latest_short = normalize.latest_by_timestamp(short_rows)
        if latest_short is not None:
            repo.insert_short_interest_snapshot(run_id, latest_short)

        # Assemble report
        report = assemble_single_stock_report(ticker, run_id, repo)

        # Score + persist
        setup = scoring.classify_setup_c(report)
        if setup is not None:
            report.setup = setup
            # Build trade plan from contract snapshots in DB
            contract_rows = repo.fetch_option_contracts(run_id, ticker)
            trade_plan = build_trade_plan_for_report(report, contract_rows)
            if trade_plan is not None:
                report.trade_plan = trade_plan

        # Persist opportunity_scores — always at least one row per run
        if setup is not None:
            score_val = setup.score
            setup_types = [setup.setup_type]
            direction = setup.direction
            confirmations = setup.confirmations
            warnings = setup.warnings
            notes = setup.notes
        else:
            score_val = Decimal("0")
            setup_types = []
            direction = None
            confirmations = []
            warnings = ["did not meet Type C criteria"]
            notes = "no classification"

        repo.insert_opportunity_score(
            run_id,
            ticker,
            score_val,
            setup_types,
            direction,
            confirmations,
            warnings,
            notes,
        )

        # Structure idea — always emit at least the bull-call-spread sketch when bull setup
        if report.trade_plan is not None:
            legs_dicts = [
                {
                    "option_symbol": leg.option_symbol,
                    "side": leg.side,
                    "strike": str(leg.strike),
                    "expiry": leg.expiry.isoformat(),
                    "mid": str(leg.mid) if leg.mid is not None else None,
                }
                for leg in report.trade_plan.legs
            ]
            repo.insert_structure_idea(
                run_id,
                ticker,
                report.trade_plan.structure,
                legs_dicts,
                report.trade_plan.rationale,
            )

        # 18. Per-ticker bulk-screener — feeds MarketAggregates on the report.
        screener_row = uw_sources.fetch_bulk_screener_ticker(
            client, repo, run_id, ticker
        )
        if screener_row is not None:
            pcr_vol = None
            if screener_row.put_volume and screener_row.call_volume:
                pcr_vol = Decimal(screener_row.put_volume) / Decimal(
                    screener_row.call_volume
                )
            aggregates = MarketAggregates(
                call_oi_total=screener_row.call_open_interest,
                put_oi_total=screener_row.put_open_interest,
                call_volume_total=screener_row.call_volume,
                put_volume_total=screener_row.put_volume,
                call_volume_ask_side=screener_row.call_volume_ask_side,
                call_volume_bid_side=screener_row.call_volume_bid_side,
                put_volume_ask_side=screener_row.put_volume_ask_side,
                put_volume_bid_side=screener_row.put_volume_bid_side,
                pcr_oi=screener_row.put_call_ratio,
                pcr_vol=pcr_vol,
                iv30d=screener_row.iv30d,
            )
            report.aggregates = aggregates
            repo.set_aggregates(run_id, aggregates)

            # 19. Append PCR snapshot for 30d-delta computation later.
            if aggregates.pcr_oi is not None or aggregates.pcr_vol is not None:
                repo.append_pcr_history(
                    ticker=ticker,
                    snapshot_date=_date.today(),
                    pcr_oi=aggregates.pcr_oi,
                    pcr_vol=aggregates.pcr_vol,
                )

        try:
            _persist_trade_insights_for_run(repo=repo, report=report)
        except Exception as exc:  # noqa: BLE001 — research-log only; never block a scan
            logger.warning(
                "trade_insights persistence failed for %s run_id=%s: %s",
                report.ticker,
                report.run_id,
                repr(exc),
            )

        repo.finish_scan_run(run_id, status="ok")
        repo.conn.commit()
        logger.info("finished scan run %d for %s", run_id, ticker)
        return report

    except Exception as exc:  # noqa: BLE001
        repo.conn.rollback()
        repo.finish_scan_run(run_id, status=f"failed: {repr(exc)[:200]}")
        repo.conn.commit()
        logger.exception("scan run %d failed: %s", run_id, repr(exc))
        raise


def _build_scan_result(row, setup, signals) -> ScanTickerResult:
    """Shape a screener row + classification into a ScanTickerResult."""
    net_premium = None
    ncp = row.net_call_premium
    npp = row.net_put_premium
    if ncp is not None or npp is not None:
        ncp_d = ncp if ncp is not None else Decimal("0")
        npp_d = npp if npp is not None else Decimal("0")
        net_premium = ncp_d - npp_d

    if setup is None:
        return ScanTickerResult(
            ticker=row.ticker,
            setup_type=None,
            label=None,
            direction=None,
            score=Decimal("0"),
            net_premium=net_premium,
            net_call_premium=row.net_call_premium,
            net_put_premium=row.net_put_premium,
            iv_rank=row.iv_rank,
            sector=row.sector,
            relative_volume=row.relative_volume,
            gex_net_change=row.gex_net_change,
            variance_risk_premium=row.variance_risk_premium,
            total_open_interest=row.total_open_interest,
            next_earnings_date=row.next_earnings_date,
            signals_present=list(signals),
            confirmations=[],
            warnings=["did not meet Type C or Type F"],
            notes="unclassified",
            screener_row=row,
        )

    return ScanTickerResult(
        ticker=row.ticker,
        setup_type=setup.setup_type,
        label=setup.label,
        direction=setup.direction,
        score=setup.score,
        net_premium=net_premium,
        net_call_premium=row.net_call_premium,
        net_put_premium=row.net_put_premium,
        iv_rank=row.iv_rank,
        sector=row.sector,
        relative_volume=row.relative_volume,
        gex_net_change=row.gex_net_change,
        variance_risk_premium=row.variance_risk_premium,
        total_open_interest=row.total_open_interest,
        next_earnings_date=row.next_earnings_date,
        signals_present=list(signals),
        confirmations=list(setup.confirmations),
        warnings=list(setup.warnings),
        notes=setup.notes,
        screener_row=row,
    )


def run_full_scan(
    client: UwClient,
    repo: Repository,
    universe: tuple[str, ...] | list[str] | None = None,
) -> ScanReport:
    """Run the S2 Full Scan: bulk screener → filter to universe → score → persist.

    A single `/api/screener/stocks` call returns up to 100 S&P 500 tickers; this
    function filters the response to the requested universe, classifies each row
    (Type F preferred, Type C fallback, else unclassified), persists scan_universe
    and scan_results, and returns the assembled ScanReport.
    """
    use_universe = tuple(universe) if universe is not None else S2_UNIVERSE
    universe_set = {t.upper() for t in use_universe}

    # Reuse the scan_runs table; mark this run with a synthetic ticker label.
    run_id = repo.insert_scan_run("__FULL_SCAN__", notes="S2 full scan")
    logger.info(
        "started full scan run %d (universe size=%d)", run_id, len(universe_set)
    )

    try:
        repo.insert_scan_universe(run_id, list(use_universe))

        rows = uw_sources.fetch_bulk_screener(client, repo, run_id)
        by_ticker = {r.ticker.upper(): r for r in rows}

        matched = [(t, by_ticker[t]) for t in universe_set if t in by_ticker]
        dropped = sorted(universe_set - set(by_ticker.keys()))
        if dropped:
            logger.warning(
                "scan run %d: %d universe tickers absent from screener response: %s",
                run_id,
                len(dropped),
                dropped,
            )

        results: list[ScanTickerResult] = []
        for _ticker, row in matched:
            f_setup = scoring.classify_setup_f(row)
            if f_setup is not None:
                signals = scoring.detect_f_signals(row)
                results.append(_build_scan_result(row, f_setup, signals))
                continue
            c_setup = scoring.classify_setup_c_from_row(row)
            if c_setup is not None:
                results.append(_build_scan_result(row, c_setup, []))
                continue
            # Unclassified — still emit a row for visibility / ranking.
            results.append(_build_scan_result(row, None, []))

        # Rank by score desc, then ticker asc for determinism
        results.sort(key=lambda r: (-r.score, r.ticker))

        repo.insert_scan_results(run_id, results)
        repo.finish_scan_run(run_id, status="ok")
        repo.conn.commit()
        logger.info(
            "finished full scan run %d: %d/%d tickers classified",
            run_id,
            sum(1 for r in results if r.setup_type is not None),
            len(results),
        )

        return assemble_scan_report(run_id, repo)

    except Exception as exc:  # noqa: BLE001
        repo.conn.rollback()
        repo.finish_scan_run(run_id, status=f"failed: {repr(exc)[:200]}")
        repo.conn.commit()
        logger.exception("full scan run %d failed: %s", run_id, repr(exc))
        raise


def run_single_stock_for_ticker_via_env(ticker: str) -> SingleStockReport:
    """Convenience entry — load Settings, open client + DB conn, run pipeline."""
    settings = Settings.from_env()
    if not settings.api_key.get_secret_value():
        raise LiveDataUnavailable(
            "UW_SCAN_API_KEY missing — refusing to fabricate data."
        )
    conn = psycopg.connect(settings.db_dsn())
    try:
        repo = Repository(conn, schema=settings.db_schema)
        with UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
        ) as client:
            return run_single_stock(ticker, client, repo)
    finally:
        conn.close()
