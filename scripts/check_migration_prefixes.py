from __future__ import annotations

from collections import defaultdict
from pathlib import Path


GRANDFATHERED_DUPLICATE_PREFIXES = frozenset(
    {
        "037",
        "038",
        "039",
        "040",
        "041",
        "042",
        "047",
        "052",
        "053",
        "054",
        "055",
    }
)


def duplicate_prefixes(migrations_dir: Path) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for path in migrations_dir.glob("*.sql"):
        prefix = path.name.split("_", 1)[0]
        if prefix.isdigit():
            grouped[prefix].append(path.name)
    return {prefix: sorted(names) for prefix, names in grouped.items() if len(names) > 1}


def unexpected_duplicate_prefixes(migrations_dir: Path) -> dict[str, list[str]]:
    duplicates = duplicate_prefixes(migrations_dir)
    return {
        prefix: names
        for prefix, names in duplicates.items()
        if prefix not in GRANDFATHERED_DUPLICATE_PREFIXES
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    duplicates = unexpected_duplicate_prefixes(root / "src/uw_scan/storage/migrations")
    if not duplicates:
        return 0
    for prefix, names in sorted(duplicates.items()):
        print(f"unexpected duplicate migration prefix {prefix}: {', '.join(names)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
