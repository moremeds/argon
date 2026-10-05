"""Budget, context and spec types shared by the data gap healer modules.

`RequestBudget` caps provider spend per bucket, `HealContext` carries the
repo, settings, budget and lazily built provider clients through one run,
and `HealSpec` binds a dataset's adapter to its writer and granularity.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from uw_scan.reports.data_gap_registry import REGISTRY
from uw_scan.reports.data_gap_types import (
    DatasetRegistryEntry,
)


_BUCKETS = ("uw", "massive", "external", "db")


def _beat(ctx, stage: str, entry, it: dict | None = None, **extra) -> None:
    """One progress beat, if this context has a heartbeat attached.

    Optional so the many unit tests that build a bare HealContext keep working;
    `execute_run` attaches one for every real run.
    """
    if ctx.heartbeat is None:
        return
    it = it or {}
    ctx.heartbeat.stage(
        stage,
        dataset=entry.table_name,
        item_id=it.get("id"),
        ticker=it.get("ticker"),
        data_date=it.get("data_date"),
        # ESTIMATED units, not real calls -- `est_per_item` is what the private
        # budget charges, and it is the number measured to diverge from UW's own
        # counter by roughly 15x on the replay adapters. Carrying it beside the
        # telemetry rows is what makes that divergence measurable per dataset.
        uw_est_spent=ctx.budget.spent.get("uw"),
        **extra,
    )


class RequestBudget:
    """Per-provider spend tracker. Only UW is capped; the rest are unbounded.

    `dataset_share` additionally caps any SINGLE dataset at that fraction of the
    UW cap, so one large backlog cannot drain the whole night and leave every
    other dataset on `skipped_budget`. None/1.0 reproduces the original
    drain-it-all behaviour exactly.
    """

    def __init__(
        self, uw_cap: int | None, *, dataset_share: float | None = None
    ) -> None:
        self.uw_cap = uw_cap
        self.dataset_share = dataset_share
        self.spent: dict[str, int] = {b: 0 for b in _BUCKETS}
        self.by_dataset: dict[str, int] = {}
        self._current: str | None = None

    def begin_dataset(self, dataset: str) -> None:
        self._current = dataset
        self.by_dataset.setdefault(dataset, 0)

    def _slice(self) -> int | None:
        if self.uw_cap is None or not self.dataset_share or self.dataset_share >= 1:
            return None
        return max(1, int(self.uw_cap * self.dataset_share))

    def can_spend(self, provider: str, n: int) -> bool:
        if provider != "uw" or self.uw_cap is None:
            return True
        if self.spent["uw"] + n > self.uw_cap:
            return False
        cap = self._slice()
        if cap is not None and self._current is not None:
            if self.by_dataset.get(self._current, 0) + n > cap:
                return False
        return True

    def record(self, provider: str, n: int) -> None:
        if provider in self.spent:
            self.spent[provider] += n
        if provider == "uw" and self._current is not None:
            self.by_dataset[self._current] = self.by_dataset.get(self._current, 0) + n

    def as_dict(self) -> dict[str, int]:
        return dict(self.spent)


@dataclass
class HealContext:
    repo: object  # uw_scan.storage.repository.Repository
    gap: object  # DataGapHealerRepository
    schema: str
    today: date
    budget: RequestBudget
    settings: object | None = None  # uw_scan.config.Settings (real adapters only)
    # Telemetry recorder for every provider client this context builds. Without
    # it the healer's UW spend never reaches `external_api_requests`, which is
    # the table `sources/uw_budget.read_snapshot` derives BOTH the pool spend and
    # the account counter from -- so an untelemetered healer is not merely
    # unobserved by the governor, it is arithmetically invisible to it.
    recorder: object | None = None
    heartbeat: object | None = None  # HealHeartbeat; created by execute_run
    run_id: int | None = None
    registry_by_table: dict[str, DatasetRegistryEntry] = field(default_factory=dict)
    _uw: object | None = field(default=None, repr=False)
    # (ticker, date) pairs already replayed in THIS heal run. One
    # run_single_stock call writes ~11 tables, so the ~11 datasets wired to
    # the replay adapter must fan in to a single UW spend per pair.
    _replayed: set = field(default_factory=set, repr=False)
    _massive: object | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.registry_by_table:
            self.registry_by_table = {e.table_name: e for e in REGISTRY}

    def uw_client(self):
        if self._uw is None:
            from uw_scan.api.client import UwClient

            self._uw = UwClient(
                api_key=self.settings.api_key.get_secret_value(),
                base_url=self.settings.base_url,
                timeout=self.settings.request_timeout_seconds,
                telemetry_recorder=self.recorder,
                job_name="data_gap_healer",
            )
        return self._uw

    def massive_provider(self):
        if self._massive is None:
            from uw_scan.sources.ohlc import MassiveOhlcProvider

            if self.settings.massive_api_key is None:
                raise RuntimeError(
                    "MASSIVE_API_KEY not set; daily_ohlc heal unavailable"
                )
            self._massive = MassiveOhlcProvider(
                api_key=self.settings.massive_api_key.get_secret_value(),
                base_url=self.settings.massive_base_url,
                timeout=self.settings.request_timeout_seconds,
                telemetry_recorder=self.recorder,
                job_name="data_gap_healer",
            )
        return self._massive


@dataclass(frozen=True)
class HealSpec:
    adapter: str
    provider: str
    granularity: str
    run: Callable
    est_per_item: int = 1  # estimated provider calls; charged to the budget bucket
