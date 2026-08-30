from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / ".test_durations"
NEW_BATCHING_TEST = (
    "tests/integration/regime/test_canary_v2a_fixture.py::"
    "test_vol_index_seed_is_value_preserving_idempotent_and_batched"
)


def test_duration_manifest_rejects_parallel_contention_as_single_test_cost():
    durations = json.loads(MANIFEST.read_text())

    # CI has two xdist workers per shard. Durations captured from an unsharded,
    # ten-worker local run included lock/checkpoint waits as if individual tests
    # cost 250-376 seconds; pytest-split then produced 11:45 and 7:20 shards.
    # A genuine >60-second test needs deliberate CI-calibrated evidence instead of
    # silently poisoning the scheduler manifest.
    assert max(durations.values()) < 60
    assert NEW_BATCHING_TEST in durations
