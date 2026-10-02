"""control-argon mcp-token — bearer tokens for the agent MCP server.

The plaintext token is printed exactly once by `create`; the DB stores only
its sha256 hex, which is all web/mcp/server.ts needs to verify a bearer.

    uv run control-argon mcp-token create grok
    uv run control-argon mcp-token list
    uv run control-argon mcp-token revoke grok

Spec: docs/superpowers/specs/2026-10-02-agent-mcp-design.md (Auth row).
Own module because control_argon.py is already at the size budget; it is wired
into that file's parser only.
"""

from __future__ import annotations

import argparse
import hashlib
import secrets
from datetime import datetime

import psycopg

from uw_scan.config import Settings


def hash_token(token: str) -> str:
    """What the DB stores — sha256 hex of the plaintext bearer."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(
    conn: psycopg.Connection, label: str, *, schema: str = "uw_scan"
) -> str:
    """Mint a token for `label`, store its hash, return the plaintext.

    ValueError on a blank label or one that already exists — revoked labels
    stay reserved too (rotation mints a new label, never rewrites a row).
    """
    label = label.strip()
    if not label:
        raise ValueError("label must not be blank")
    token = secrets.token_urlsafe(32)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {schema}.mcp_token (label, token_hash) "
                "VALUES (%s, %s)",
                (label, hash_token(token)),
            )
        conn.commit()
    except psycopg.errors.UniqueViolation:
        conn.rollback()
        raise ValueError(
            f"label {label!r} already exists — pick a new one"
        ) from None
    return token


def revoke_token(
    conn: psycopg.Connection, label: str, *, schema: str = "uw_scan"
) -> str:
    """Set revoked_at. Returns 'revoked' or 'already_revoked' (idempotent);
    ValueError when the label was never minted."""
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE {schema}.mcp_token SET revoked_at = now() "
            "WHERE label = %s AND revoked_at IS NULL",
            (label,),
        )
        if cur.rowcount:
            conn.commit()
            return "revoked"
        cur.execute(f"SELECT 1 FROM {schema}.mcp_token WHERE label = %s", (label,))
        exists = cur.fetchone() is not None
    conn.rollback()
    if exists:
        return "already_revoked"
    raise ValueError(f"no token with label {label!r}")


def list_tokens(
    conn: psycopg.Connection, *, schema: str = "uw_scan"
) -> list[tuple[str, datetime, datetime | None]]:
    """(label, created_at, revoked_at) — never the hash."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT label, created_at, revoked_at FROM {schema}.mcp_token "
            "ORDER BY label"
        )
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def cmd_mcp_token(args: argparse.Namespace) -> int:
    # Local import — control_argon imports this module for its parser, so a
    # top-level import of the emit helpers back would be circular.
    from uw_scan.control_argon import FAIL, OK, emit

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        if args.mcp_action == "create":
            try:
                token = create_token(conn, args.label, schema=settings.db_schema)
            except ValueError as exc:
                emit(FAIL, str(exc))
                return 1
            emit(
                OK,
                f"created mcp token for {args.label!r} — store it now; "
                "it is shown once and only the sha256 hex is kept:",
            )
            print(token)
            return 0
        if args.mcp_action == "revoke":
            try:
                outcome = revoke_token(conn, args.label, schema=settings.db_schema)
            except ValueError as exc:
                emit(FAIL, str(exc))
                return 1
            emit(OK, f"mcp token {args.label!r}: {outcome.replace('_', ' ')}")
            return 0
        rows = list_tokens(conn, schema=settings.db_schema)
        if not rows:
            emit(OK, "no mcp tokens")
            return 0
        for label, created, revoked in rows:
            state = f"revoked {revoked:%Y-%m-%d %H:%M}" if revoked else "active"
            print(f"{label:<16} {state:<24} created {created:%Y-%m-%d %H:%M}")
        return 0
