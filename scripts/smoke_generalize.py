#!/usr/bin/env python3
"""Smoke test for the Architect agent against the live claude subprocess.

Run manually from the project root:
    python scripts/smoke_generalize.py

Flow
----
1. Phase 1 — real PM call; raises PM_CLARIFY, parks at AWAITING_OPERATOR.
2. Hardcoded clarify_answers written to detail blob.
3. Phase 2 — orch.grant(pm_clarify.id) resolves PM_CLARIFY, re-runs PM,
   writes PRD.md, raises PRD_APPROVAL.
4. orch.grant(prd_approval.id) advances to DESIGN; Architect runs live,
   writes DESIGN.md, then the ReviewPanel stub raises DESIGN_APPROVAL.
5. Script prints the DESIGN_APPROVAL gate id and a DESIGN.md preview.

DESIGN_APPROVAL is left pending — the operator decides whether to advance.
Workspace is written to smoke_workspaces/worksheet-generator/ and wiped on
each run.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from control_plane.agents import live_registry
from control_plane.approvals import ApprovalQueue
from control_plane.audit import DecisionLog
from control_plane.cost import CostGovernor, CostLedger
from control_plane.machine import Status
from control_plane.orchestrator import Orchestrator
from control_plane.state import StateHeader, StateStore

REQUEST = (
    "Build a worksheet generator that creates practice problem sets for my "
    "tutoring students at different difficulty levels."
)

CLARIFY_ANSWERS = {
    "1": "Python 3.11 on macOS; runs locally, no cloud account to provision.",
    "2": "Subjects are algebra and pre-algebra to start; problems and answer keys "
    "must be printable as a PDF.",
    "3": "Difficulty levels are easy/medium/hard, selected per worksheet; problems "
    "can be templated/randomized rather than pulled from a question bank API.",
    "4": "Used ad hoc before each tutoring session on my laptop; no server, "
    "scheduling, or multi-user access needed.",
    "5": "No login or student accounts — I generate and print worksheets myself; "
    "just needs generated files saved locally with a sensible naming scheme.",
}

PROJECT_ID = "worksheet-generator"
WORKSPACE = Path(__file__).resolve().parent.parent / "smoke_workspaces" / PROJECT_ID


def _print(msg: str = "") -> None:
    print(msg, flush=True)


def main() -> None:
    for subdir in (".agent", "wiki"):
        d = WORKSPACE / subdir
        if d.exists():
            shutil.rmtree(d)
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    store = StateStore(WORKSPACE)
    store.init(
        StateHeader(project_id=PROJECT_ID, tier="Standard"),
        detail={"request": REQUEST},
    )

    queue = ApprovalQueue(WORKSPACE)
    log = DecisionLog(WORKSPACE, PROJECT_ID)
    gov = CostGovernor(CostLedger(WORKSPACE), allowance=10_000_000)
    orch = Orchestrator(WORKSPACE, store, queue, log, gov, registry=live_registry())

    # ------------------------------------------------------------------
    # Phase 1: PM clarify
    # ------------------------------------------------------------------
    _print("=== Phase 1: PM clarify (live claude call) ===")
    header = orch.run_to_gate()

    if header.status is not Status.AWAITING_OPERATOR:
        _print(f"ERROR: expected AWAITING_OPERATOR after Phase 1, got {header.status}")
        sys.exit(1)

    pending = queue.pending()
    if not pending or pending[0].gate != "PM_CLARIFY":
        _print(f"ERROR: expected PM_CLARIFY gate, got {[p.gate for p in pending]}")
        sys.exit(1)

    pm_clarify = pending[0]
    detail = store.read_detail()
    _print(f"Questions ({len(detail.get('questions', []))}):")
    for i, q in enumerate(detail.get("questions", []), 1):
        _print(f"  {i}. {q}")
    _print(f"Provisional: {detail.get('provisional', {})}")

    store.write_detail({"clarify_answers": CLARIFY_ANSWERS})
    _print("\nclarify_answers written.")

    # ------------------------------------------------------------------
    # Phase 2: PRD draft
    # ------------------------------------------------------------------
    _print("\n=== Phase 2: PRD draft (live claude call) ===")
    header = orch.grant(pm_clarify.id, "smoke-operator")

    if header.status is not Status.AWAITING_OPERATOR:
        _print(f"ERROR: expected AWAITING_OPERATOR after Phase 2, got {header.status}")
        sys.exit(1)

    pending = queue.pending()
    if not pending or pending[0].gate != "PRD_APPROVAL":
        _print(f"ERROR: expected PRD_APPROVAL gate, got {[p.gate for p in pending]}")
        sys.exit(1)

    prd_approval = pending[0]
    _print(f"PRD_APPROVAL gate id: {prd_approval.id}")
    prd_path = WORKSPACE / "wiki" / "projects" / PROJECT_ID / "PRD.md"
    if prd_path.exists():
        _print(f"PRD.md written: {prd_path.relative_to(WORKSPACE.parent.parent)}")

    # ------------------------------------------------------------------
    # Architect: grant PRD_APPROVAL -> DESIGN -> DESIGN_REVIEW
    # ------------------------------------------------------------------
    _print("\n=== Architect: DESIGN phase (live claude call) ===")
    header = orch.grant(prd_approval.id, "smoke-operator")
    header = orch.run_to_gate()

    if header.status is not Status.AWAITING_OPERATOR:
        _print(f"ERROR: expected AWAITING_OPERATOR after Architect, got {header.status}")
        sys.exit(1)

    pending = queue.pending()
    if not pending or pending[0].gate != "DESIGN_APPROVAL":
        _print(f"ERROR: expected DESIGN_APPROVAL gate, got {[p.gate for p in pending]}")
        sys.exit(1)

    design_approval = pending[0]
    _print(f"DESIGN_APPROVAL gate id: {design_approval.id}")

    design_path = WORKSPACE / "wiki" / "projects" / PROJECT_ID / "DESIGN.md"
    if design_path.exists():
        rel = design_path.relative_to(Path(__file__).resolve().parent.parent)
        _print(f"DESIGN.md written: {rel}")
        _print("\n--- DESIGN.md preview (first 60 lines) ---")
        lines = design_path.read_text().splitlines()
        for line in lines[:60]:
            _print(line)
        if len(lines) > 60:
            _print(f"... ({len(lines) - 60} more lines)")
    else:
        _print("WARNING: DESIGN.md not found")

    detail = store.read_detail()
    ta = detail.get("design", {}).get("tier_assessment", {})
    _print(f"\nTier verdict : {ta.get('verdict')} ({ta.get('current_tier')} -> {ta.get('recommended_tier')})")
    _print(f"Reason       : {ta.get('reason', '')}")

    _print("\n=== Smoke PASS ===")
    _print(f"To advance past DESIGN_APPROVAL:")
    _print(f"    orch.grant({design_approval.id!r}, 'operator')")


if __name__ == "__main__":
    main()
