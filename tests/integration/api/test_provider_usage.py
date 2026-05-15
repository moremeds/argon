from __future__ import annotations

from datetime import timedelta

from uw_scan.storage.repository import provider_day_bounds


def _seed_provider_usage(repo):
    started_at = provider_day_bounds()[0] + timedelta(hours=1)
    for endpoint, ticker, status_code, status_family, latency in [
        ("iv_rank", "TSLA", 200, "2xx", 20),
        ("greek_exposure", "TSLA", 429, "4xx", 30),
        ("daily_ohlc", "AAPL", 200, "2xx", 40),
    ]:
        provider = "massive" if endpoint == "daily_ohlc" else "uw"
        repo.insert_external_api_request(
            provider=provider,
            endpoint_key=endpoint,
            method="GET",
            path=f"/example/{ticker}/{endpoint}",
            ticker=ticker,
            params={"ticker": ticker},
            status_code=status_code,
            status_family=status_family,
            started_at=started_at,
            finished_at=started_at,
            latency_ms=latency,
            official_daily_count=7 if provider == "uw" else None,
            official_daily_limit=1000 if provider == "uw" else None,
        )
    repo.conn.commit()


def test_provider_usage_summary_returns_provider_day_counts(client, seeded_db_empty_cards):
    _seed_provider_usage(seeded_db_empty_cards)

    response = client.get("/api/provider-usage/summary?provider=all")

    assert response.status_code == 200
    body = response.json()
    assert body["provider_day_start"].endswith("-04:00")
    assert body["provider_day_end"].endswith("-04:00")
    assert body["total_requests"] == 3
    assert body["http_2xx"] == 2
    assert body["http_4xx"] == 1
    assert body["http_5xx"] == 0
    assert body["uw_latest_daily_count"] == 7
    assert body["uw_latest_daily_limit"] == 1000


def test_provider_usage_breakdowns_group_by_endpoint_and_ticker(
    client, seeded_db_empty_cards
):
    _seed_provider_usage(seeded_db_empty_cards)

    endpoints = client.get("/api/provider-usage/endpoints?provider=uw")
    tickers = client.get("/api/provider-usage/tickers?provider=uw")

    assert endpoints.status_code == 200
    assert {row["key"]: row["total_requests"] for row in endpoints.json()["rows"]} == {
        "greek_exposure": 1,
        "iv_rank": 1,
    }
    assert tickers.status_code == 200
    assert tickers.json()["rows"] == [
        {
            "key": "TSLA",
            "total_requests": 2,
            "http_2xx": 1,
            "http_3xx": 0,
            "http_4xx": 1,
            "http_5xx": 0,
            "transport_errors": 0,
            "latency_p95_ms": 30,
        }
    ]


def test_provider_usage_requests_filters_and_bounds_limit(client, seeded_db_empty_cards):
    _seed_provider_usage(seeded_db_empty_cards)

    response = client.get(
        "/api/provider-usage/requests"
        "?provider=uw&ticker=TSLA&status_family=4xx&limit=999"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 500
    assert len(body["rows"]) == 1
    assert body["rows"][0]["endpoint_key"] == "greek_exposure"
    assert body["rows"][0]["params"] == {"ticker": "TSLA"}


def test_provider_usage_rejects_invalid_provider(client, seeded_db_empty_cards):
    response = client.get("/api/provider-usage/summary?provider=internal")

    assert response.status_code == 422
