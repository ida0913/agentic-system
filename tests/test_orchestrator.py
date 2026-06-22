"""Integration tests for the orchestrator and the gate model."""

from __future__ import annotations

from control_plane.agents import AgentResult, default_registry
from control_plane.approvals import ApprovalQueue
from control_plane.audit import DecisionLog
from control_plane.cost import CostGovernor, CostLedger
from control_plane.machine import State, Status
from control_plane.orchestrator import MAX_RETRIES, Orchestrator
from control_plane.state import StateHeader, StateStore


def _wire(tmp_path, allowance=1_000_000, registry=None):
    store = StateStore(tmp_path)
    store.init(StateHeader(project_id="demo", tier="Standard"))
    queue = ApprovalQueue(tmp_path)
    log = DecisionLog(tmp_path, "demo")
    gov = CostGovernor(CostLedger(tmp_path), allowance=allowance)
    return Orchestrator(tmp_path, store, queue, log, gov, registry=registry), store, queue


def test_halts_at_first_gate(tmp_path):
    orch, store, queue = _wire(tmp_path)
    header = orch.run_to_gate()
    # PM runs in INTAKE -> DEFINE, then DEFINE raises the PRD gate.
    assert header.current_state is State.DEFINE
    assert header.status is Status.AWAITING_OPERATOR
    assert len(queue.pending()) == 1
    assert queue.pending()[0].gate == "PRD_APPROVAL"


def test_grant_advances_past_gate(tmp_path):
    orch, store, queue = _wire(tmp_path)
    orch.run_to_gate()
    gate = queue.pending()[0]
    orch.grant(gate.id, "adi")
    header = orch.run_to_gate()
    # Next blocking gate after DESIGN_REVIEW is the design approval.
    assert header.status is Status.AWAITING_OPERATOR
    assert queue.pending()[0].gate == "DESIGN_APPROVAL"


def test_full_pipeline_reaches_done(tmp_path):
    orch, store, queue = _wire(tmp_path)
    for _ in range(20):
        header = orch.run_to_gate()
        if header.status is Status.DONE:
            break
        pending = queue.pending()
        if pending:
            orch.grant(pending[0].id, "adi")
    assert store.read_header().current_state is State.DONE


def test_deny_sends_to_failed(tmp_path):
    orch, store, queue = _wire(tmp_path)
    orch.run_to_gate()
    gate = queue.pending()[0]
    orch.deny(gate.id, "adi")
    assert store.read_header().current_state is State.FAILED


def test_budget_halt_parks_project(tmp_path):
    orch, store, queue = _wire(tmp_path, allowance=100)  # tiny: first call exceeds
    # Spend immediately exhausts; governor should refuse the next mutating call.
    header = orch.run_to_gate()
    assert header.status is Status.AWAITING_OPERATOR
    assert store.read_header().budget_status in {"HALTED", "WARN", "OK"}


def test_agent_failure_retries_then_escalates(tmp_path):
    calls = {"n": 0}

    def failing(header, fetch_detail, workspace):
        calls["n"] += 1
        return AgentResult(ok=False, summary="boom")

    registry = default_registry()
    registry["PM"] = failing
    orch, store, queue = _wire(tmp_path, registry=registry)
    orch.run_to_gate()
    header = store.read_header()
    assert header.current_state is State.FAILED
    assert calls["n"] == MAX_RETRIES + 1  # initial try + retries, then escalate


def test_idempotent_step_at_gate(tmp_path):
    orch, store, queue = _wire(tmp_path)
    orch.run_to_gate()
    v1 = store.read_header().version
    orch.step()  # stepping while awaiting operator must be a no-op
    orch.step()
    assert store.read_header().version == v1
