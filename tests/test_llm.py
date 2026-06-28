"""Unit tests for control_plane.llm — parse_json and call_claude."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from control_plane.llm import LLMError, LLMParseError, call_claude, parse_json


# ---------------------------------------------------------------------------
# parse_json
# ---------------------------------------------------------------------------

def test_parse_json_clean():
    assert parse_json('{"key": "value"}') == {"key": "value"}


def test_parse_json_json_fence():
    assert parse_json('```json\n{"key": "value"}\n```') == {"key": "value"}


def test_parse_json_plain_fence():
    assert parse_json('```\n{"key": "value"}\n```') == {"key": "value"}


def test_parse_json_whitespace():
    assert parse_json('  \n{"key": "value"}\n  ') == {"key": "value"}


def test_parse_json_malformed_raises():
    with pytest.raises(LLMParseError, match="not valid JSON"):
        parse_json("not json at all")


def test_parse_json_non_dict_raises():
    with pytest.raises(LLMParseError, match="expected object"):
        parse_json("[1, 2, 3]")


# ---------------------------------------------------------------------------
# call_claude
# ---------------------------------------------------------------------------

def _proc(returncode: int = 0, stdout: str = "response", stderr: str = "") -> MagicMock:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def test_call_claude_nonzero_exit_raises_with_stderr_snippet():
    with patch("control_plane.llm.subprocess.run", return_value=_proc(returncode=1, stderr="auth error")):
        with pytest.raises(LLMError, match="auth error"):
            call_claude("sys", "user", "claude-sonnet-4-6", 1000)


def test_call_claude_timeout_raises():
    with patch(
        "control_plane.llm.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=180),
    ):
        with pytest.raises(LLMError, match="timed out"):
            call_claude("sys", "user", "claude-sonnet-4-6", 1000)


def test_call_claude_empty_output_raises():
    with patch("control_plane.llm.subprocess.run", return_value=_proc(stdout="   ")):
        with pytest.raises(LLMError, match="empty output"):
            call_claude("sys", "user", "claude-sonnet-4-6", 1000)
