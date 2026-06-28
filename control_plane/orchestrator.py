"""The orchestrator.

The only component that decides what runs next. It reads the state header,
consults the state machine, runs the owning agent through the cost governor,
records the outcome in the decision log, and either advances state or halts at a
blocking gate. It owns retry and escalation, and it is idempotent: stepping a
project that sits at a gate or a terminal state is a no-op, so re-running after a
crash is safe (§4.1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .agents import Agent, default_registry
from .approvals import ApprovalQueue, ApprovalStatus
from .audit import DecisionLog
from .cost import CostGovernor
from .llm import DETAIL_KEY_CLARIFY_GATE, DETAIL_KEY_CLASSIFICATION
from .machine import FIX_CYCLE_CAP, State, Status, has_gate, is_terminal, spec
from .state import StateHeader, StateStore

MAX_RETRIES = 2

# Risk class per gate, used when raising approval objects.
_GATE_RISK = {
    "PRD_APPROVAL": "low",
    "TIER_RECLASSIFY": "low",
    "DESIGN_APPROVAL": "medium",
    "PUSH_APPROVAL": "medium",
    "MERGE_APPROVAL": "high",
    "DEPLOY_APPROVAL": "high",
}


class Orchestrator:
    """Drives one project through the state machine.

    Args:
        root: Project root directory (holds ``.agent/`` and ``wiki/``).
        store: The split state store.
        queue: The durable approval queue.
        log: The append-only decision log.
        governor: The cost governor wrapping agent calls.
        registry: Map of owner role -> agent callable. Defaults to stubs.
    """

    def __init__(
        self,
        root: Path,
        store: StateStore,
        queue: ApprovalQueue,
        log: DecisionLog,
        governor: CostGovernor,
        registry: Optional[dict[str, Agent]] = None,
    ) -> None:
        self._root = Path(root)
        self._store = store
        self._queue = queue
        self._log = log
        self._governor = governor
        self._registry = registry or default_registry()

    def step(self) -> StateHeader:
        """Advance the project by at most one unit of work.

        Returns the resulting header. Halts (returns unchanged) when the project
        is terminal, already awaiting the operator, or blocked by the governor.
        """
        header = self._store.read_header()

        if is_terminal(header.current_state) or header.status is Status.DONE:
            return header

        if header.status is Status.AWAITING_OPERATOR:
            if not header.open_gates:
                return header  # parked by the governor; resumes only on operator action
            resolved = self._resolve_open_gate(header)
            if resolved is None:
                return header  # still waiting on a gate
            header = resolved

        s = spec(header.current_state)

        # Pure pass-through state (no owning agent): advance immediately.
        if s.owner == "-":
            return self._advance(header)

        decision = self._governor.check(mutating=True)
        if not decision.allowed:
            return self._halt_budget(header, decision.status.value, decision.reason)

        agent = self._registry[s.owner]
        result = agent(header, self._store.read_detail, self._root)

        if not result.ok:
            return self._handle_failure(header)

        self._governor_record(s.owner, result.tokens)
        if result.detail_patch:
            self._store.write_detail(result.detail_patch)
            # Apply classification override written by the PM agent in Phase 2.
            cls = result.detail_patch.get(DETAIL_KEY_CLASSIFICATION)
            if cls:
                header.tier = cls.get("tier", header.tier)
                header.mode = cls.get("mode", header.mode)
                header.complexity = cls.get("complexity", header.complexity)
        self._log.append("AGENT_COMPLETE", f"{s.owner}: {result.summary}", s.owner)

        header.retry_count = 0

        # PM Phase 1 signals a clarify pause via a detail-blob key; park on that
        # approval instead of raising the normal state-machine gate.
        clarify_id = (result.detail_patch or {}).get(DETAIL_KEY_CLARIFY_GATE)
        if clarify_id:
            header.status = Status.AWAITING_OPERATOR
            header.open_gates = [clarify_id]
            self._log.append("GATE_RAISED", f"PM_CLARIFY ({clarify_id})", header.owner_agent)
            return self._store.write_header(header.version, header)

        if has_gate(header.current_state):
            return self._raise_gate(header, s.gate or "")
        return self._advance(header)

    def grant(self, approval_id: str, operator: str) -> StateHeader:
        """Grant a pending approval and step the project forward."""
        approval = self._queue.grant(approval_id, operator)
        self._log.append("GATE_GRANTED", f"{approval.gate} ({approval.id})", operator)
        return self.step()

    def deny(self, approval_id: str, operator: str) -> StateHeader:
        """Deny a pending approval, sending the project to FAILED for operator triage."""
        approval = self._queue.deny(approval_id, operator)
        self._log.append("GATE_DENIED", f"{approval.gate} ({approval.id})", operator)
        header = self._store.read_header()
        return self._to_failed(header, f"operator denied {approval.gate}")

    def run_to_gate(self, max_steps: int = 50) -> StateHeader:
        """Step repeatedly until the project halts at a gate or terminates.

        Termination is detected by the state version standing still across a
        step: a productive step (including a retry, which rewrites the header)
        always advances the version, so a version that does not move means the
        project is parked at a gate, blocked, or terminal.
        """
        header = self._store.read_header()
        for _ in range(max_steps):
            before_version = header.version
            header = self.step()
            if header.version == before_version:
                break
        return header

    # -- internals -----------------------------------------------------------

    def _advance(self, header: StateHeader) -> StateHeader:
        nxt = spec(header.current_state).nxt
        if nxt is None:
            raise RuntimeError(f"cannot advance from terminal state {header.current_state.value}")
        header.current_state = nxt
        header.owner_agent = spec(nxt).owner
        header.status = Status.DONE if nxt is State.DONE else Status.RUNNING
        return self._store.write_header(header.version, header)

    def _raise_gate(self, header: StateHeader, gate: str) -> StateHeader:
        approval = self._queue.request(
            gate=gate,
            project_id=header.project_id,
            action=f"advance {header.current_state.value} -> {spec(header.current_state).nxt.value}",
            risk_class=_GATE_RISK.get(gate, "medium"),
            requested_by=header.owner_agent,
        )
        header.status = Status.AWAITING_OPERATOR
        header.open_gates = [approval.id]
        self._log.append("GATE_RAISED", f"{gate} ({approval.id})", header.owner_agent)
        return self._store.write_header(header.version, header)

    def _resolve_open_gate(self, header: StateHeader) -> Optional[StateHeader]:
        for approval_id in header.open_gates:
            approval = self._queue.get(approval_id)
            if approval.status is ApprovalStatus.PENDING:
                return None
            if approval.status is ApprovalStatus.GRANTED:
                header.status = Status.RUNNING
                header.open_gates = []
                header = self._store.write_header(header.version, header)
                # Clarify gates re-run the current state's agent rather than advancing.
                if approval.gate == "PM_CLARIFY":
                    return header
                return self._advance(header)
            return self._to_failed(header, f"{approval.gate} denied")
        # No open gates recorded but status said awaiting: treat as runnable.
        header.status = Status.RUNNING
        return self._store.write_header(header.version, header)

    def _handle_failure(self, header: StateHeader) -> StateHeader:
        header.retry_count += 1
        if header.retry_count > MAX_RETRIES:
            return self._to_failed(header, f"agent failed {header.retry_count}x")
        self._log.append("AGENT_RETRY", f"attempt {header.retry_count}", header.owner_agent)
        return self._store.write_header(header.version, header)

    def _to_failed(self, header: StateHeader, reason: str) -> StateHeader:
        header.current_state = State.FAILED
        header.status = Status.FAILED
        header.open_gates = []
        self._log.append("ESCALATED", reason, "Orchestrator")
        return self._store.write_header(header.version, header)

    def _halt_budget(self, header: StateHeader, status: str, reason: str) -> StateHeader:
        target = State.BUDGET_UNKNOWN if status == "UNKNOWN" else State.HALTED_BUDGET
        if header.current_state is target:
            return header
        header.budget_status = status
        self._log.append("BUDGET_HALT", f"{status}: {reason}", "Governor")
        # Record the halt without losing the project's place: park status only.
        header.status = Status.AWAITING_OPERATOR
        return self._store.write_header(header.version, header)

    def _governor_record(self, agent: str, tokens: int) -> None:
        # The ledger lives inside the governor; record via its ledger handle.
        self._governor._ledger.record(agent, tokens)  # noqa: SLF001 (intentional internal use)
