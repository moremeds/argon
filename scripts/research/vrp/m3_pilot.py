"""Frozen, model-priced SPX VRP sizing pilot for the Helium M3 loop.

This is a development-corpus experiment, not sealed OOS evidence. Prices are the
existing flat-vol model and settled SPX closes; costs are hypothetical flat
round-trip dollars per spread contract. No quote or achievable-fill claim is made.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_capital_account import CapitalConfig, simulate_account
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_harvest import _Loaded
from uw_scan.reports.vrp_macro_signal import WINNER
from uw_scan.storage.repository import Repository

CAPITAL = 1_000_000.0
PRIMARY_COST_USD = 2.0
RISK_FREE_RATE = 0.04
ARMS = {
    "baseline": 0.20,
    "size_down_control": 0.05,
    "candidate": 0.10,
}
COSTS_USD = (0.0, 2.0, 5.0)
REPO_ROOT = Path(__file__).resolve().parents[3]


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: Any) -> str:
    data = _json_bytes(value)
    path.write_bytes(data)
    return _sha256_bytes(data)


def _engine_source_binding() -> dict[str, Any]:
    paths = sorted((REPO_ROOT / "src/uw_scan/reports").glob("vrp*.py"))
    paths.extend(
        [
            REPO_ROOT / "scripts/research/vrp/m3_pilot.py",
            REPO_ROOT / "src/uw_scan/config.py",
            REPO_ROOT / "uv.lock",
        ]
    )
    return {
        "argon_git_head": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "files_sha256": {
            str(path.relative_to(REPO_ROOT)): _sha256_bytes(path.read_bytes())
            for path in paths
        },
    }


def loaded_to_snapshot(loaded: _Loaded) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": {
            "instrument": "SPX",
            "spot": "uw_scan.vol_index_daily:SPX.close",
            "implied_vol": "uw_scan.vol_index_daily:VIX.close/100",
        },
        "adj": [[d.isoformat(), v] for d, v in loaded.adj],
        "rows": [
            {
                **row,
                "market_date": row["market_date"].isoformat(),
            }
            for row in loaded.rows
        ],
        "events": loaded.events,
    }


def snapshot_to_loaded(snapshot: dict[str, Any]) -> _Loaded:
    adj = [(date.fromisoformat(d), float(v)) for d, v in snapshot["adj"]]
    rows = [
        {**row, "market_date": date.fromisoformat(row["market_date"])}
        for row in snapshot["rows"]
    ]
    return _Loaded(
        adj=adj,
        pidx={d: i for i, (d, _v) in enumerate(adj)},
        rows=rows,
        events=snapshot.get("events", []),
    )


def settlement_metrics(rungs: list, capital: float = CAPITAL) -> tuple[dict, list[dict]]:
    by_date: dict[date, float] = defaultdict(float)
    for rung in rungs:
        by_date[rung.exit_date] += rung.net_pnl
    equity = capital
    peak = capital
    max_drawdown = 0.0
    path = [{"date": None, "net_pnl_usd": 0.0, "equity_usd": capital}]
    for settled, pnl in sorted(by_date.items()):
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
        path.append(
            {
                "date": settled.isoformat(),
                "net_pnl_usd": pnl,
                "equity_usd": equity,
            }
        )
    if rungs:
        start = min(r.entry_date for r in rungs)
        end = max(r.exit_date for r in rungs)
        years = max((end - start).days / 365.2425, 1 / 365.2425)
    else:
        start = end = None
        years = 0.0
    terminal_positive = equity > 0
    annual = (equity / capital) ** (1 / years) - 1 if years and terminal_positive else None
    return (
        {
            "annual_net_return": annual,
            "max_drawdown": max_drawdown,
            "terminal_equity_usd": equity,
            "net_pnl_usd": equity - capital,
            "insolvent": not terminal_positive,
            "trade_count": len(rungs),
            "contracts": sum(r.contracts for r in rungs),
            "span": {
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "years": years,
            },
        },
        path,
    )


def _settings_for_cost(cost_usd: float) -> SimpleNamespace:
    # Bull put spread = 2 legs x 2 sides. This makes CostModel.total exactly the
    # declared flat round-trip dollars per spread contract, with no slippage proxy.
    return SimpleNamespace(
        vrp_risk_free_rate=RISK_FREE_RATE,
        vrp_cost_per_contract=cost_usd / 4.0,
        vrp_slippage_frac=0.0,
        vrp_slippage_min=0.0,
        vrp_cost_round_trip=True,
    )


def _protocol(source_binding: dict[str, Any]) -> dict[str, Any]:
    arm_configs = {}
    for arm, risk in ARMS.items():
        config = {
            "capital_usd": CAPITAL,
            "base_risk_pct": risk,
            "overlay_mult": 0.0,
            "rich_threshold": 99.0,
            "names": ["SPX"],
            "compounding": True,
            "base_cfg": asdict(WINNER),
        }
        arm_configs[arm] = {**config, "config_sha256": _sha256_bytes(_json_bytes(config))}
    return {
        "schema_version": 1,
        "experiment_id": "argon-m3-vrp-sizing-pilot-1",
        "engine_source_binding": source_binding,
        "status": "development_corpus_exposed_no_sealed_oos",
        "candidate_selected_before_evaluation": "candidate",
        "primary_cost_usd_selected_before_evaluation": PRIMARY_COST_USD,
        "arms": arm_configs,
        "cost_sensitivity_usd_per_spread_contract_round_trip": list(COSTS_USD),
        "cost_model": "flat hypothetical cost; zero slippage; no NBBO or achievable-fill claim",
        "risk_free_rate": RISK_FREE_RATE,
        "metric_basis": "realized_settlements_only",
        "drawdown": "positive peak-relative drawdown; initial capital is the first peak",
        "annual_return": "geometric net return when terminal equity is positive; otherwise null with insolvent=true",
        "data_split": "chronological 60/40 boundary is reported without subperiod performance; entire corpus is development-exposed",
        "pricing_and_entry_rules": "existing load_index_vol(SPX), WINNER, and simulate_account shared by every arm",
    }


def run(output: Path, snapshot_path: Path | None = None) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    (output / "trades").mkdir()
    (output / "equity").mkdir()

    source_binding = _engine_source_binding()
    protocol = _protocol(source_binding)
    protocol_sha = _write_json(output / "protocol.json", protocol)
    settings = Settings.from_env()
    if snapshot_path:
        snapshot_bytes = snapshot_path.read_bytes()
        snapshot = json.loads(snapshot_bytes)
        loaded = snapshot_to_loaded(snapshot)
        (output / "source_snapshot.json").write_bytes(snapshot_bytes)
        snapshot_sha = _sha256_bytes(snapshot_bytes)
    else:
        with psycopg.connect(
            settings.db_dsn(), options="-c default_transaction_read_only=on"
        ) as conn:
            loaded = load_index_vol(Repository(conn, schema=settings.db_schema), "SPX")
        snapshot = loaded_to_snapshot(loaded)
        snapshot_sha = _write_json(output / "source_snapshot.json", snapshot)

    results = []
    for arm, risk in ARMS.items():
        capcfg = CapitalConfig(
            capital=CAPITAL,
            base_risk_pct=risk,
            overlay_mult=0.0,
            rich_threshold=99.0,
            names=("SPX",),
            compounding=True,
            base_cfg=WINNER,
        )
        for cost_usd in COSTS_USD:
            account = simulate_account(
                {"SPX": loaded}, _settings_for_cost(cost_usd), capcfg
            )
            metrics, equity = settlement_metrics(account.rungs)
            slug = f"{arm}-cost-{cost_usd:g}"
            trades = [
                {
                    "name": r.name,
                    "entry_date": r.entry_date.isoformat(),
                    "exit_date": r.exit_date.isoformat(),
                    "contracts": r.contracts,
                    "margin_usd": r.margin,
                    "net_pnl_usd": r.net_pnl,
                    "breached": r.breached,
                }
                for r in account.rungs
            ]
            trade_path = f"trades/{slug}.json"
            equity_path = f"equity/{slug}.json"
            trade_sha = _write_json(output / trade_path, trades)
            equity_sha = _write_json(output / equity_path, equity)
            results.append(
                {
                    "arm": arm,
                    "cost_usd": cost_usd,
                    **metrics,
                    "source_span": {
                        "start": loaded.adj[0][0].isoformat(),
                        "end": loaded.adj[-1][0].isoformat(),
                    },
                    "trade_path": trade_path,
                    "trade_sha256": trade_sha,
                    "settlement_equity_path": equity_path,
                    "settlement_equity_sha256": equity_sha,
                }
            )

    split_at = round(len(loaded.adj) * 0.60)
    if _engine_source_binding() != source_binding:
        raise RuntimeError("Argon engine sources changed during the pilot")
    summary = {
        "schema_version": 1,
        "experiment_id": protocol["experiment_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": protocol_sha,
        "snapshot_sha256": snapshot_sha,
        "metric_basis": protocol["metric_basis"],
        "oos_status": protocol["status"],
        "primary_cost_usd": PRIMARY_COST_USD,
        "arms": protocol["arms"],
        "development_split": {
            "rule": "chronological source dates; round(n * 0.60)",
            "first_60_pct": {
                "start": loaded.adj[0][0].isoformat(),
                "end": loaded.adj[split_at - 1][0].isoformat(),
            },
            "last_40_pct": {
                "start": loaded.adj[split_at][0].isoformat(),
                "end": loaded.adj[-1][0].isoformat(),
            },
            "performance_reported": False,
            "caveat": "Boundary only: the entire corpus was exposed during development, so neither segment is sealed confirmation.",
        },
        "results": results,
        "caveats": [
            "All data was exposed during development; the 60/40 split is diagnostic only.",
            "Equity and drawdown use settled realized P&L only; no open-position MTM exists.",
            "Prices are model-derived and costs hypothetical; there is no NBBO or achievable-fill claim.",
            "The declared $1,000,000 is a model experiment account, not an observed balance.",
        ],
    }
    _write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    summary = run(args.output, args.snapshot)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
