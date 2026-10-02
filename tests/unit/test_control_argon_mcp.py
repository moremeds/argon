"""Pure-logic checks for `control-argon mcp-token`. No DB, no network."""

from __future__ import annotations

import hashlib

import pytest

from uw_scan.control_argon import build_parser
from uw_scan.control_argon_mcp import cmd_mcp_token, create_token, hash_token


def test_hash_token_is_sha256_hex():
    token = "abc123-_XYZ"
    assert hash_token(token) == hashlib.sha256(token.encode()).hexdigest()
    assert len(hash_token(token)) == 64


def test_create_token_refuses_a_blank_label_before_touching_the_db():
    # The ValueError fires before conn is used, so None is a safe stand-in.
    with pytest.raises(ValueError, match="blank"):
        create_token(None, "   ")  # type: ignore[arg-type]


def test_mcp_token_parses_create_with_label():
    args = build_parser().parse_args(["mcp-token", "create", "grok"])
    assert (args.command, args.mcp_action, args.label) == ("mcp-token", "create", "grok")
    assert args.func is cmd_mcp_token


def test_mcp_token_parses_revoke_and_list():
    assert build_parser().parse_args(["mcp-token", "revoke", "openai"]).mcp_action == "revoke"
    listed = build_parser().parse_args(["mcp-token", "list"])
    assert listed.mcp_action == "list" and listed.func is cmd_mcp_token


def test_mcp_token_create_without_label_is_a_usage_error():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["mcp-token", "create"])


def test_mcp_token_bare_is_a_usage_error():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["mcp-token"])
