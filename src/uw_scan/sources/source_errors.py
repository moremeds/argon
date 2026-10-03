"""Shared failure signal for external read clients (I-15, I-17).

A client returns its normal shape on a 2xx: an empty list/dict/None there means
"the source answered and has no data", nothing else. When the source could not
answer -- a transport error, a non-2xx, an undecodable body, or a body of the
wrong shape -- the client raises SourceUnavailable instead. Clients catch only
those failures, so a programming error such as a TypeError still propagates.
"""

from __future__ import annotations


class SourceUnavailable(Exception):
    """An external source could not answer this request."""

    def __init__(self, source: str, detail: str) -> None:
        super().__init__(f"{source}: {detail}")
        self.source = source
        self.detail = detail
