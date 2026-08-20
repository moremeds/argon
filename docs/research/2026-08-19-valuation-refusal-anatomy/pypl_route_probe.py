"""Which company_type can honestly carry PYPL's band?

Run in-container on the mini against the DEPLOYED code, so the answer is what
the job would actually compute rather than a re-derivation:

  ssh macmini "docker exec -i argon-worker-massive-0-1 \
      python /tmp/pypl_route_probe.py"

Compares the two live routings for a payment processor:
  unclassified  -> sales_to_ev  (EV-denominated: subtracts net_debt)
  platform_scale-> fcf_yield    (market-cap denominated: never touches net_debt)
"""

from __future__ import annotations

from pathlib import Path

from uw_scan.config import Settings
from uw_scan.fundamentals.valuation import (
    METHOD_NUMERATOR,
    TYPE_YIELD,
    build_anchors,
)
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.worker.jobs.fundamental_anchors import (
    _history,
    load_raw_closes,
    statement_currencies,
)
from uw_scan.worker.jobs.fundamental_scoring import _knowledge_date

TICKER = "PYPL"


def main() -> None:
    import psycopg

    s = Settings.from_env()
    with psycopg.connect(s.db_dsn()) as conn:
        obs = FundamentalObsRepository(conn, schema=s.db_schema)
        scores = FundamentalScoresRepository(conn, schema=s.db_schema)
        engine = scores.active_version()
        panel = obs.statement_panel([TICKER])
        per = panel[TICKER]
        periods = sorted(per["income-statements"])
        closes = load_raw_closes(Path(s.lake_credit_etf_root), [TICKER])[TICKER]
        ccy = statement_currencies(per, periods)
        spot_date, spot = closes[-1]
        print(f"engine={engine} periods={len(periods)} currencies={ccy}")
        print(f"spot={spot} @ {spot_date}")

        # Raw FCF sign history: the constraint that killed TSLA's band.
        neg = 0
        for i, p in enumerate(periods[-20:], start=max(0, len(periods) - 20)):
            from uw_scan.fundamentals.valuation import quarter_inputs

            qi = quarter_inputs(per, periods, i)
            f = qi.get("fcf")
            if f is not None and f <= 0:
                neg += 1
        print(f"trailing-20 quarters with non-positive TTM fcf: {neg}")

        for ctype in ("unclassified", "platform_scale"):
            method = TYPE_YIELD[ctype]
            hist, latest, li = _history(per, periods, closes, method, currencies=ccy)
            if li < 0:
                print(f"\n{ctype}/{method}: no usable latest quarter")
                continue
            know, _ = _knowledge_date(per, periods[li])
            band = build_anchors(
                ticker=TICKER,
                company_type=ctype,
                history=hist,
                fundamental=latest.get(METHOD_NUMERATOR[method]) or 0.0,
                net_debt=latest.get("net_debt") or 0.0,
                shares=latest.get("shares") or 0.0,
                spot=spot,
                knowledge_age_days=(spot_date - know).days,
            )
            print(f"\n{ctype} / {method}  history_n={len(hist)}")
            print(f"  net_debt={latest.get('net_debt'):,.0f}  shares={latest.get('shares'):,.0f}")
            print(f"  numerator {METHOD_NUMERATOR[method]}={latest.get(METHOD_NUMERATOR[method]):,.0f}")
            print(f"  anchors={band['anchors']}")
            print(f"  pct={band['spot_percentile']} conf={band['confidence']} q={band['history_quarters']}")
            for r in band["confidence_reasons"]:
                print(f"  reason: {r}")


if __name__ == "__main__":
    main()
