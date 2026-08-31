"""Seed fundamental method versions and activate the validated one.

    uv run python scripts/seed_fundamental_method.py [--show]

`v1_equal` is ACTIVE — equal weight across the seven features, which is the
construction carrying the validated IC (0.039 leak-free, t 2.67). The rubric and
no-margins alternatives are registered as INACTIVE candidates so the eventual
walk-forward sweep has them expressed in the same schema, at zero cost and with no
risk of one being quoted as validated.

Ruling and evidence:
`docs/research/2026-08-12-fundamental-weighting-probe/DECISION.md`.
"""

from __future__ import annotations

import sys

import psycopg

from uw_scan.config import Settings
from uw_scan.fundamentals.features import FEATURES
from uw_scan.fundamentals.scoring import (
    CODE_VERSION,
    CODE_VERSION_V2,
    engine_version,
    param_hash,
)
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository

# The validated construction. Nothing else may claim its IC.
EQUAL = {f: 1.0 for f in FEATURES}

# §5.2's seed weights, mapped onto the features that exist and renormalized.
# Beat equal weight on independent t-stats (4.11 vs 3.09) and NOT on the paired
# test (t 1.79) — which is why it is registered, not activated.
RUBRIC = {
    "rev_growth": 0.20,
    "gross_margin": 0.10,
    "op_margin": 0.10,
    "fcf_margin": 0.075,
    "asset_turnover": 0.075,
    "neg_net_debt_ebitda": 0.15,
    "roe": 0.0,
}

# Drops the two features whose measured direction was contradicted. Paired t 2.52
# and POST-HOC — components chosen on their realised sign. Needs a pre-committed
# out-of-sample test before it could ever be activated.
NO_MARGINS = {f: (0.0 if f in ("gross_margin", "op_margin") else 1.0) for f in FEATURES}

# v2 is v1's weights under v1's validated construction, with ONE change: values
# an integrity check impugns are withheld from the math rather than only from the
# card. Registered under CODE_VERSION_V2 so every v1 row keeps replaying
# byte-identically; the exclusion code does not run for them.
CANDIDATES_V2 = {
    "v2_equal": (
        EQUAL,
        "equal weight + validity exclusions (M1.1); v1 weights, v1 math, "
        "violated inputs withheld",
    ),
}

CANDIDATES = {
    "v1_equal": (EQUAL, "VALIDATED: equal weight, IC 0.039 leak-free t 2.67"),
    "v1_rubric": (RUBRIC, "INACTIVE: spec §5.2 seeds; paired t 1.79 vs equal — n.s."),
    "v1_no_margins": (
        NO_MARGINS,
        "INACTIVE: post-hoc (components dropped on realised sign); needs OOS",
    ),
}

# v1_equal stays ACTIVE. v2 is registered but NOT activated: switching the
# default would change every score the card and Value surface read, and that
# switch is a measured decision (does excluding violated inputs change the
# ranking, and by how much) rather than a deploy side effect. `--activate-v2`
# makes it explicit.
ACTIVE = "v1_equal"
ACTIVE_V2 = "v2_equal"


def main() -> int:
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = FundamentalScoresRepository(conn, schema=settings.db_schema)
        if "--show" in sys.argv:
            active = repo.active_version()
            print(f"active: {active}")
            if active:
                print(f"params: {repo.params(active)}")
            return 0

        active_engine = None
        for name, (params, note) in CANDIDATES.items():
            engine = engine_version(params)
            repo.register_version(
                engine_version=engine,
                code_version=CODE_VERSION,
                param_hash=param_hash(params),
                params=params,
                note=f"{name} — {note}",
            )
            marker = "ACTIVE " if name == ACTIVE else "       "
            print(f"  {marker}{name:14} {engine}")
            if name == ACTIVE:
                active_engine = engine

        v2_engine = None
        for name, (params, note) in CANDIDATES_V2.items():
            engine = engine_version(params, CODE_VERSION_V2)
            repo.register_version(
                engine_version=engine,
                code_version=CODE_VERSION_V2,
                param_hash=param_hash(params),
                params=params,
                note=f"{name} — {note}",
            )
            print(f"         {name:14} {engine}")
            if name == ACTIVE_V2:
                v2_engine = engine

        assert active_engine, f"{ACTIVE} not among candidates"
        assert v2_engine, f"{ACTIVE_V2} not among v2 candidates"
        if "--activate-v2" in sys.argv:
            active_engine = v2_engine
            print(f"\n  activating v2 on request: {v2_engine}")
        repo.activate(active_engine)
        print(f"\nactive engine_version: {repo.active_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
