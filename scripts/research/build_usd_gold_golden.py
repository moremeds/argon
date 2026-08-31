"""Freeze the MC3 Part B golden fixture from live publishers.

Reproduce:
    uv run python scripts/research/build_usd_gold_golden.py

Every value is fetched from the publisher at authoring time and frozen with the instant
that made it knowable.  The ``expect`` blocks are preregistered predictions written before
the USD and gold engines existed; regenerating this file must never be used to edit them
to match whatever the engines produce.  The generator refuses to overwrite an existing
``expect`` block and merges freshly fetched inputs under the predictions already on disk.

Every input row carries ``owned_by``.  That field is the double-count prohibition made
checkable: a USD scenario reads EFFR and DFII10 rows tagged ``policy_rates``, so a test
can assert USD referenced them as upstream rather than claiming them as its own factors.
Spec 1 states the rule; this is where it becomes falsifiable.
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any
from pathlib import Path

import httpx
from dotenv import load_dotenv

from uw_scan.sources.etf_holdings import EtfHoldingsProvider

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "fixtures" / "macro" / "usd_gold_golden.json"
SPEC = "docs/superpowers/archive/specs/2026-08-12-usd-gold-state-design.md"

FRED = "https://api.stlouisfed.org/fred/series/observations"
MASSIVE = "https://api.massive.com"

#: FRED's daily vintage window, and the reason scenario 4 exists.  ``request_window()``
#: splits on the contract's own frequency: a daily series is bounded here because the
#: unbounded window exceeds FRED's 2000-vintage cap, a monthly one is not bounded at all.
#: So DTWEXBGS (daily) has no vintage in the store before this date while RTWEXBGS
#: (monthly) has one going back decades -- which is precisely the substitution the USD
#: state must refuse.
DAILY_VINTAGE_START = "2021-01-01"
ALL_VINTAGES_END = "9999-12-31"


def _client() -> httpx.Client:
    # trust_env=False: httpx would otherwise fall through to getproxies(), which on macOS
    # reads the system network pane.  Four rates clients froze on exactly that, and the
    # Linux container was immune, so a green prod is not evidence the call is safe.
    return httpx.Client(timeout=120.0, trust_env=False, follow_redirects=True)


def _get_with_retry(
    client: httpx.Client, url: str, params: dict[str, Any], **kw: Any
) -> httpx.Response:
    """FRED answers a transient 502 often enough to lose a ten-call run.

    Retries only 5xx.  A 4xx is the publisher telling us the request is wrong -- retrying
    it would turn "this series does not exist" into "the network is slow", which is the
    distinction the probe exists to keep.
    """
    for attempt in range(3):
        response = client.get(url, params=params, **kw)
        if response.status_code < 500 or attempt == 2:
            if response.is_error:
                # NOT raise_for_status(): it embeds the full request URL in the message,
                # and FRED takes its api_key as a QUERY PARAMETER -- so the obvious call
                # prints the key into any terminal or CI log that captures the traceback.
                raise SystemExit(
                    f"{url} returned HTTP {response.status_code} "
                    f"for {_redacted(params)}"
                )
            return response
        print(f"  retry {attempt + 1}/2 after HTTP {response.status_code}")
    raise AssertionError("unreachable")


def _redacted(params: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if "key" in k.lower() else v) for k, v in params.items()}


def fetch_fred(
    client: httpx.Client,
    series_id: str,
    start: str,
    end: str,
    key: str,
    *,
    causal_role: str,
    owned_by: str,
    unit: str,
    daily: bool = True,
    as_of: str | None = None,
) -> list[dict[str, Any]]:
    """Observations with the vintage window that makes each one point-in-time readable.

    ``realtime_start`` is the day the value became the published value and is the ONLY
    availability a FRED observation has.  ``realtime_end`` is the day it stopped being
    the published value -- ``9999-12-31`` means it still is.  A row without both cannot be
    replayed, which is the entire point of the fixture.

    ``as_of`` pins the real-time window to a single past day, which is how scenario 4 asks
    "what did the store hold on that date" rather than "what does FRED hold now".
    """
    params: dict[str, Any] = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": start,
        "observation_end": end,
    }
    if as_of is not None:
        params |= {"realtime_start": as_of, "realtime_end": as_of}
    elif daily:
        params |= {
            "realtime_start": DAILY_VINTAGE_START,
            "realtime_end": ALL_VINTAGES_END,
        }
    response = _get_with_retry(client, FRED, params)
    return [
        {
            "series_id": series_id,
            "causal_role": causal_role,
            "owned_by": owned_by,
            "period_end": row["date"],
            "available_at": row["realtime_start"],
            # An as_of-pinned query makes ALFRED report realtime_end == as_of for every
            # row: that is where the QUERY window closes, not where the vintage did.
            # Recording it would claim each value stopped being current on the replay
            # date, which is the opposite of what the scenario is testing.
            "superseded_at": None
            if as_of is not None or row["realtime_end"] == ALL_VINTAGES_END
            else row["realtime_end"],
            "value": row["value"],
            "unit": unit,
            "source": "fred",
            "source_kind": "first_party_publisher",
            "cost_class": "free_publisher",
        }
        for row in response.json()["observations"]
        if row["value"] != "."
    ]


def fetch_gld_close(
    client: httpx.Client, start: str, end: str, key: str
) -> list[dict[str, Any]]:
    """GLD daily closes -- the gold price the orchestrator already reads as GLD_CLOSE.

    FRED's LBMA gold fix (``GOLDPMGBD228NLBM``) was retired and now answers HTTP 400, and
    the standing data-source rule bans Yahoo, so the traded ETF close is the free gold
    price this desk actually has.  It is a real instrument at a real settled price, not a
    spot quote: the fixture says so rather than letting a later reader assume otherwise.

    A daily bar has no vintage.  ``available_at`` is the session close, which is the
    earliest instant the number existed at all -- conservative in the only direction that
    matters.
    """
    response = _get_with_retry(
        client,
        f"{MASSIVE}/v2/aggs/ticker/GLD/range/1/day/{start}/{end}",
        {"adjusted": "true", "limit": 50000},
        headers={"Authorization": f"Bearer {key}"},
    )
    out = []
    for bar in response.json().get("results") or []:
        day = datetime.fromtimestamp(bar["t"] / 1000, tz=UTC).date().isoformat()
        out.append(
            {
                "series_id": "GLD_CLOSE",
                "causal_role": "decomposition_component",
                "owned_by": "gold",
                "period_end": day,
                "available_at": day,
                "superseded_at": None,
                "value": str(bar["c"]),
                "unit": "usd_per_share",
                "source": "massive.com",
                "source_kind": "vendor",
                "cost_class": "paid_vendor",
            }
        )
    return sorted(out, key=lambda row: row["period_end"])


def fetch_gld_holdings(start: date, end: date) -> list[dict[str, Any]]:
    """SPDR's own daily holdings archive -- Lens 1 structural flow, from the issuer.

    Tonnage in the trust is a custody fact the sponsor publishes about itself, which is
    why it is ``official`` while the price of the same fund is ``vendor``: one is the
    issuer reporting its own bar list, the other is a market print resold to us.
    """
    with EtfHoldingsProvider() as provider:
        rows = provider.fetch_gld(start=start)
    return [
        {
            "series_id": "GLD_HOLDINGS_OZ",
            "causal_role": "positioning",
            "owned_by": "gold",
            "period_end": row.obs_date.isoformat(),
            "available_at": row.obs_date.isoformat(),
            "superseded_at": None,
            "value": str(row.holdings_oz),
            "unit": "troy_oz",
            "source": "spdrgoldshares",
            "source_kind": "official",
            "cost_class": "free_official",
        }
        for row in rows
        if row.holdings_oz is not None and row.obs_date <= end
    ]


# Preregistered predictions.  Written before the engines exist; never edited to match output.
EXPECT: dict[str, dict[str, Any]] = {
    "usd_strength_against_easing_policy": {
        "usd_state": "STRENGTHENING",
        "contradictions_include": ["usd_against_relative_policy"],
        "policy_direction_inferred": None,
        "policy_actual_is_upstream_reference": True,
        "note": (
            "Window 2024-09-16 to 2024-12-31, replayed at as_of 2025-01-08 -- the first "
            "date the whole window was knowable, because the H.10 releases weekly in "
            "arrears and an as_of of 2024-12-31 cannot see 2024-12-31. The broad dollar "
            "rises 121.7684 -> 129.4880, +6.34%, while EFFR falls 5.33 -> 4.33 across "
            "three cuts. Those are the POINT-IN-TIME values: the vintage in force today "
            "reads 121.4976 -> 129.2775 (+6.40%), restated on 2026-02-02, and a replay "
            "that quoted it would be reading the 2026 annual revision into 2024. "
            "Easing is supposed to weaken "
            "a currency and the measured move is the opposite, so the contradiction is the "
            "output and no direction for policy is read back out of the dollar. The USD "
            "state is STRENGTHENING because that is what the anchor did; the contradiction "
            "sits beside it and does not soften it into a hedge. EFFR is tagged "
            "owned_by=policy_rates: USD reads it through the rates state, and a test that "
            "sees USD claim it as its own factor has found the double-count spec 1 forbids."
        ),
    },
    "gold_and_real_yields_decoupled_post_2022": {
        "regime": "post_2022",
        "regime_gate_load_bearing": True,
        "contradictions_include": ["gold_against_real_yields_post_2022"],
        "lens2_direction_inferred": None,
        "note": (
            "Window 2025-10-01 to 2025-12-31, replayed at as_of 2026-01-08. GLD closes "
            "356.03 -> 396.31, +11.3%, while the 10y real yield rises 1.77 -> 1.93. "
            "The pre-2022 relationship is that gold falls "
            "when real yields rise -- a higher real rate is a higher carrying cost for a "
            "zero-coupon asset -- and both legs rise together here. The gate is what makes "
            "this reportable rather than an error: a Lens 2 fitted across the break would "
            "average a negative relationship with a broken one and describe neither. The "
            "contradiction fires; it does not resolve into a view on gold."
        ),
    },
    "strong_official_flows_against_adverse_cyclical": {
        "lens1_flow": "STRONG",
        "lens2_cyclical": "ADVERSE",
        "lens_precedence": None,
        "contradictions_include": ["gold_flow_against_cyclical"],
        "note": (
            "Window 2024-08-19 to 2024-10-23, replayed at as_of 2024-10-30 once the "
            "H.10 had published the last of it. GLD tonnage rises 4.05% -- real "
            "accumulation into the trust, not a price effect, because holdings are "
            "counted in ounces -- while the 10y real yield rises 14bp (1.79 -> 1.93) and "
            "the broad dollar rises 2.24% (122.1762 -> 124.9181). Both cyclical "
            "legs are adverse and the flow leg is strong. Neither lens is allowed to "
            "overwrite the other and there is no precedence rule: the state reports a "
            "strong flow and an adverse cyclical backdrop as two findings, because "
            "collapsing them would throw away the only information the disagreement "
            "carries. This window overlaps scenario 1's on the calendar and that is fine "
            "-- one period can be evidence for two different questions."
        ),
    },
    "usd_anchor_absent_state_abstains": {
        "usd_state": "UNKNOWN",
        "anchor_series": "DTWEXBGS",
        "anchor_periods_in_fixture_gt": 0,
        "anchor_rows_passing_available_at": 0,
        "substituted_series": None,
        "real_index_available_but_unused": True,
        "note": (
            "as_of 2020-06-30. DTWEXBGS is a daily contract, so its ingest window begins at "
            "DAILY_VINTAGE_START=2021-01-01 and every vintage the store holds carries "
            "available_at >= 2021-01-01 -- the periods are in the fixture, and not one of "
            "them passes available_at <= as_of. FRED's own history reaches back to 2006, "
            "but what we could have read is what counts. RTWEXBGS is monthly, so its "
            "window is unbounded and it DOES "
            "have a vintage there: 112.9934 for period 2020-05-01. That is the whole "
            "scenario. The substitute is present, plausible, and named in the same spec, "
            "and the state must still abstain -- a nominal index and a CPI-deflated one "
            "answer different questions, and quietly swapping them would report an "
            "inflation differential as a dollar move. UNKNOWN with the anchor named, not a "
            "degraded reading from the sibling."
        ),
    },
    "broad_dollar_revised_after_the_fact": {
        "replay_reads_vintage_in_force": True,
        "period": "2026-08-03",
        "value_at_2026_08_12": "120.7739000000",
        "value_at_2026_08_20": "119.6951000000",
        "revision_penalty_fires": True,
        "revision_penalty_is_correct": True,
        "note": (
            "Period 2026-08-03 was published at 120.7739 on 2026-08-10 and restated to "
            "119.6951 on 2026-08-17 -- 1.08 index points, a tenth of the whole 2024 dollar "
            "rally, silently. A replay at 2026-08-12 must read 120.7739 and one at "
            "2026-08-20 must read 119.6951; reading the latest value at both is the bug, "
            "and it is invisible without a fixture that carries the superseded vintage. "
            "The Fed restates this index on 1,265 periods against zero for SOFR, EFFR and "
            "RRPONTSYD, so compute_confidence's revision_penalty fires on USD in normal "
            "operation. A USD state carrying revision drag is correct and must not be "
            "tuned away -- the penalty is reporting a real property of the publisher."
        ),
    },
}


def main() -> None:
    load_dotenv(ROOT / ".env")
    key = os.environ.get("FRED_API_KEY")
    massive_key = os.environ.get("MASSIVE_API_KEY")
    if not key or not massive_key:
        raise SystemExit("FRED_API_KEY and MASSIVE_API_KEY are required")

    client = _client()

    def usd(series_id: str, start: str, end: str, **kw: Any) -> list[dict[str, Any]]:
        return fetch_fred(
            client,
            series_id,
            start,
            end,
            key,
            causal_role="curve",
            owned_by="usd",
            unit="index_jan_2006_100",
            **kw,
        )

    # 1 -- the dollar rises through three cuts.
    #
    # EVERY vintage is frozen, never just the one still in force.  The first draft
    # collapsed each period to its current value, and every scenario-1 row then carried
    # available_at=2026-02-02 -- the annual revision -- so nothing at all was knowable
    # at an as_of in 2024 and the state read UNKNOWN.  Selection belongs to
    # ``is_known_on``, which is the predicate under test; a generator that pre-selects
    # is a second implementation of it that cannot be wrong out loud.
    s1_usd = usd("DTWEXBGS", "2024-09-16", "2024-12-31")
    s1_effr = fetch_fred(
        client,
        "EFFR",
        "2024-09-16",
        "2024-12-31",
        key,
        causal_role="policy_actual",
        owned_by="policy_rates",
        unit="percent",
    )

    # 2 -- gold and real yields rise together, which the pre-2022 relationship forbids.
    s2_gold = fetch_gld_close(client, "2025-10-01", "2025-12-31", massive_key)
    s2_real = fetch_fred(
        client,
        "DFII10",
        "2025-10-01",
        "2025-12-31",
        key,
        causal_role="decomposition_component",
        owned_by="policy_rates",
        unit="percent",
    )

    # 3 -- tonnage accumulates into a rising real yield and a rising dollar.
    #
    # The cyclical legs reach back to January so a reader has a denominator: the
    # measured disagreement is the Aug-Oct window, but "the dollar is strong" against
    # ten weeks of its own history is not a statement about anything.
    s3_flow = fetch_gld_holdings(date(2024, 8, 19), date(2024, 10, 23))
    s3_real = fetch_fred(
        client,
        "DFII10",
        "2024-01-02",
        "2024-10-23",
        key,
        causal_role="decomposition_component",
        owned_by="policy_rates",
        unit="percent",
    )
    s3_usd = usd("DTWEXBGS", "2024-01-02", "2024-10-23")

    # 4 -- the anchor has no vintage at as_of and the real sibling does.
    #
    # Fetched under the anchor's REAL contract window rather than pinned to the as_of, so
    # the fixture carries the rows that make the abstention non-trivial: those periods
    # exist and every one of them carries available_at >= 2021-01-01.  A test applies
    # ``available_at <= as_of`` -- the universal evidence predicate -- and gets nothing.
    # Freezing an empty list instead would prove only that an empty list is empty.
    s4_anchor = usd("DTWEXBGS", "2020-06-01", "2020-06-30")
    s4_real_index = fetch_fred(
        client,
        "RTWEXBGS",
        "2019-01-01",
        "2020-06-30",
        key,
        causal_role="decomposition_component",
        owned_by="usd",
        unit="index_jan_2006_100",
        daily=False,
        as_of="2020-06-30",
    )

    # 5 -- every vintage of a restated week, not just the one still in force.
    s5 = usd("DTWEXBGS", "2026-08-03", "2026-08-07")

    scenarios = [
        {
            "id": "usd_strength_against_easing_policy",
            "domain": "usd",
            "as_of": "2025-01-08",
            "inputs": s1_usd + s1_effr,
            "expect": EXPECT["usd_strength_against_easing_policy"],
        },
        {
            "id": "gold_and_real_yields_decoupled_post_2022",
            "domain": "gold",
            "as_of": "2026-01-08",
            "inputs": s2_gold + s2_real,
            "expect": EXPECT["gold_and_real_yields_decoupled_post_2022"],
        },
        {
            "id": "strong_official_flows_against_adverse_cyclical",
            "domain": "gold",
            "as_of": "2024-10-30",
            "inputs": s3_flow + s3_real + s3_usd,
            "expect": EXPECT["strong_official_flows_against_adverse_cyclical"],
        },
        {
            "id": "usd_anchor_absent_state_abstains",
            "domain": "usd",
            "as_of": "2020-06-30",
            "inputs": s4_anchor + s4_real_index,
            "expect": EXPECT["usd_anchor_absent_state_abstains"],
        },
        {
            "id": "broad_dollar_revised_after_the_fact",
            "domain": "usd",
            "as_of": ["2026-08-12", "2026-08-20"],
            "inputs": s5,
            "expect": EXPECT["broad_dollar_revised_after_the_fact"],
        },
    ]

    _assert_preconditions(scenarios)

    payload = {
        "schema_version": "1",
        "authored_at": datetime.now(UTC).isoformat(),
        "spec": SPEC,
        "provenance": {
            "anchor": (
                "DTWEXBGS, the Fed H.10 nominal broad dollar, via FRED/ALFRED. Chosen in "
                "docs/research/2026-08-12-usd-source-probe/VERDICT.md as the only "
                "broad-dollar index that is both current and vintage-bearing. "
                "available_at is the vintage's realtime_start; superseded_at is the day it "
                "stopped being the published value, null while it still is."
            ),
            "real_index": (
                "RTWEXBGS, the CPI-deflated sibling. Present in scenario 4 to prove it is "
                "NOT substituted for the absent nominal anchor -- a different question, "
                "not a fallback."
            ),
            "gold_price": (
                "GLD daily closes from massive.com. FRED's LBMA fix GOLDPMGBD228NLBM was "
                "retired and answers HTTP 400, and Yahoo is banned by standing rule, so a "
                "traded ETF close is the free gold price this desk has. It is a fund's "
                "settled close, not a spot fix, and is labelled vendor rather than official."
            ),
            "gold_flow": (
                "SPDR's own historical-archive endpoint, tonnage held in the GLD trust. "
                "Counted in ounces, so a change is real accumulation rather than a price "
                "effect. official/free: the sponsor reporting its own bar list."
            ),
            "upstream": (
                "EFFR and DFII10 carry owned_by=policy_rates. USD and gold reference them "
                "through the upstream state, and the tag exists so a test can prove they "
                "were not re-claimed as domain-owned factors -- the double-count spec 1 "
                "prohibits."
            ),
            "values_are_real": (
                "Every number was fetched from the live publisher at authoring time. No "
                "value here was invented, rounded for legibility, or carried over from a "
                "prior fixture."
            ),
        },
        "scenarios": scenarios,
    }

    if OUT.exists():
        prior = json.loads(OUT.read_text(encoding="utf-8"))
        frozen = {row["id"]: row.get("expect") for row in prior.get("scenarios", [])}
        changed = [
            row["id"]
            for row in payload["scenarios"]
            if row["id"] in frozen and frozen[row["id"]] != row["expect"]
        ]
        if changed and "--rewrite-predictions" not in sys.argv:
            raise SystemExit(
                "refusing to overwrite the frozen prediction for "
                + ", ".join(changed)
                + ".\nPreregistered expectations are not editable from a regeneration. If "
                "the change is an authoring-time correction rather than a fit to engine "
                "output, re-run with --rewrite-predictions and record it as a spec "
                "deviation."
            )
        for scenario_id in changed:
            print(f"  REWRITING PREDICTION: {scenario_id}")
            print(f"    was: {json.dumps(frozen[scenario_id], sort_keys=True)}")

    OUT.write_text(
        json.dumps(payload, indent=1, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT.relative_to(ROOT)}")
    for row in scenarios:
        print(f"  {row['id']:<48} inputs={len(row['inputs']):>4}")


def _assert_preconditions(scenarios: list[dict[str, Any]]) -> None:
    """Fail loudly if the publishers stopped saying what the predictions assume.

    A silent empty leg would freeze a fixture whose scenario no longer exists, and the
    tests written against it would pass by describing nothing.
    """
    by_id = {row["id"]: row for row in scenarios}

    absent = by_id["usd_anchor_absent_state_abstains"]
    as_of = absent["as_of"]
    anchor = [row for row in absent["inputs"] if row["series_id"] == "DTWEXBGS"]
    visible = [row for row in anchor if row["available_at"] <= as_of]
    sibling = [
        row
        for row in absent["inputs"]
        if row["series_id"] == "RTWEXBGS" and row["available_at"] <= as_of
    ]
    if not anchor:
        raise SystemExit(
            "scenario 4 needs the anchor's periods present-but-unavailable; an empty leg "
            "would make the abstention trivially true"
        )
    if visible:
        raise SystemExit(
            f"scenario 4 needs ZERO DTWEXBGS rows passing available_at <= {as_of}, "
            f"got {len(visible)}"
        )
    if not sibling:
        raise SystemExit(
            "scenario 4 needs RTWEXBGS present at as_of -- the point is that an available "
            "substitute is refused, and with the sibling absent the scenario proves nothing"
        )

    revised = by_id["broad_dollar_revised_after_the_fact"]
    vintages: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in revised["inputs"]:
        vintages[row["period_end"]].append(row)
    if not any(len(rows) > 1 for rows in vintages.values()):
        raise SystemExit(
            "scenario 5 needs a period carrying more than one vintage; the window returned "
            "only current values, so there is no revision to replay"
        )

    for scenario in scenarios:
        if (
            not scenario["inputs"]
            and scenario["id"] != "usd_anchor_absent_state_abstains"
        ):
            raise SystemExit(f"{scenario['id']} fetched no inputs")

    # Rows that exist but are not yet knowable are the failure this guard exists for.
    # The first draft froze each period's CURRENT vintage, so scenario 1's rows all
    # carried available_at=2026-02-02 and a 2024 replay saw nothing -- every count above
    # was healthy and the scenario was empty. Only the abstention scenario is exempt,
    # because zero knowable anchor rows is the thing it asserts.
    for scenario in scenarios:
        if scenario["id"] == "usd_anchor_absent_state_abstains":
            continue
        raw = scenario["as_of"]
        as_of = min(raw) if isinstance(raw, list) else raw
        for series_id in sorted({row["series_id"] for row in scenario["inputs"]}):
            rows = [r for r in scenario["inputs"] if r["series_id"] == series_id]
            knowable = {r["period_end"] for r in rows if r["available_at"] <= as_of}
            if not knowable:
                raise SystemExit(
                    f"{scenario['id']}: {series_id} has {len(rows)} rows and NONE is "
                    f"knowable at as_of {as_of}. The scenario would replay as empty."
                )
            print(
                f"    {scenario['id'][:34]:<34} {series_id:<16} "
                f"{len(knowable):>4} knowable of {len(rows):>4}"
            )


if __name__ == "__main__":
    main()
