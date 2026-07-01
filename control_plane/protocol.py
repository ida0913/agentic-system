"""Agent contract — the shared types every agent implementation depends on.

Keeping this separate from agents.py breaks the import cycle between
agents.py (registries, stubs) and agents_pm.py (real implementations):
both import from here; neither imports from the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .state import StateHeader

VALID_TIERS = {"Micro", "Standard", "Full"}


@dataclass
class AgentResult:
    """What an agent returns to the orchestrator.

    Attributes:
        ok: Whether the agent completed its work successfully.
        tokens: Tokens consumed (recorded by the cost governor).
        detail_patch: Keys to merge into the state detail blob.
        summary: One-line human-readable summary for the decision log.
        artifacts: Paths of files the agent wrote, for traceability.
    """

    ok: bool = True
    tokens: int = 0
    detail_patch: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    artifacts: list[str] = field(default_factory=list)


class Agent(Protocol):
    """Structural type for an agent callable."""

    def __call__(
        self,
        header: StateHeader,
        fetch_detail: Callable[[], dict[str, Any]],
        workspace: Path,
    ) -> AgentResult: ...
