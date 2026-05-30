"""Embedded trade-skills knowledge base (v6.0).

Loads the vendored markdown library at import time into a single string
constant. The model subprocess has no filesystem, so the KB must be baked
into the prompt at build time. Kept in its own module so prompt assembly
stays under the line budget (the constant is pure data, like prompt_text.py).
"""

from __future__ import annotations

from importlib import resources

_KB_DIR = resources.files(__package__).joinpath("kb")


def _sorted_md(subdir: str) -> list[str]:
    base = _KB_DIR.joinpath(subdir)
    names = sorted(p.name for p in base.iterdir() if p.name.endswith(".md"))
    return [f"{subdir}/{name}" for name in names]


def _read(rel: str) -> str:
    return _KB_DIR.joinpath(rel).read_text(encoding="utf-8")


def _build() -> str:
    order = [
        ("Operating principles & 3-axis framework", ["SKILL.md"]),
        (
            "Frameworks",
            [
                "frameworks/gamma-framework.md",
                "frameworks/strategies.md",
                "frameworks/price-action-framework.md",
            ],
        ),
        ("Pitfalls", _sorted_md("pitfalls")),
        ("Case studies", _sorted_md("ticker")),
    ]
    parts: list[str] = ["# TRADE FRAMEWORK KNOWLEDGE (ported from trade-skills)\n"]
    for section, files in order:
        parts.append(f"\n\n## {section}\n")
        for rel in files:
            parts.append(f"\n\n### {rel}\n\n{_read(rel)}")
    return "".join(parts)


TRADE_FRAMEWORK_KNOWLEDGE = _build()
