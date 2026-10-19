"""The xenon API key must never reach a log record (PR #560 review).

websockets logs upgrade headers and frames at DEBUG, and a rejected
upgrade's response can echo the key back; argon's own error logs must not
carry it either. Synthetic key only.
"""

from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus
from types import SimpleNamespace

import pytest
import websockets
from pydantic import SecretStr
from websockets.frames import OP_BINARY, OP_TEXT, Frame

from uw_scan.sources.xenon_ws import _KeyRedactingLogger
from uw_scan.worker.massive_ws_consumer import _xenon_probe_loop

KEY = "sekrit-key-123"
KEY_HEX = " ".join(f"{b:02x}" for b in KEY.encode())


def _client_output(caplog) -> str:
    """Every client-side record as a handler would render it (the in-process
    test server logs what it receives under websockets.server)."""
    fmt = logging.Formatter("%(name)s %(message)s")
    return "\n".join(
        fmt.format(r) for r in caplog.records if r.name != "websockets.server"
    )


def test_redacting_logger_renders_and_masks_every_record_part(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="websockets.client")
    log = _KeyRedactingLogger(KEY)
    try:
        raise RuntimeError(f"server said {KEY}")
    except RuntimeError:
        log.debug("rejected %s", KEY.encode(), exc_info=True)
    log.debug("< %s", Frame(OP_TEXT, f'{{"echo":"{KEY}"}}'.encode()))
    log.debug("< %s", Frame(OP_BINARY, KEY.encode()))
    log.debug("%(k)s", {"k": KEY})
    log.debug(f"direct {KEY}", stack_info=True)

    assert len(caplog.records) == 5
    for r in caplog.records:
        assert r.args == ()  # handlers never see a raw arg object
        assert r.exc_info is None and r.stack_info is None
    out = _client_output(caplog)
    assert out.count("***") >= 5
    assert "Traceback" in out and "RuntimeError" in out  # exception kept, masked
    assert KEY not in out and KEY_HEX not in out


@pytest.mark.asyncio
async def test_probe_logs_no_key_when_rejection_echoes_it(caplog) -> None:
    caplog.set_level(logging.DEBUG)

    def reject(connection, request):
        resp = connection.respond(HTTPStatus.UNAUTHORIZED, f"bad key {KEY}\n")
        resp.headers["X-Echo-Key"] = request.headers["X-API-Key"]
        return resp

    async with websockets.serve(
        lambda ws: None, "127.0.0.1", 0, process_request=reject
    ) as server:
        port = server.sockets[0].getsockname()[1]
        settings = SimpleNamespace(
            xenon_ws_retry_primary_seconds=0.05,
            xenon_ws_url=f"ws://127.0.0.1:{port}",
            xenon_ws_port_file="",
            xenon_query_api_key=SecretStr(KEY),
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(_xenon_probe_loop(settings), timeout=0.5)

    out = _client_output(caplog)
    assert "xenon ws probe failed: 'InvalidStatus HTTP 401'" in out
    assert "X-Echo-Key: ***" in out  # the echoed header was logged, masked
    assert KEY not in out
