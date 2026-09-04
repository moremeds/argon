"""Contract models for the generic agent-run transport (migration 148).

WHY `view` IS `dict[str, Any]` AND NOT A TYPED UNION
-----------------------------------------------------
Typing the document would mean a union that grows a member every time a writer
ships a new kind, and a deploy-ordering problem every time one changes shape:
argon would start refusing payloads it has no model for, on the writer's
release schedule rather than its own. The contract that actually earns its keep
is `schema_version` — the writer states which shape it sent, and the READER
decides whether it can render it. A section missing from a page is recoverable;
a rejected POST is a run that was never recorded at all.

WHAT IS VALIDATED HERE
-----------------------
Only the envelope: the identity and shape fields the store's CHECK constraints
also enforce, so a malformed row is refused at the boundary with a readable 422
instead of surfacing as a database integrity error.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import Field

from uw_scan.models._base import _preserve_public_module, _UwBase

RunOutcome = Literal["completed", "DEGRADED", "FAILED"]

#: Shape only. The set of legal tenants is not enumerated anywhere in this
#: transport: a new writer is a POST, not a release.
Tenant = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]

#: Opaque and writer-chosen. Argon never switches on the value here — the
#: meaning of a kind is a fact about one tenant's view layer.
Kind = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")]

WeekKey = Annotated[str, Field(pattern=r"^\d{4}-W\d{2}$")]


class AgentRunIngest(_UwBase):
    """One run, as the writer sends it."""

    tenant: Tenant
    kind: Kind
    run_day: date
    #: Writers normally send it; absent falls back to the ISO week of `run_day`.
    #: Only the writer knows a run is backward-looking, so the writer decides.
    week_key: WeekKey | None = None
    run_id: str = Field(min_length=1, max_length=200)
    code_sha: str = Field(min_length=1, max_length=64)
    schema_version: int = Field(ge=1)
    outcome: RunOutcome
    headline: str = Field(default="", max_length=2000)
    #: Opaque to argon, but never empty: a run with no document is a row a
    #: reader could open and find nothing in.
    view: dict[str, Any] = Field(min_length=1)
    report: dict[str, Any] = Field(default_factory=dict)


class AgentRunIngestResult(_UwBase):
    """`created=False` is the answer to a blind retry, not an error."""

    tenant: str
    kind: str
    run_day: date
    week_key: str
    version_no: int
    created: bool


class AgentRunWeek(_UwBase):
    week_key: str
    first_day: date
    last_day: date
    run_count: int
    day_count: int


class AgentRunWeekListResponse(_UwBase):
    tenant: str
    weeks: list[AgentRunWeek] = []


class AgentRunIndexRow(_UwBase):
    """A navigation row. Deliberately carries no document."""

    run_day: date
    kind: str
    run_id: str
    version_no: int
    outcome: str
    headline: str
    code_sha: str
    schema_version: int
    created_at: datetime


class AgentRunWeekResponse(_UwBase):
    tenant: str
    week_key: str
    runs: list[AgentRunIndexRow] = []


class AgentRunResponse(_UwBase):
    tenant: str
    week_key: str
    run_day: date
    kind: str
    run_id: str
    version_no: int
    outcome: str
    headline: str
    code_sha: str
    schema_version: int
    created_at: datetime
    view: dict[str, Any] = {}
    report: dict[str, Any] = {}


_preserve_public_module(
    AgentRunIngest,
    AgentRunIngestResult,
    AgentRunWeek,
    AgentRunWeekListResponse,
    AgentRunIndexRow,
    AgentRunWeekResponse,
    AgentRunResponse,
)
