"""Thin wrapper around the Claude CLI for model calls.

Uses the local ``claude`` CLI (subscription credentials) rather than an
``ANTHROPIC_API_KEY`` environment variable, so the system runs against the
operator's subscription quota instead of metered pay-as-you-go. Usage credits
are left disabled at the Claude Code level: quota exhaustion halts the call
rather than charging.
"""

from __future__ import annotations

import json
import subprocess


class LLMError(RuntimeError):
    """Raised when the ``claude`` CLI call fails (non-zero exit, empty output, timeout)."""


class LLMParseError(ValueError):
    """Raised when the model's reply cannot be parsed as strict JSON."""


def call_claude(system: str, user: str, model: str, max_tokens: int) -> str:  # noqa: ARG001
    """Call Claude via the local CLI and return the raw text response.

    The system prompt is passed as a stable prefix so the CLI can cache it
    across repeated calls. The user message is written to stdin to avoid
    shell-quoting issues with long or multi-line content.

    ``max_tokens`` is accepted for interface symmetry with the Messages API but
    is not forwarded to the CLI (no CLI flag exists); the model's default output
    ceiling applies.

    Args:
        system: System prompt — stable, cacheable, never rebuilt per call.
        user: User-turn content for this specific request.
        model: Model ID (e.g. ``"claude-sonnet-4-6"``).
        max_tokens: Soft token hint (not enforced by the CLI wrapper).

    Returns:
        Raw text from the model response, whitespace-stripped.

    Raises:
        LLMError: If the subprocess exits non-zero, times out, or returns empty output.
    """
    cmd = [
        "claude",
        "--print",
        "--model", model,
        "--system-prompt", system,
        "--output-format", "text",
        "--bare",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=user,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise LLMError("claude CLI timed out after 180 s") from exc

    if result.returncode != 0:
        snippet = (result.stderr or result.stdout or "")[:300]
        raise LLMError(f"claude CLI exited {result.returncode}: {snippet}")

    text = result.stdout.strip()
    if not text:
        raise LLMError("claude CLI returned empty output")
    return text


def parse_json(text: str) -> dict:
    """Parse strict JSON from a model reply.

    Tolerates leading/trailing whitespace (the model sometimes pads its output)
    but rejects anything that is genuinely not a JSON object.

    Args:
        text: Raw text returned by the model.

    Returns:
        Parsed dict.

    Raises:
        LLMParseError: If the text is not valid JSON after stripping whitespace.
    """
    stripped = text.strip()
    try:
        result = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LLMParseError(
            f"model reply is not valid JSON: {stripped[:120]!r}"
        ) from exc
    if not isinstance(result, dict):
        raise LLMParseError(
            f"model reply parsed to {type(result).__name__}, expected object"
        )
    return result
