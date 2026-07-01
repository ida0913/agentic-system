"""Cross-agent handoff test: PM -> Architect.

``call_claude`` is mocked for both agents so the test never hits the network.
This drives the real PM agent and the real Architect agent through the
orchestrator (via ``live_registry()``) to prove a property the single-agent
test suites don't cover: a [HANDOFF TO ARCHITECT: ...] marker the PM embeds in
the PRD (a) actually reaches the Architect's prompt unmangled, and (b) is
addressed in the Architect's structured output, not silently dropped.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from control_plane.agents import live_registry
from control_plane.approvals import ApprovalQueue
from control_plane.audit import DecisionLog
from control_plane.cost import CostGovernor, CostLedger
from control_plane.machine import State, Status
from control_plane.orchestrator import Orchestrator
from control_plane.state import StateHeader, StateStore

# The specific handoff the PM leaves for the Architect to pick up.
_MARKER = "[HANDOFF TO ARCHITECT: chart component for rendering the weekly velocity trend]"

PHASE1_REPLY = json.dumps({
    "questions": [
        "Is this for internal use only or will external users access it?",
        "What is the expected data volume per day?",
    ],
    "provisional": {
        "tier": "Standard",
        "mode": "greenfield",
        "physical": False,
        "complexity": "M",
    },
    "reasoning_note": "Determines persistence and integration scope.",
})

PHASE2_REPLY = json.dumps({
    "classification": {
        "tier": "Standard",
        "mode": "greenfield",
        "physical": False,
        "complexity": "M",
    },
    "prd": {
        "overview_goals": "Build a weekly velocity report for the team.",
        "problem_statement": "Velocity trends are tracked manually in spreadsheets.",
        "target_audience": "Internal — single operator (Adi)",
        "success_metrics": ["Report generated in < 5s"],
        "features_requirements": {
            "functional": ["Aggregate weekly task counts"],
            "non_functional": ["Runs as a scheduled job"],
            "usability": ["No manual data entry"],
        },
        "user_journey": (
            "Operator triggers weekly report -> system aggregates task data -> "
            f"{_MARKER} -> operator reviews report"
        ),
        "assumptions_constraints": ["Python 3.11+"],
        "competitive_context": "N/A — internal",
        "out_of_scope": ["Real-time dashboards"],
        "acceptance_criteria": ["Report reflects the prior 7 days of activity"],
    },
    "dmaic_plan": [
        {
            "phase": "Define",
            "deliverables": ["PRD"],
            "owner": "PM",
            "entry": "Operator request received",
            "exit": "PRD approved",
        }
    ],
    "sipoc": {
        "suppliers": ["Operator"],
        "inputs": ["Task data"],
        "process": ["Aggregate", "Render"],
        "outputs": ["Weekly report"],
        "customers": ["Adi"],
    },
    "ctq_tree": [],
    "resolved_operation": "Generate a weekly task-velocity report",
    "gemba_guide": None,
    "summary_card": "Weekly velocity report.\nStandard / greenfield / M.",
})


def _architect_reply_addressing_marker() -> str:
    """A structurally valid Architect reply whose open_questions addresses _MARKER."""
    return json.dumps({
        "tier_assessment": {
            "verdict": "agree",
            "current_tier": "Standard",
            "recommended_tier": "Standard",
            "reason": "Single-service scope with a scheduled aggregation job fits Standard.",
        },
        "tech_stack_options": [
            {
                "name": "Python + APScheduler + matplotlib",
                "pros": ["Simple", "stdlib-adjacent"],
                "cons": ["No web UI"],
                "best_if": "A CLI/cron-driven report is sufficient.",
            },
            {
                "name": "Python + Celery + Plotly",
                "pros": ["Scales to more jobs"],
                "cons": ["Heavier operational surface"],
                "best_if": "More scheduled jobs are planned soon.",
            },
        ],
        "design_doc": {
            "components": ["Scheduler", "Aggregator", "Chart renderer"],
            "data_flow": "Cron -> aggregator -> chart renderer -> report file",
            "key_decisions": ["Chart output format (PNG vs. inline ASCII)"],
            "open_questions": [
                f"{_MARKER} -> resolved: render the weekly velocity trend with "
                "matplotlib to a PNG embedded in the report."
            ],
        },
        "operator_decisions": [],
        "summary_card": "Standard tier confirmed.\n2 stack options presented.\n0 operator decisions raised.",
    })


def _wire(tmp_path: Path) -> tuple[Orchestrator, StateStore, ApprovalQueue]:
    """Wire an orchestrator with the REAL PM and REAL Architect agents."""
    store = StateStore(tmp_path)
    store.init(
        StateHeader(project_id="handoff-test", tier="Standard"),
        detail={"request": "Build a weekly task-velocity report for the team."},
    )
    queue = ApprovalQueue(tmp_path)
    log = DecisionLog(tmp_path, "handoff-test")
    gov = CostGovernor(CostLedger(tmp_path), allowance=1_000_000)

    return Orchestrator(tmp_path, store, queue, log, gov, registry=live_registry()), store, queue


def test_handoff_marker_survives_pm_to_architect(tmp_path: Path) -> None:
    """A [HANDOFF TO ARCHITECT] marker in the PRD must reach the Architect's
    prompt unmangled and be addressed in its structured design output."""
    orch, store, queue = _wire(tmp_path)

    # --- PM Phase 1: clarify -----------------------------------------------
    with patch("control_plane.agents_pm.call_claude", return_value=PHASE1_REPLY):
        header = orch.run_to_gate()
    assert header.current_state is State.DEFINE
    pm_clarify = queue.pending()[0]
    assert pm_clarify.gate == "PM_CLARIFY"

    # --- PM Phase 2: draft PRD containing the handoff marker ---------------
    store.write_detail({"clarify_answers": {"1": "Internal only.", "2": "Low volume."}})
    with patch("control_plane.agents_pm.call_claude", return_value=PHASE2_REPLY):
        orch.grant(pm_clarify.id, "adi")
        header = orch.run_to_gate()
    assert header.current_state is State.DEFINE
    prd_approval = queue.pending()[0]
    assert prd_approval.gate == "PRD_APPROVAL"

    # Sanity check: the marker actually landed in the persisted PRD.
    detail = store.read_detail()
    assert _MARKER in detail["prd"]["user_journey"]

    # --- Grant PRD_APPROVAL: real Architect runs on the approved PRD -------
    architect_mock = patch(
        "control_plane.agents_architect.call_claude",
        return_value=_architect_reply_addressing_marker(),
    )
    with architect_mock as mocked_call:
        orch.grant(prd_approval.id, "adi")
        header = orch.run_to_gate()

    assert header.current_state is State.DESIGN_REVIEW
    assert header.status is Status.AWAITING_OPERATOR

    # (a) The marker reached the Architect's prompt unmangled — the handoff
    #     wasn't dropped or summarized away before the Architect ever saw it.
    architect_user_msg = mocked_call.call_args[0][1]
    assert _MARKER in architect_user_msg

    # (b) The Architect's structured output addresses the marker — it isn't
    #     silently dropped from the design package the operator reviews.
    detail = store.read_detail()
    design_doc = detail["design"]["design_doc"]
    addressed = design_doc["open_questions"] + design_doc["key_decisions"]
    assert any(_MARKER in item for item in addressed), (
        "Architect design output does not reference the PM's handoff marker; "
        f"open_questions/key_decisions were: {addressed!r}"
    )

    # (c) The rendered DESIGN.md — what the operator actually reads — also
    #     surfaces the marker, not just the in-memory detail blob.
    design_path = tmp_path / "wiki" / "projects" / "handoff-test" / "DESIGN.md"
    assert _MARKER in design_path.read_text()
