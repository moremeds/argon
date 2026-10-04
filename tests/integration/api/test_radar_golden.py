"""Golden of every radar/chain/dimensions GET response (I-35 proof).

Written BEFORE the radar router's raw SQL moved into
``storage/radar.py``: the four GET routes of ``api/routers/radar.py`` are
called with their query-param variants on an empty DB and on a seeded DB, and
status + body must equal the committed ``golden/radar_gets.json``.

The seed populates every table the four queries read (fundamental_universe,
fundamental_dimensions via fundamental_scores, fundamental_statement_obs,
fundamental_company_type, research_taxonomy_versions, research_chains,
chain_membership, company_exposure) with fixed dates. Two as_of rows per
(ticker, dimension) carry different values so DISTINCT ON's choice of the
newest row is visible in the bodies.

The clock is frozen, not normalised out: ``company_dimensions`` compares the
newest as_of to ``date.today()`` to choose ``ok`` vs ``stale_run`` and to write
the age into ``reason``. The freeze patches the ``date``/``datetime`` names of
every loaded ``uw_scan.api.routers.radar*`` and ``uw_scan.storage.radar*``
module, so it still reaches the code after it moves.

Floats are rounded to 9 significant digits before comparing (same rule as the
regime golden). No response field is masked.

Regenerate (only for an intentional response change):
``RADAR_GOLDEN_WRITE=1 uv run pytest tests/integration/api/test_radar_golden.py``
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

import pytest
from psycopg.types.json import Jsonb

from uw_scan.storage.fundamental_dimensions import FundamentalDimensionsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository

GOLDEN = Path(__file__).resolve().parent / "golden" / "radar_gets.json"

NOW = _dt.datetime(2026, 6, 30, 14, 0, 0, tzinfo=_dt.timezone.utc)
NEW = _dt.date(2026, 6, 15)  # newest as_of: 15 days before NOW -> "ok"
OLD = _dt.date(2026, 3, 31)  # older as_of: DISTINCT ON must skip it
STALE = _dt.date(2026, 1, 15)  # only as_of of EEE: 166 days -> "stale_run"

ENGINE_A = "golden-eng-a"  # activated
ENGINE_B = "golden-eng-b"
TAX_V1 = "golden-tax-v1"  # activated
TAX_V0 = "golden-tax-v0"

_CLOCK_PREFIXES = ("uw_scan.api.routers.radar", "uw_scan.storage.radar")

REQUESTS: list[tuple[str, dict]] = [
    # company dimensions
    ("/api/stock/AAA/fundamentals/dimensions", {}),
    ("/api/stock/aaa/fundamentals/dimensions", {}),
    ("/api/stock/EEE/fundamentals/dimensions", {}),
    ("/api/stock/STM/fundamentals/dimensions", {}),
    ("/api/stock/XYZ/fundamentals/dimensions", {}),
    ("/api/stock/AAA/fundamentals/dimensions", {"engine_version": ENGINE_B}),
    ("/api/stock/AAA/fundamentals/dimensions", {"engine_version": "golden-eng-none"}),
    # radar
    ("/api/scanner/radar", {}),
    ("/api/scanner/radar", {"tier": "ranked"}),
    ("/api/scanner/radar", {"tier": "watch"}),
    ("/api/scanner/radar", {"tier": "dormant"}),
    ("/api/scanner/radar", {"tier": "no-such-tier"}),
    ("/api/scanner/radar", {"engine_version": ENGINE_B}),
    ("/api/scanner/radar", {"engine_version": "golden-eng-none"}),
    ("/api/scanner/radar", {"limit": 2}),
    ("/api/scanner/radar", {"limit": 0}),
    ("/api/scanner/radar", {"min_dimensions": 0}),
    ("/api/scanner/radar", {"min_dimensions": 4}),
    ("/api/scanner/radar", {"min_dimensions": 5}),
    ("/api/scanner/radar", {"tier": "watch", "engine_version": ENGINE_B, "limit": 1}),
    # chain matrix
    ("/api/research/chains/matrix", {}),
    ("/api/research/chains/matrix", {"taxonomy_version": TAX_V0}),
    ("/api/research/chains/matrix", {"taxonomy_version": "golden-tax-none"}),
    ("/api/research/chains/matrix", {"engine_version": ENGINE_B}),
    ("/api/research/chains/matrix", {"domain": "ai"}),
    ("/api/research/chains/matrix", {"domain": "energy"}),
    ("/api/research/chains/matrix", {"domain": "no-such-domain"}),
    # chain members
    ("/api/research/chains/Optical", {}),
    ("/api/research/chains/Optical", {"layer": "Module"}),
    ("/api/research/chains/Optical", {"layer": "Systems"}),
    ("/api/research/chains/Compute", {}),
    ("/api/research/chains/Compute", {"engine_version": ENGINE_B}),
    ("/api/research/chains/Power", {}),
    ("/api/research/chains/NoSuchChain", {}),
    ("/api/research/chains/Optical", {"taxonomy_version": TAX_V0}),
]


class _FrozenDateTime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):  # type: ignore[override]
        return NOW.replace(tzinfo=None)


class _FrozenDate(_dt.date):
    @classmethod
    def today(cls):  # type: ignore[override]
        return NOW.date()


@pytest.fixture
def frozen_clock(monkeypatch, client):
    # timestamptz values render in the DB session's timezone; pin it.
    monkeypatch.setenv("PGTZ", "UTC")
    # `client` first: create_app() has imported every router module by now.
    names = [m for m in list(sys.modules) if m.startswith(_CLOCK_PREFIXES)]
    assert "uw_scan.api.routers.radar" in names
    for name in names:
        mod = sys.modules[name]
        for attr in ("datetime", "_datetime", "date", "_date"):
            val = getattr(mod, attr, None)
            if val is _dt.datetime:
                monkeypatch.setattr(mod, attr, _FrozenDateTime)
            elif val is _dt.date:
                monkeypatch.setattr(mod, attr, _FrozenDate)
    return client


def _round_floats(value):
    if isinstance(value, float):
        return float(f"{value:.9g}")
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v) for v in value]
    return value


def _sweep(client) -> list[dict]:
    out: list[dict] = []
    for path, params in REQUESTS:
        r = client.get(path, params=params)
        try:
            body = r.json()
        except ValueError:
            body = r.text
        out.append(
            {
                "path": path,
                "params": params,
                "status": r.status_code,
                "body": _round_floats(body),
            }
        )
    return out


# (ticker, as_of, engine) -> {dimension: (value, present, expected, authority, detail)}
_R = "research_priority"
_D = "descriptive"
_M = "directional_monitor"
DIMS: dict[tuple[str, _dt.date, str], dict[str, tuple]] = {
    ("AAA", OLD, ENGINE_A): {
        "priority": ("0.9", 4, 4, _R, {}),
        "growth": ("0.5", 1, 1, _R, {}),
        "balance_sheet": ("0.1", 1, 1, _R, {}),
    },
    ("AAA", NEW, ENGINE_A): {
        "priority": ("1.5", 4, 4, _R, {"note": "four of four"}),
        "growth": ("12.3", 1, 1, _R, {"features": {"rev_growth": 12.3}}),
        "operating_quality": ("-0.25", 2, 2, _D, {}),
        "balance_sheet": ("0.75", 1, 1, _R, {}),
        "cash_conversion": ("-0.4", 1, 1, _R, {}),
        "capital_efficiency": ("0.2", 2, 2, _R, {}),
        "valuation": ("-11.0", 1, 1, _M, {}),
        "evidence_quality": ("0.8", 4, 5, _D, {}),
    },
    ("BBB", OLD, ENGINE_A): {
        "priority": ("2.0", 2, 4, _R, {}),
    },
    ("BBB", NEW, ENGINE_A): {
        "priority": ("0.4", 2, 4, _R, {}),
        "growth": ("0.6", 1, 1, _R, {}),
        "balance_sheet": ("0.2", 1, 1, _R, {}),
        "cash_conversion": (None, 0, 1, _R, {}),
        "evidence_quality": (None, 0, 5, _D, {}),
    },
    ("CCC", NEW, ENGINE_A): {
        "priority": (None, 3, 4, _R, {"refused": "spread"}),
        "growth": ("-1.2", 1, 1, _R, {}),
        "cash_conversion": ("0.3", 1, 1, _R, {}),
        "capital_efficiency": ("0.9", 2, 2, _R, {}),
    },
    ("DDD", NEW, ENGINE_A): {
        "growth": ("0.05", 1, 1, _R, {}),
    },
    ("EEE", STALE, ENGINE_A): {
        "priority": ("0.4", 2, 4, _R, {}),
        "growth": ("-0.3", 1, 1, _R, {}),
        "capital_efficiency": ("0.7", 2, 2, _R, {}),
    },
    ("FFF", NEW, ENGINE_A): {
        "priority": ("-0.6", 2, 4, _R, {}),
        "growth": ("-0.6", 1, 1, _R, {}),
        "balance_sheet": ("-0.6", 1, 1, _R, {}),
    },
    ("GGG", NEW, ENGINE_A): {
        "priority": ("3.1", 2, 4, _R, {}),
        "growth": ("3.0", 1, 1, _R, {}),
        "balance_sheet": ("3.2", 1, 1, _R, {}),
    },
    ("AAA", NEW, ENGINE_B): {
        "priority": ("-0.2", 3, 4, _R, {}),
        "growth": ("-0.1", 1, 1, _R, {}),
        "balance_sheet": ("-0.3", 1, 1, _R, {}),
        "cash_conversion": ("-0.2", 1, 1, _R, {}),
    },
    ("FFF", NEW, ENGINE_B): {
        "priority": ("1.1", 2, 4, _R, {}),
        "growth": ("1.0", 1, 1, _R, {}),
        "capital_efficiency": ("1.2", 2, 2, _R, {}),
    },
}

UNIVERSE = [
    # (tier, ticker, removed)
    ("ranked", "AAA", False),
    ("ranked", "BBB", False),
    ("ranked", "CCC", False),
    ("ranked", "DDD", False),
    ("ranked", "EEE", False),
    ("ranked", "ZZZ", False),  # no dimensions -> names_without_result
    ("ranked", "GGG", True),  # removed -> outside the tier
    ("watch", "FFF", False),
    ("watch", "AAA", False),
    ("watch", "GGG", False),
    ("dormant", "HHH", False),  # names but no dims -> no_compatible_run
]

COMPANY_TYPE = [("AAA", "compounder"), ("BBB", "cyclical"), ("FFF", "financials")]

STATEMENTS = ["AAA", "STM"]  # STM: statements, never scored


def seed(repo) -> None:
    """Populate every table the radar router reads, with fixed values."""
    conn, schema = repo.conn, repo._schema
    scores = FundamentalScoresRepository(conn, schema=schema)
    for eng in (ENGINE_A, ENGINE_B):
        scores.register_version(
            engine_version=eng, code_version="golden", param_hash=eng, params={}
        )
    scores.activate(ENGINE_A)

    dim_rows = []
    with conn.cursor() as cur:
        for (ticker, as_of, eng), dims in DIMS.items():
            cur.execute(
                f"""INSERT INTO {schema}.fundamental_scores
                           (ticker, as_of, engine_version, inputs_hash, period_end,
                            knowledge_date, filing_date_known, features_present)
                    VALUES (%s, %s, %s, 'golden', %s, %s, true, 4)
                    RETURNING result_id""",
                (ticker, as_of, eng, as_of, as_of),
            )
            result_id = cur.fetchone()[0]
            for dim, (value, present, expected, authority, detail) in dims.items():
                dim_rows.append(
                    {
                        "result_id": result_id,
                        "ticker": ticker,
                        "as_of": as_of,
                        "engine_version": eng,
                        "dimension": dim,
                        "value": value,
                        "inputs_present": present,
                        "inputs_expected": expected,
                        "authority": authority,
                        "detail": detail,
                    }
                )
        for tier, ticker, removed in UNIVERSE:
            cur.execute(
                f"""INSERT INTO {schema}.fundamental_universe
                           (tier, ticker, layer, reason, added_at, removed_at)
                    VALUES (%s, %s, NULL, 'golden', %s, %s)""",
                (
                    tier,
                    ticker,
                    _dt.datetime(2026, 1, 2, tzinfo=_dt.timezone.utc),
                    _dt.datetime(2026, 2, 2, tzinfo=_dt.timezone.utc)
                    if removed
                    else None,
                ),
            )
        for ticker, ctype in COMPANY_TYPE:
            cur.execute(
                f"""INSERT INTO {schema}.fundamental_company_type
                           (ticker, company_type, source)
                    VALUES (%s, %s, 'manual')""",
                (ticker, ctype),
            )
        for ticker in STATEMENTS:
            cur.execute(
                f"""INSERT INTO {schema}.fundamental_statement_obs
                           (source, ticker, period_end, period_type, statement,
                            content_hash, raw_jsonb, field_map_version)
                    VALUES ('uw', %s, %s, 'quarterly', 'income', 'golden', %s, 'v1')""",
                (ticker, _dt.date(2026, 3, 31), Jsonb({})),
            )
    conn.commit()
    FundamentalDimensionsRepository(conn, schema=schema).record(dim_rows)

    tax = ResearchTaxonomyRepository(conn, schema=schema)
    tax.publish_version(TAX_V0, note="golden old", activate=False)
    tax.publish_version(TAX_V1, note="golden", activate=True)
    tax.define_chains(
        TAX_V1,
        [
            {"domain": "ai", "chain": "Optical", "layer": "Laser", "layer_rank": 20},
            {"domain": "ai", "chain": "Optical", "layer": "Module", "layer_rank": 30},
            {"domain": "ai", "chain": "Optical", "layer": "Systems", "layer_rank": 40},
            {
                "domain": "ai",
                "chain": "Compute",
                "layer": "Accelerator",
                "layer_rank": 10,
            },
            {"domain": "energy", "chain": "Power", "layer": "Grid", "layer_rank": 10},
        ],
    )
    tax.define_chains(
        TAX_V0,
        [{"domain": "ai", "chain": "Optical", "layer": "Module", "layer_rank": 30}],
    )
    for version, chain, layer, ticker, ev in [
        (TAX_V1, "Optical", "Module", "AAA", "disclosed"),
        (TAX_V1, "Optical", "Module", "BBB", "analyst"),
        (TAX_V1, "Optical", "Module", "CCC", "inferred"),
        (TAX_V1, "Optical", "Module", "EEE", "mirrored"),
        (TAX_V1, "Optical", "Module", "HHH", "inferred"),  # closed below
        (TAX_V1, "Optical", "Systems", "DDD", "analyst"),
        (TAX_V1, "Optical", "Systems", "FFF", "analyst"),
        (TAX_V1, "Compute", "Accelerator", "AAA", "disclosed"),
        (TAX_V1, "Compute", "Accelerator", "BBB", "analyst"),
        (TAX_V1, "Compute", "Accelerator", "FFF", "disclosed"),
        (TAX_V1, "Compute", "Accelerator", "GGG", "inferred"),
        (TAX_V0, "Optical", "Module", "ZZZ", "inferred"),
        (TAX_V0, "Optical", "Module", "AAA", "inferred"),
    ]:
        tax.add_membership(
            version,
            chain=chain,
            layer=layer,
            ticker=ticker,
            evidence_class=ev,
            approved_by="golden-operator",
        )
    tax.record_exposure(
        [
            {
                "taxonomy_version": TAX_V1,
                "ticker": "AAA",
                "chain": "Optical",
                "role": "component",
                "direction": "upstream",
                "magnitude": 0.4,
                "magnitude_basis": "segment_share",
                "confidence": "high",
                "status": "disclosed",
                "source_kind": "revenue_breakdown_obs",
                "source_ref": "aaa:OpticsMember",
            },
            {
                "taxonomy_version": TAX_V1,
                "ticker": "BBB",
                "chain": "Optical",
                "role": "supplier",
                "magnitude_basis": "qualitative",
                "confidence": "low",
                "status": "asserted",
                "source_kind": "chain_membership",
            },
            {
                "taxonomy_version": TAX_V1,
                "ticker": "FFF",
                "chain": "Compute",
                "role": "customer",
                "direction": "downstream",
                "magnitude": 0.25,
                "magnitude_basis": "customer_concentration",
                "confidence": "medium",
                "status": "disclosed",
                "source_kind": "manual",
                "source_ref": "fff:10-K",
            },
            {
                "taxonomy_version": TAX_V1,
                "ticker": "CCC",
                "chain": "Optical",
                "role": "integrator",
                "magnitude_basis": "unknown",
                "status": "inferred",
                "source_kind": "chain_membership",
            },
        ]
    )
    with conn.cursor() as cur:
        # Close HHH's membership and CCC's exposure: both must drop out of the
        # `valid_to IS NULL` joins. Fixed instants, not now().
        opened = _dt.datetime(2026, 1, 5, tzinfo=_dt.timezone.utc)
        closed = _dt.datetime(2026, 2, 5, tzinfo=_dt.timezone.utc)
        cur.execute(
            f"""UPDATE {schema}.chain_membership
                   SET valid_from = %s, valid_to = %s
                 WHERE ticker = 'HHH'""",
            (opened, closed),
        )
        cur.execute(
            f"""UPDATE {schema}.company_exposure
                   SET valid_from = %s, valid_to = %s
                 WHERE ticker = 'CCC'""",
            (opened, closed),
        )
    conn.commit()


def test_radar_gets_match_golden(frozen_clock, seeded_db_empty_cards):
    client = frozen_clock
    result = {"empty": _sweep(client)}
    seed(seeded_db_empty_cards)
    result["seeded"] = _sweep(client)
    text = json.dumps(result, sort_keys=True, indent=1, default=str) + "\n"

    if os.environ.get("RADAR_GOLDEN_WRITE") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(text)
        pytest.skip("golden written")
    assert text == GOLDEN.read_text(), (
        "radar GET responses changed; diff against "
        "tests/integration/api/golden/radar_gets.json"
    )
