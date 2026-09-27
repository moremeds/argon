#!/usr/bin/env python
"""Vendor livewire's S&P 500 list into argon for sector RS breadth.

Why it is vendored (ruling 2026-09-26, spec §4): apex's membership route is
defective (null symbols, dead tickers, META/XOM missing), and livewire's
presets/sp500.json, which is clean, is not in the lake mount the argon
container sees. Re-run this whenever livewire updates the preset, then commit
the result.

It refuses with SystemExit, writing nothing, on duplicates or fewer than 450
names. It uses the same validator the runtime reader applies.

Reproduce:
    uv run python scripts/research/sync_sp500_members.py --livewire ~/projects/livewire
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

from uw_scan.sources.sp500_members import Sp500ListInvalid, validate_tickers

DEFAULT_OUT = (
    Path(__file__).resolve().parents[2] / "src/uw_scan/sources/data/sp500_members.json"
)


def build(livewire: Path, as_of: date) -> dict[str, object]:
    preset = json.loads((livewire / "presets" / "sp500.json").read_text())
    try:
        tickers = validate_tickers(
            preset.get("tickers") if isinstance(preset, dict) else None
        )
    except Sp500ListInvalid as exc:
        raise SystemExit(
            f"refusing to vendor {livewire}/presets/sp500.json: {exc}"
        ) from exc
    commit = subprocess.run(
        ["git", "-C", str(livewire), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "as_of": as_of.isoformat(),
        "source": f"livewire presets/sp500.json @ {commit}",
        "source_note": preset.get("source"),
        "tickers": list(tickers),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Vendor livewire presets/sp500.json into argon"
    )
    p.add_argument(
        "--livewire", type=Path, default=Path.home() / "projects" / "livewire"
    )
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = p.parse_args(argv)
    body = build(args.livewire.expanduser(), args.as_of)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(body, indent=1) + "\n")
    print(f"wrote {args.out}: {len(body['tickers'])} tickers from {body['source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
