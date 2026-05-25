from uw_scan.benchmark.pipeline import (
    BenchmarkInputs,
    ComponentScores,
    classify_status,
    compute_component_scores,
    weighted_score,
)


def test_weighted_score_uses_documented_weights() -> None:
    scores = ComponentScores(
        freshness=100,
        coverage=80,
        throughput=60,
        provider=40,
        worker=100,
        persistence=50,
    )

    assert weighted_score(scores) == 76


def test_classify_status_bands() -> None:
    assert classify_status(85) == "OK"
    assert classify_status(84) == "DEGRADED"
    assert classify_status(60) == "DEGRADED"
    assert classify_status(59) == "CRITICAL"


def test_coverage_penalizes_missing_scanner_tickers() -> None:
    inputs = BenchmarkInputs(
        watchlist_size=100,
        scanner_fresh_count=70,
        scanner_stale_count=20,
        scanner_dead_count=10,
        record_health_ok=True,
    )

    scores, reasons = compute_component_scores(inputs)

    assert scores.coverage < 80
    assert any(reason.component == "coverage" for reason in reasons)


def test_freshness_does_not_penalize_wall_clock_age_without_expected_misses() -> None:
    inputs = BenchmarkInputs(
        watchlist_size=100,
        scanner_fresh_count=100,
        last_full_scan_age_seconds=34.5 * 3600,
        expected_full_scan_miss_count=0,
    )

    scores, reasons = compute_component_scores(inputs)

    assert scores.freshness == 100
    assert not any("expected full scans missed" in reason.message for reason in reasons)


def test_freshness_penalizes_missed_expected_full_scans() -> None:
    inputs = BenchmarkInputs(
        watchlist_size=100,
        scanner_fresh_count=100,
        last_full_scan_age_seconds=34.5 * 3600,
        expected_full_scan_miss_count=3,
        full_scan_expected_lag_seconds=3 * 3600,
    )

    scores, reasons = compute_component_scores(inputs)

    assert scores.freshness == 80
    assert any("3 expected full scans missed" in reason.message for reason in reasons)
