"""The durable approval queue.

Approvals are first-class objects living in the queue, which is the source of
truth; any chat surface (Slack) is only a view onto it (§6.4). Because the queue
persists independently, a transport outage never loses a pending approval, and
the system can continue non-gated work while one project waits.

Grants are idempotent and carry the granting identity. No timeout ever implies
consent — an ungranted approval simply remains pending forever until acted on.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class ApprovalStatus(str, Enum):
    """Lifecycle of an approval object."""

    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


@dataclass
class Approval:
    """A single operator decision the system is waiting on.

    Attributes:
        gate: The gate name from the state machine (e.g. ``PRD_APPROVAL``).
        project_id: The project this approval belongs to.
        action: Human-readable description of what will happen on grant.
        risk_class: One of ``low`` / ``medium`` / ``high`` for triage.
        requested_by: The agent that raised the request.
        status: Current lifecycle status.
        decided_by: The authenticated operator identity that decided it.
        id: Stable unique identifier.
        created_at: Unix timestamp when the request was raised.
    """

    gate: str
    project_id: str
    action: str
    risk_class: str
    requested_by: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: Optional[str] = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)

    def to_json(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Approval":
        """Reconstruct an approval from its serialised form."""
        data = dict(data)
        data["status"] = ApprovalStatus(data["status"])
        return cls(**data)


class ApprovalQueue:
    """File-backed queue of approval objects for one project."""

    def __init__(self, root: Path) -> None:
        self._path = Path(root) / ".agent" / "approvals.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("[]")

    def request(
        self, gate: str, project_id: str, action: str, risk_class: str, requested_by: str
    ) -> Approval:
        """Raise a new pending approval and persist it."""
        approval = Approval(
            gate=gate,
            project_id=project_id,
            action=action,
            risk_class=risk_class,
            requested_by=requested_by,
        )
        items = self._load()
        items.append(approval)
        self._save(items)
        return approval

    def grant(self, approval_id: str, operator: str) -> Approval:
        """Grant an approval on behalf of an authenticated operator.

        Granting an already-granted approval is idempotent: it returns the same
        object unchanged rather than re-deciding it.

        Raises:
            KeyError: If no approval with ``approval_id`` exists.
            PermissionError: If ``operator`` is falsy (identity is required).
        """
        return self._decide(approval_id, operator, ApprovalStatus.GRANTED)

    def deny(self, approval_id: str, operator: str) -> Approval:
        """Deny an approval on behalf of an authenticated operator."""
        return self._decide(approval_id, operator, ApprovalStatus.DENIED)

    def pending(self) -> list[Approval]:
        """Return all approvals still awaiting a decision."""
        return [a for a in self._load() if a.status is ApprovalStatus.PENDING]

    def get(self, approval_id: str) -> Approval:
        """Return a single approval by id."""
        for item in self._load():
            if item.id == approval_id:
                return item
        raise KeyError(approval_id)

    def _decide(self, approval_id: str, operator: str, status: ApprovalStatus) -> Approval:
        if not operator:
            raise PermissionError("approval requires an authenticated operator identity")
        items = self._load()
        for item in items:
            if item.id != approval_id:
                continue
            if item.status is not ApprovalStatus.PENDING:
                return item  # idempotent: already decided
            item.status = status
            item.decided_by = operator
            self._save(items)
            return item
        raise KeyError(approval_id)

    def _load(self) -> list[Approval]:
        return [Approval.from_json(d) for d in json.loads(self._path.read_text())]

    def _save(self, items: list[Approval]) -> None:
        self._path.write_text(json.dumps([a.to_json() for a in items], indent=2))
