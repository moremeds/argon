from uw_scan.sources.uw_flow import flow_rows_from_payload


def test_flow_rows_from_payload_accepts_stringly_numbers():
    rows = flow_rows_from_payload(
        {
            "data": [
                {
                    "underlying_symbol": "tsla",
                    "option_symbol": "TSLA260619P00180000",
                    "expiry": "2026-06-19",
                    "strike": "180",
                    "type": "put",
                    "premium": "820000",
                    "volume": "1800",
                    "open_interest": "620",
                    "side": "ask",
                    "dte": "39",
                }
            ]
        },
        source_label="UW Flow Poll",
    )

    assert rows[0].ticker == "TSLA"
    assert rows[0].premium == 820000
    assert rows[0].open_interest == 620
