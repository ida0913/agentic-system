"""The split state store.

State is divided into a small *header* read by every agent on wake and a heavier
*detail* fetched only when an agent's job needs it (the token-economy split of
§4.2 and §6). Both persist as JSON files under a project's ``.agent/`` directory,
matching the GitHub-as-source-of-truth principle of §23.

Only the orchestrator may advance state, and every write is a versioned
compare-and-swap: a writer declares the version it observed, and the store
rejects the write if the on-disk version has moved on. This makes concurrent
agents race-safe without locks (§4.2, state-write discipline).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from .machine import State, Status


class StateConflict(RuntimeError):
    """Raised when a compare-and-swap write loses to a concurrent update."""


@dataclass
class StateHeader:
    """The tiny record every agent reads on wake (~200 tokens).

    The ``version`` field backs the compare-and-swap protocol; it is incremented
    by the store on every successful write and must never be set by callers.
    """

    project_id: str
    tier: str = "Standard"
    mode: str = "greenfield"
    current_state: State = State.INTAKE
    status: Status = Status.RUNNING
    owner_agent: str = "PM"
    complexity: str = "M"
    retry_count: int = 0
    fix_cycle_count: int = 0
    budget_status: str = "OK"
    open_gates: list[str] = field(default_factory=list)
    version: int = 0

    def to_json(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict, flattening enums to their values."""
        data = asdict(self)
        data["current_state"] = self.current_state.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "StateHeader":
        """Reconstruct a header from its serialised form."""
        data = dict(data)
        data["current_state"] = State(data["current_state"])
        data["status"] = Status(data["status"])
        return cls(**data)


class StateStore:
    """File-backed persistence for one project's split state.

    Args:
        root: The project root directory. State files are written under
            ``root/.agent/``.
    """

    def __init__(self, root: Path) -> None:
        self._dir = Path(root) / ".agent"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._header_path = self._dir / "state.header.json"
        self._detail_path = self._dir / "state.detail.json"

    @property
    def header_path(self) -> Path:
        """Filesystem path of the header file."""
        return self._header_path

    def init(self, header: StateHeader, detail: Optional[dict[str, Any]] = None) -> StateHeader:
        """Create the initial state for a new project.

        Raises:
            StateConflict: If state already exists for this project.
        """
        if self._header_path.exists():
            raise StateConflict(f"state already exists for {header.project_id}")
        header.version = 1
        self._write_header(header)
        self._detail_path.write_text(json.dumps(detail or {}, indent=2))
        return header

    def read_header(self) -> StateHeader:
        """Return the current header from disk."""
        return StateHeader.from_json(json.loads(self._header_path.read_text()))

    def read_detail(self) -> dict[str, Any]:
        """Return the current detail blob from disk."""
        return json.loads(self._detail_path.read_text())

    def write_header(self, expected_version: int, header: StateHeader) -> StateHeader:
        """Compare-and-swap write of the header.

        Args:
            expected_version: The version the caller observed when it began work.
            header: The new header to persist.

        Returns:
            The persisted header, with its ``version`` incremented.

        Raises:
            StateConflict: If the on-disk version no longer matches
                ``expected_version`` — the caller's view is stale and the write
                is rejected.
        """
        current = self.read_header()
        if current.version != expected_version:
            raise StateConflict(
                f"version moved {expected_version} -> {current.version}; write rejected"
            )
        header.version = expected_version + 1
        self._write_header(header)
        return header

    def write_detail(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Merge ``patch`` into the detail blob and persist it."""
        detail = self.read_detail()
        detail.update(patch)
        self._detail_path.write_text(json.dumps(detail, indent=2))
        return detail

    def _write_header(self, header: StateHeader) -> None:
        self._header_path.write_text(json.dumps(header.to_json(), indent=2))
