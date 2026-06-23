"""Throwaway builder for docs/research/vrp/macro-capital-utilisation-findings.ipynb.
Reads docs/research/vrp/capital-sweep-results.csv. Run:
  uv run python scripts/_build_vrp_capital_notebook.py
"""

from __future__ import annotations

import json
import pathlib

OUT = pathlib.Path("docs/research/vrp/macro-capital-utilisation-findings.ipynb")


def _md(text: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": text.splitlines(keepends=True),
    }


def _code(src: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": src.splitlines(keepends=True),
    }


def main() -> None:
    cells = [
        _md(
            "# Macro Short-Vol — Two-Layer $50k Capital-Utilisation Study\n\n"
            "Base = deployed WINNER (ramp+ vrp-z-sized bull put spread, Sharpe ≈1.65). "
            "Overlay = binary extra set when `vrp_z >= rich_threshold`. One shared $50k "
            "across SPY/QQQ/IWM. Full results: `capital-sweep-results.csv`.\n"
        ),
        _code(
            "import pandas as pd\ndf = pd.read_csv('capital-sweep-results.csv')\ndf\n"
        ),
        _md("## Base-only baselines (overlay disabled)\n"),
        _code(
            "df[df.overlay_enabled == 0].sort_values('ann_return_gross', ascending=False)\n"
        ),
        _md("## Base + overlay — frontier by gross annualised return\n"),
        _code(
            "bo = df[df.overlay_enabled == 1].sort_values('ann_return_gross', ascending=False)\n"
            "bo[['base_risk_pct','overlay_mult','rich_threshold','ann_return_gross','cagr_gross',"
            "'sharpe','maxdd_pct','util_mean','util_peak','skip_rate']].head(12)\n"
        ),
        _md(
            "## Does the overlay earn its capital?\n\n"
            "Compare each base+overlay cell against its base-only sibling at the same "
            "`base_risk_pct`: Δ ann_return_gross vs Δ utilisation vs Δ maxDD.\n"
        ),
        _code(
            "base = df[df.overlay_enabled == 0].set_index('base_risk_pct')\n"
            "rows = []\n"
            "for _, r in df[df.overlay_enabled == 1].iterrows():\n"
            "    b = base.loc[r.base_risk_pct]\n"
            "    rows.append({'base_risk_pct': r.base_risk_pct, 'overlay_mult': r.overlay_mult,\n"
            "        'rich_threshold': r.rich_threshold,\n"
            "        'd_ann_gross': r.ann_return_gross - b.ann_return_gross,\n"
            "        'd_util_mean': r.util_mean - b.util_mean,\n"
            "        'd_maxdd_pct': r.maxdd_pct - b.maxdd_pct,\n"
            "        'd_sharpe': r.sharpe - b.sharpe})\n"
            "pd.DataFrame(rows).sort_values('d_ann_gross', ascending=False)\n"
        ),
    ]
    nb = {
        "cells": cells,
        "metadata": {"language_info": {"name": "python"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    OUT.write_text(json.dumps(nb, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
