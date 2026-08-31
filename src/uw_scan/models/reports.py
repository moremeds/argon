"""Contract models for versioned research reports (M7).

WHY THE DELTA IS PART OF THE READ CONTRACT
-------------------------------------------
`GET` a report and you get the current version AND what changed since the last
one, in the same payload. Splitting them into two calls would let a surface
render a report without its delta, which is exactly the surface a versioned
report exists to replace: a document that looks the same every time and quietly
means something different.

WHY MANIFEST FIELDS ARE TYPED AND SCOPE IS NOT
-----------------------------------------------
`engine_version`, `taxonomy_version`, `evidence_policy` and `as_of` are what a
reader must compare between two versions to know whether a move is news or a
re-versioning, so they are named fields a client can switch on. `scope` differs
by report type (a ticker, a chain, a member list) and typing it would mean a
union that grows every time a report type is added.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from uw_scan.models._base import _preserve_public_module, _UwBase
from uw_scan.models.radar import ClaimAuthority

ReportType = Literal["company", "comparison", "chain", "watchlist"]

#: `partial` is not an error. A report that refused to publish because one block
#: was unsupported would be strictly less useful than one that publishes and
#: names the gap — which is what `partial` plus the `unsupported` block do.
ReportStatus = Literal["draft", "partial", "published", "superseded", "stale"]

#: Same six-way state model as the radar, restated for reports. `no_report` is
#: distinct from `no_coverage`: the first means nobody has asked for this report
#: yet, the second means Argon holds nothing to build it from.
ReportState = Literal["ok", "no_report", "no_coverage", "failed_run"]


class ReportManifest(_UwBase):
    """The frozen question. Everything needed to reproduce the content."""

    engine_version: str | None
    taxonomy_version: str | None
    evidence_policy: str
    as_of: str
    assembler_version: str
    scope: dict = {}


class ReportBlock(_UwBase):
    """One section. Carries its evidence or its derivation — never neither.

    `authority` is null for a block that makes no ordering or directional claim.
    The type cannot express `investment_ranking`, which is the program ceiling
    made unrepresentable rather than merely unused.
    """

    ordinal: int
    block_kind: str
    title: str
    payload: dict = {}
    evidence: dict = {}
    derivation: str | None = None
    authority: ClaimAuthority | None = None


class ResearchReportModel(_UwBase):
    report_id: int
    report_key: str
    report_type: ReportType
    version_no: int
    title: str
    manifest: ReportManifest
    content_hash: str
    status: ReportStatus
    superseded_by: int | None = None
    created_at: datetime
    blocks: list[ReportBlock] = []


class ReportVersionRef(_UwBase):
    """One entry in the version history — enough to fetch or compare it."""

    version_no: int
    content_hash: str
    status: ReportStatus
    created_at: datetime


class ManifestChange(_UwBase):
    """A METHOD change. Reported apart from value moves, and stated first."""

    field: str
    before: str | None = None
    after: str | None = None


class BlockValueChange(_UwBase):
    """One number that moved. `before`/`after` null means it appeared/vanished."""

    path: str
    before: float | None = None
    after: float | None = None
    change: float | None = None


class BlockChange(_UwBase):
    block_kind: str
    title: str
    changes: list[BlockValueChange] = []


class BlockRef(_UwBase):
    block_kind: str
    title: str


class ReportDeltaModel(_UwBase):
    """What changed since the previous version, or that there wasn't one."""

    is_first_version: bool
    manifest: list[ManifestChange] = []
    added: list[BlockRef] = []
    removed: list[BlockRef] = []
    moved: list[BlockChange] = []
    summary: str


class ReportResponse(_UwBase):
    state: ReportState
    #: Why a non-`ok` state happened, in a sentence a surface can render.
    reason: str | None = None
    report: ResearchReportModel | None = None
    delta: ReportDeltaModel | None = None
    versions: list[ReportVersionRef] = []


class ReportSummary(_UwBase):
    report_key: str
    report_type: ReportType
    version_no: int
    title: str
    status: ReportStatus
    created_at: datetime


class ReportListResponse(_UwBase):
    reports: list[ReportSummary] = []


_preserve_public_module(
    ReportManifest,
    ReportBlock,
    ResearchReportModel,
    ReportVersionRef,
    ManifestChange,
    BlockValueChange,
    BlockChange,
    BlockRef,
    ReportDeltaModel,
    ReportResponse,
    ReportSummary,
    ReportListResponse,
)
