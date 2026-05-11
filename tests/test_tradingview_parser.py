from uw_scan.sources.tradingview import parse_tradingview_watchlist_html
from uw_scan.sources.tradingview_browser import parse_tradingview_rendered_html


def test_parse_embedded_symbols_from_fixture_html():
    html = """
    <html>
      <head><title>portfolio(update daily) - TradingView</title></head>
      <body>
        <script id="watchlist-data" type="application/json">
          {"symbols":["NASDAQ:NVDA","NASDAQ:AMD","NYSE:TSLA"]}
        </script>
      </body>
    </html>
    """

    result = parse_tradingview_watchlist_html(
        html,
        source_url="https://www.tradingview.com/watchlists/326877343/",
    )

    assert result.source_label == "portfolio(update daily)"
    assert result.symbols == ["NVDA", "AMD", "TSLA"]
    assert result.status == "ok"


def test_parse_static_page_without_symbols_returns_nonblocking_failure():
    html = "<html><head><title>portfolio(update daily) - TradingView</title></head><body>No symbols here</body></html>"

    result = parse_tradingview_watchlist_html(
        html,
        source_url="https://www.tradingview.com/watchlists/326877343/",
    )

    assert result.source_label == "portfolio(update daily)"
    assert result.symbols == []
    assert result.status == "no_symbols_found"
    assert "browser-rendered retrieval" in result.message


def test_parse_rendered_page_symbols_from_accessible_text():
    html = """
    <html>
      <head><title>portfolio(update daily) - TradingView</title></head>
      <body>
        <span>NASDAQ:NVDA</span><span>NASDAQ:AMD</span><span>NYSE:TSLA</span>
      </body>
    </html>
    """

    result = parse_tradingview_rendered_html(
        html,
        source_url="https://www.tradingview.com/watchlists/326877343/",
    )

    assert result.status == "ok"
    assert result.symbols == ["NVDA", "AMD", "TSLA"]
