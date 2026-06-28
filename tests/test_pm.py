"""Tests for the two-phase PM agent.

``call_claude`` is always mocked so the test suite never hits the network.
The tests drive the full orchestrator loop to prove the gate model works
end-to-end with the real PM agent wired in.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from control_plane.agents import AgentResult, default_registry
from control_plane.agents_pm import PMAgent
from control_plane.approvals import ApprovalQueue, ApprovalStatus
from control_plane.audit import DecisionLog
from control_plane.cost import CostGovernor, CostLedger
from control_plane.machine import State, Status
from control_plane.orchestrator import Orchestrator
from control_plane.state import StateHeader, StateStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PHASE1_REPLY = json.dumps({
    "questions": [
        "Is this for internal use only or will external users access it?",
        "What is the expected data volume per day?",
        "Are there existing systems this must integrate with?",
    ],
    "provisional": {
        "tier": "Standard",
        "mode": "greenfield",
        "physical": False,
        "complexity": "M",
    },
    "reasoning_note": "These questions directly determine persistence and integration scope.",
})

PHASE2_REPLY = json.dumps({
    "classification": {
        "tier": "Standard",
        "mode": "greenfield",
        "physical": False,
        "complexity": "M",
    },
    "prd": {
        "overview_goals": "Build a lightweight task tracker for the operator.",
        "problem_statement": "Manual task management via notes is error-prone.",
        "target_audience": "Internal — single operator (Adi)",
        "success_metrics": [
            "Task retrieval latency < 200 ms",
            "Zero data loss across 30-day retention window",
        ],
        "features_requirements": {
            "functional": ["Create, read, update, delete tasks"],
            "non_functional": ["SQLite persistence", "CLI interface"],
            "usability": ["Single command to add a task"],
        },
        "user_journey": "Operator runs `task add` -> task stored -> operator runs `task list`",
        "assumptions_constraints": ["Python 3.11+", "No external dependencies beyond stdlib"],
        "competitive_context": "N/A — internal",
        "out_of_scope": ["Web UI", "Multi-user support"],
        "acceptance_criteria": [
            "Adding a task persists it across process restarts",
            "Listing tasks shows all stored tasks in creation order",
        ],
    },
    "dmaic_plan": [
        {
            "phase": "Define",
            "deliverables": ["PRD", "SIPOC"],
            "owner": "PM",
            "entry": "Operator request received",
            "exit": "PRD approved",
        }
    ],
    "sipoc": {
        "suppliers": ["Operator"],
        "inputs": ["Task description"],
        "process": ["task add", "task list"],
        "outputs": ["Stored task", "Task list"],
        "customers": ["Adi"],
    },
    "ctq_tree": [
        {
            "need": "Fast retrieval",
            "driver": "Low latency",
            "measurable_target": "< 200 ms p99",
        }
    ],
    "gemba_guide": None,
    "summary_card": "Lightweight CLI task tracker.\nStandard / greenfield / M.\n1 DMAIC phase defined.",
})


def _wire(
    tmp_path: Path,
    allowance: int = 1_000_000,
    registry: dict | None = None,
) -> tuple[Orchestrator, StateStore, ApprovalQueue]:
    """Wire a fresh orchestrator with a real PM agent and stub everything else."""
    store = StateStore(tmp_path)
    store.init(
        StateHeader(project_id="demo", tier="Standard"),
        detail={"request": "Build a simple task tracker CLI for personal use."},
    )
    queue = ApprovalQueue(tmp_path)
    log = DecisionLog(tmp_path, "demo")
    gov = CostGovernor(CostLedger(tmp_path), allowance=allowance)

    if registry is None:
        reg = default_registry()
        reg["PM"] = PMAgent()
        registry = reg

    return Orchestrator(tmp_path, store, queue, log, gov, registry=registry), store, queue


# ---------------------------------------------------------------------------
# Test 1 — Phase 1 parks the project at PM_CLARIFY
# ---------------------------------------------------------------------------

def test_phase1_parks_at_pm_clarify(tmp_path: Path) -> None:
    orch, store, queue = _wire(tmp_path)

    with patch("control_plane.agents_pm.call_claude", return_value=PHASE1_REPLY):
        header = orch.run_to_gate()

    assert header.status is Status.AWAITING_OPERATOR
    assert header.current_state is State.DEFINE

    pending = queue.pending()
    assert len(pending) == 1
    assert pending[0].gate == "PM_CLARIFY"

    detail = store.read_detail()
    assert len(detail["questions"]) == 3
    assert detail["provisional"]["tier"] == "Standard"


# ---------------------------------------------------------------------------
# Test 2 — Supplying answers + stepping produces PRD.md, parks at PRD_APPROVAL
# ---------------------------------------------------------------------------

def test_phase2_produces_prd_and_parks_at_prd_approval(tmp_path: Path) -> None:
    orch, store, queue = _wire(tmp_path)

    with patch("control_plane.agents_pm.call_claude", return_value=PHASE1_REPLY):
        orch.run_to_gate()

    # Operator writes answers and grants PM_CLARIFY.
    store.write_detail({
        "clarify_answers": {
            "1": "Internal use only.",
            "2": "Fewer than 100 tasks per day.",
            "3": "No existing systems.",
        }
    })
    pm_clarify = queue.pending()[0]
    assert pm_clarify.gate == "PM_CLARIFY"

    with patch("control_plane.agents_pm.call_claude", return_value=PHASE2_REPLY):
        header = orch.grant(pm_clarify.id, "adi")
        header = orch.run_to_gate()

    assert header.current_state is State.DEFINE
    assert header.status is Status.AWAITING_OPERATOR

    prd_approval = queue.pending()[0]
    assert prd_approval.gate == "PRD_APPROVAL"

    prd_path = tmp_path / "wiki" / "projects" / "demo" / "PRD.md"
    assert prd_path.exists()
    content = prd_path.read_text()
    assert "# PRD" in content
    assert "Overview" in content

    # SIPOC section rendered
    assert "## SIPOC" in content
    assert "**Suppliers**" in content
    assert "**Inputs**" in content
    assert "**Process**" in content
    assert "**Outputs**" in content
    assert "**Customers**" in content
    assert "- Operator" in content  # from PHASE2_REPLY suppliers

    # CTQ Tree section rendered
    assert "## CTQ Tree" in content
    assert "Fast retrieval" in content
    assert "Low latency" in content
    assert "< 200 ms p99" in content

    detail = store.read_detail()
    assert "prd" in detail
    assert detail["_classification"]["tier"] == "Standard"

    # Header classification should be patched too.
    final_header = store.read_header()
    assert final_header.tier == "Standard"
    assert final_header.mode == "greenfield"
    assert final_header.complexity == "M"


# ---------------------------------------------------------------------------
# Test 3 — Malformed JSON triggers retries then escalates to FAILED
# ---------------------------------------------------------------------------

def test_malformed_reply_retries_then_fails(tmp_path: Path) -> None:
    orch, store, queue = _wire(tmp_path)

    with patch("control_plane.agents_pm.call_claude", return_value="not json at all !!!"):
        header = orch.run_to_gate()

    assert header.current_state is State.FAILED


# ---------------------------------------------------------------------------
# Test 4 — Granting PRD_APPROVAL advances to DESIGN
# ---------------------------------------------------------------------------

def test_grant_prd_approval_advances_to_design(tmp_path: Path) -> None:
    orch, store, queue = _wire(tmp_path)

    with patch("control_plane.agents_pm.call_claude", return_value=PHASE1_REPLY):
        orch.run_to_gate()

    store.write_detail({"clarify_answers": {"1": "Internal", "2": "Low volume", "3": "None"}})
    pm_clarify = queue.pending()[0]

    with patch("control_plane.agents_pm.call_claude", return_value=PHASE2_REPLY):
        orch.grant(pm_clarify.id, "adi")
        orch.run_to_gate()

    prd_approval = queue.pending()[0]
    assert prd_approval.gate == "PRD_APPROVAL"

    header = orch.grant(prd_approval.id, "adi")
    header = orch.run_to_gate()

    # Past PRD_APPROVAL the stub Architect runs immediately; the system parks at the
    # next blocking gate (DESIGN_APPROVAL on DESIGN_REVIEW).
    assert header.current_state is not State.DEFINE
    assert header.status is Status.AWAITING_OPERATOR
    next_gate = queue.pending()[0]
    assert next_gate.gate == "DESIGN_APPROVAL"
