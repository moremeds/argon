"""Guard: no two `Repository` mixins may define the same member name.

`Repository` composes ~34 domain mixins. Python's MRO silently keeps the
leftmost definition, so a duplicated method name is dead code that still looks
live — and a future edit to the losing copy is a silent no-op. This is how
`_VrpTradingMixin`'s mirror of `fetch_distinct_vrp_tickers` went unnoticed.
"""

from __future__ import annotations

from collections import defaultdict

from uw_scan.storage.repository import Repository


def test_no_duplicate_member_names_across_mixins() -> None:
    owners: dict[str, list[str]] = defaultdict(list)
    for base in Repository.__bases__:
        for name, value in vars(base).items():
            if name.startswith("__"):
                continue
            if not (callable(value) or isinstance(value, property)):
                continue
            owners[name].append(base.__name__)

    collisions = {name: mixins for name, mixins in owners.items() if len(mixins) > 1}
    assert not collisions, (
        "Repository mixins define the same name more than once; every mixin "
        "after the first in the MRO is dead code. Keep one definition: "
        f"{collisions}"
    )
