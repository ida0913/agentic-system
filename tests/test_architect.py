"""Tests for the Architect agent.

``call_claude`` is always mocked so the test suite never hits the network.
Tests start the project in State.DESIGN directly to avoid re-testing PM phases.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from control_plane.agents import default_registry
from control_plane.agents_architect import ArchitectAgent
from control_plane.approvals import ApprovalQueue
from control_plane.audit import DecisionLog
from control_plane.cost import CostGovernor, CostLedger
from control_plane.machine import State, Status
from control_plane.orchestrator import Orchestrator
from control_plane.state import StateHeader, StateStore


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_PRD = {
    "overview_goals": "Build a lightweight task tracker.",
    "problem_statement": "Manual task management is error-prone.",
    "target_audience": "Internal — single operator",
    "success_metrics": ["Retrieval latency < 200 ms"],
    "features_requirements": {
        "functional": ["CRUD tasks"],
        "non_functional": ["SQLite persistence"],
        "usability": ["Single CLI command"],
    },
    "user_journey": "Operator runs `task add` -> stored -> `task list`",
    "assumptions_constraints": ["Python 3.11+"],
    "competitive_context": "N/A",
    "out_of_scope": ["Web UI"],
    "acceptance_criteria": ["Tasks survive process restarts"],
}

_CLASSIFICATION = {"tier": "Standard", "mode": "greenfield", "physical": False, "complexity": "M"}

VALID_REPLY = json.dumps({
    "tier_assessment": {
        "verdict": "agree",
        "current_tier": "Standard",
        "recommended_tier": "Standard",
        "reason": "Single-service scope with SQLite persistence fits Standard.",
    },
    "tech_stack_options": [
        {
            "name": "Python + SQLite + Click",
            "pros": ["Simple", "stdlib-friendly"],
            "cons": ["No async"],
            "best_if": "Solo operator, no concurrency needed.",
        },
        {
            "name": "Python + SQLite + Typer",
            "pros": ["Type hints", "Auto-completion"],
            "cons": ["Extra dependency"],
            "best_if": "Operator wants richer CLI UX.",
        },
    ],
    "design_doc": {
        "components": ["CLI entrypoint", "SQLite persistence layer"],
        "data_flow": "CLI -> persistence -> stdout",
        "key_decisions": ["SQLite file location", "[OPERATOR DECISION] retention policy"],
        "open_questions": ["Should tasks support tags?"],
    },
    "operator_decisions": [
        {
            "decision": "Data retention policy",
            "options": ["Keep indefinitely", "Purge after 90 days"],
            "why_it_matters": "Determines storage growth over time.",
        }
    ],
    "summary_card": "Standard tier confirmed.\n2 stack options presented.\n1 operator decision raised.",
})

CHALLENGE_REPLY = json.dumps({
    "tier_assessment": {
        "verdict": "challenge",
        "current_tier": "Micro",
        "recommended_tier": "Standard",
        "reason": "External Craigslist integration adds anti-automation risk.",
    },
    "tech_stack_options": [
        {
            "name": "Playwright + Python",
            "pros": ["Mature", "Good error reporting"],
            "cons": ["Browser overhead"],
            "best_if": "Full-page automation required.",
        },
        {
            "name": "requests + Selenium",
            "pros": ["Lightweight"],
            "cons": ["Brittle selector management"],
            "best_if": "Simpler page interactions.",
        },
    ],
    "design_doc": {
        "components": ["Scheduler", "Browser driver", "Logger"],
        "data_flow": "Cron -> scheduler -> browser driver -> Craigslist -> log",
        "key_decisions": ["[OPERATOR DECISION] Proceed despite ToS risk"],
        "open_questions": ["Will Craigslist change their form structure?"],
    },
    "operator_decisions": [
        {
            "decision": "Proceed despite Craigslist anti-automation ToS",
            "options": ["Proceed", "Abort"],
            "why_it_matters": "Account ban risk.",
        }
    ],
    "summary_card": "Tier challenged: Micro -> Standard.\n2 stack options.\n1 operator decision.",
})


def _wire(
    tmp_path: Path,
    allowance: int = 1_000_000,
) -> tuple[Orchestrator, StateStore, ApprovalQueue]:
    """Wire an orchestrator starting at DESIGN with the real ArchitectAgent."""
    store = StateStore(tmp_path)
    store.init(
        StateHeader(
            project_id="arch-test",
            tier="Standard",
            current_state=State.DESIGN,
            status=Status.RUNNING,
            owner_agent="Architect",
        ),
        detail={
            "prd": _PRD,
            "_classification": _CLASSIFICATION,
            "resolved_operation": "Add, read, update, and delete tasks via CLI",
        },
    )
    queue = ApprovalQueue(tmp_path)
    log = DecisionLog(tmp_path, "arch-test")
    gov = CostGovernor(CostLedger(tmp_path), allowance=allowance)

    reg = default_registry()
    reg["Architect"] = ArchitectAgent()
    return Orchestrator(tmp_path, store, queue, log, gov, registry=reg), store, queue


# ---------------------------------------------------------------------------
# Test 1 — Valid design package: success, DESIGN.md written, parks at
#           DESIGN_REVIEW with DESIGN_APPROVAL pending
# ---------------------------------------------------------------------------

def test_valid_design_package(tmp_path: Path) -> None:
    orch, store, queue = _wire(tmp_path)

    with patch("control_plane.agents_architect.call_claude", return_value=VALID_REPLY):
        header = orch.run_to_gate()

    assert header.current_state is State.DESIGN_REVIEW
    assert header.status is Status.AWAITING_OPERATOR

    pending = queue.pending()
    assert len(pending) == 1
    assert pending[0].gate == "DESIGN_APPROVAL"

    design_path = tmp_path / "wiki" / "projects" / "arch-test" / "DESIGN.md"
    assert design_path.exists()

    detail = store.read_detail()
    assert "design" in detail
    assert detail["design"]["tier_assessment"]["verdict"] == "agree"


# ---------------------------------------------------------------------------
# Test 2 — Tier challenge: different recommended_tier validates and persists
# ---------------------------------------------------------------------------

def test_tier_challenge_validates_and_persists(tmp_path: Path) -> None:
    orch, store, queue = _wire(tmp_path)

    # Override initial tier so the challenge makes sense.
    store.write_detail({"_classification": {**_CLASSIFICATION, "tier": "Micro"}})

    with patch("control_plane.agents_architect.call_claude", return_value=CHALLENGE_REPLY):
        header = orch.run_to_gate()

    assert header.current_state is State.DESIGN_REVIEW

    detail = store.read_detail()
    ta = detail["design"]["tier_assessment"]
    assert ta["verdict"] == "challenge"
    assert ta["current_tier"] == "Micro"
    assert ta["recommended_tier"] == "Standard"


# ---------------------------------------------------------------------------
# Test 3 — Bad verdict → validation fails → ok=False → FAILED after retries
# ---------------------------------------------------------------------------

def test_bad_verdict_returns_failure(tmp_path: Path) -> None:
    orch, store, queue = _wire(tmp_path)

    bad = json.loads(VALID_REPLY)
    bad["tier_assessment"]["verdict"] = "approve"  # not in {"agree", "challenge"}

    with patch(
        "control_plane.agents_architect.call_claude", return_value=json.dumps(bad)
    ):
        header = orch.run_to_gate()

    assert header.current_state is State.FAILED


# ---------------------------------------------------------------------------
# Test 4 — agree verdict with mismatched tiers → validation fails → FAILED
# ---------------------------------------------------------------------------

def test_agree_tier_mismatch_returns_failure(tmp_path: Path) -> None:
    orch, store, queue = _wire(tmp_path)

    bad = json.loads(VALID_REPLY)
    bad["tier_assessment"]["verdict"] = "agree"
    bad["tier_assessment"]["current_tier"] = "Micro"
    bad["tier_assessment"]["recommended_tier"] = "Standard"  # mismatch!

    with patch(
        "control_plane.agents_architect.call_claude", return_value=json.dumps(bad)
    ):
        header = orch.run_to_gate()

    assert header.current_state is State.FAILED


# ---------------------------------------------------------------------------
# Test 5 — Fewer than 2 stack options → validation fails → FAILED
# ---------------------------------------------------------------------------

def test_too_few_stack_options_returns_failure(tmp_path: Path) -> None:
    orch, store, queue = _wire(tmp_path)

    bad = json.loads(VALID_REPLY)
    bad["tech_stack_options"] = bad["tech_stack_options"][:1]  # only 1 option

    with patch(
        "control_plane.agents_architect.call_claude", return_value=json.dumps(bad)
    ):
        header = orch.run_to_gate()

    assert header.current_state is State.FAILED


# ---------------------------------------------------------------------------
# Test 6 — DESIGN.md content: tier verdict, stack option names, operator
#           decisions must all appear in the rendered file
# ---------------------------------------------------------------------------

def test_design_md_content(tmp_path: Path) -> None:
    orch, store, queue = _wire(tmp_path)

    with patch("control_plane.agents_architect.call_claude", return_value=VALID_REPLY):
        orch.run_to_gate()

    content = (tmp_path / "wiki" / "projects" / "arch-test" / "DESIGN.md").read_text()

    # Tier assessment block
    assert "**Verdict:** agree" in content
    assert "Standard" in content

    # Both stack option names
    assert "Python + SQLite + Click" in content
    assert "Python + SQLite + Typer" in content

    # Operator decision rendered under its own heading
    assert "[OPERATOR DECISION]" in content
    assert "Data retention policy" in content
    assert "Keep indefinitely" in content

    # Summary card
    assert "2 stack options presented" in content
