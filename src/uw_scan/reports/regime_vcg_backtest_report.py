"""Pure renderer: VCG regime_backtest_runs row + daily rows -> markdown.

Mirrors regime_backtest_report.render_backtest_markdown shape. The router
calls this on each /api/regime/vcg-validation request — no I/O, no DB.

The structured payload (interpretation distribution + named-crash window)
is surfaced separately on the response; this renderer produces only the
human-readable summary that goes into the <pre> block in the UI.
"""

from __future__ import annotations

from io import StringIO

# Order: the 7 interpretation levels emitted by vcg_scoring._interpretation_for_index
# under normal data conditions, then INSUFFICIENT_DATA (emitted when there aren't
# enough bars in the rolling window). Including it here keeps the renderer's
# distribution table consistent with the API response (which iterates all dist
# keys) and ensures row percentages sum to 100.
_LEVELS = (
    "NORMAL",
    "SUPPRESSED",
    "EDR",
    "BOUNCE",
    "RISK_OFF",
    "PANIC",
    "WATCH",
    "INSUFFICIENT_DATA",
)


def render_vcg_backtest_markdown(run: dict, daily: list[dict]) -> str:
    if not daily:
        return "# VCG Backtest\n\n_No daily rows available._\n"

    extras = (run.get("summary") or {}).get("extras") or {}
    proxy = extras.get("credit_proxy", "—")
    dist = extras.get("interpretation_distribution") or {}
    total = sum(dist.values()) or 1

    out = StringIO()
    out.write("# VCG Backtest — Credit Proxy + Vol Compression\n\n")
    out.write(f"**N days:** {len(daily)}\n")
    out.write(f"**Credit proxy:** {proxy}\n")
    out.write(
        f"**Date range:** {daily[0]['trade_date'].isoformat()} "
        f"→ {daily[-1]['trade_date'].isoformat()}\n\n"
    )

    out.write("## Interpretation distribution\n\n")
    out.write("| Interpretation | Count | % |\n|---|---|---|\n")
    for level in _LEVELS:
        n = dist.get(level, 0)
        if n == 0:
            continue
        out.write(f"| {level} | {n} | {n / total * 100:.1f}% |\n")
    return out.getvalue()
