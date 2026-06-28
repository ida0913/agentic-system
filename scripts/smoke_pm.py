#!/usr/bin/env python3
"""Smoke test for the two-phase PM agent against the live claude subprocess.

Run manually from the project root:
    python scripts/smoke_pm.py

Flow
----
1. Phase 1 — real claude call; PM raises PM_CLARIFY and parks the project.
2. Hardcoded clarify_answers are written to the detail blob.
3. Phase 2 — orch.grant(pm_clarify.id, "smoke-operator") is the single call that
   resolves PM_CLARIFY, re-runs the PM agent (Phase 2), writes PRD.md, and raises
   the PRD_APPROVAL gate.  No extra run_to_gate() is needed between the two phases.
4. Script prints the PRD_APPROVAL gate id and a PRD preview, then exits.

PRD_APPROVAL is left pending — the operator decides whether to advance.

Workspace is written to smoke_workspaces/craigslist-repost/ so the full output
(header, detail, approvals, PRD) is inspectable after the run.  A second run
wipes and re-initialises that directory for idempotency.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Importable when run from the project root or from the scripts/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from control_plane.agents import default_registry
from control_plane.agents_pm import PMAgent
from control_plane.approvals import ApprovalQueue
from control_plane.audit import DecisionLog
from control_plane.cost import CostGovernor, CostLedger
from control_plane.llm import DETAIL_KEY_CLASSIFICATION
from control_plane.machine import Status
from control_plane.orchestrator import Orchestrator
from control_plane.state import StateHeader, StateStore

REQUEST = "Automate reposting my tutoring listing to Craigslist every 48 hours."

# Hardcoded answers keyed by question number string ("1", "2", ...).
# _build_phase2_user() tries str(i+1) first, so these wire up regardless of
# what questions the model happens to ask in Phase 1.
CLARIFY_ANSWERS = {
    "1": "Python 3.11 on macOS; Playwright is already installed.",
    "2": "The listing body, title, and images stay identical — only the post timestamp needs refreshing.",
    "3": "Browser automation (Playwright) is fine; no Craigslist API exists.",
    "4": "Runs on my personal laptop via a cron job; no server or cloud deployment needed.",
    "5": "Log each attempt (success/failure) to a local file; a terminal notification on failure is a nice-to-have.",
}

PROJECT_ID = "craigslist-repost-smoke"
WORKSPACE = Path(__file__).resolve().parent.parent / "smoke_workspaces" / PROJECT_ID


def _print(msg: str = "") -> None:
    print(msg, flush=True)


def main() -> None:
    # Wipe previous run so the script is idempotent.
    agent_dir = WORKSPACE / ".agent"
    if agent_dir.exists():
        shutil.rmtree(agent_dir)
    wiki_dir = WORKSPACE / "wiki"
    if wiki_dir.exists():
        shutil.rmtree(wiki_dir)
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    store = StateStore(WORKSPACE)
    store.init(
        StateHeader(project_id=PROJECT_ID, tier="Standard"),
        detail={"request": REQUEST},
    )

    queue = ApprovalQueue(WORKSPACE)
    log = DecisionLog(WORKSPACE, PROJECT_ID)
    # Generous allowance: smoke run is two real model calls, each well under 2 k tokens.
    gov = CostGovernor(CostLedger(WORKSPACE), allowance=5_000_000)

    reg = default_registry()
    reg["PM"] = PMAgent()
    orch = Orchestrator(WORKSPACE, store, queue, log, gov, registry=reg)

    # ------------------------------------------------------------------
    # Phase 1
    # ------------------------------------------------------------------
    _print("=== Phase 1: PM clarify (live claude call) ===")
    header = orch.run_to_gate()

    if header.status is not Status.AWAITING_OPERATOR:
        _print(f"ERROR: expected AWAITING_OPERATOR after Phase 1, got {header.status}", )
        sys.exit(1)

    pending = queue.pending()
    if not pending or pending[0].gate != "PM_CLARIFY":
        gates = [p.gate for p in pending]
        _print(f"ERROR: expected PM_CLARIFY gate, got {gates}")
        sys.exit(1)

    pm_clarify = pending[0]
    detail = store.read_detail()
    questions = detail.get("questions", [])

    _print(f"Clarifying questions ({len(questions)}):")
    for i, q in enumerate(questions, 1):
        _print(f"  {i}. {q}")
    _print(f"Provisional: {detail.get('provisional', {})}")
    _print(f"Reasoning:   {detail.get('reasoning_note', '(none)')}")

    # Write clarify_answers so Phase 2 picks them up.
    store.write_detail({"clarify_answers": CLARIFY_ANSWERS})
    _print()
    _print("clarify_answers written to detail blob.")

    # ------------------------------------------------------------------
    # Phase 2 — single grant() call: resolves PM_CLARIFY, re-runs PM,
    # drafts PRD, raises PRD_APPROVAL.  No run_to_gate() in between.
    # ------------------------------------------------------------------
    _print()
    _print("=== Phase 2: PRD draft (via orch.grant — live claude call) ===")
    header = orch.grant(pm_clarify.id, "smoke-operator")

    if header.status is not Status.AWAITING_OPERATOR:
        _print(f"ERROR: expected AWAITING_OPERATOR after Phase 2, got {header.status}")
        sys.exit(1)

    prd_pending = queue.pending()
    if not prd_pending or prd_pending[0].gate != "PRD_APPROVAL":
        gates = [p.gate for p in prd_pending]
        _print(f"ERROR: expected PRD_APPROVAL gate, got {gates}")
        sys.exit(1)

    prd_gate = prd_pending[0]
    detail = store.read_detail()
    cls = detail.get(DETAIL_KEY_CLASSIFICATION, {})

    _print(f"PRD_APPROVAL gate id : {prd_gate.id}")
    _print(f"Classification       : tier={cls.get('tier')}  mode={cls.get('mode')}  "
           f"complexity={cls.get('complexity')}  physical={cls.get('physical')}")

    prd_path = WORKSPACE / "wiki" / "projects" / PROJECT_ID / "PRD.md"
    if prd_path.exists():
        rel = prd_path.relative_to(Path(__file__).resolve().parent.parent)
        _print(f"PRD written to       : {rel}")
        _print()
        _print("--- PRD preview (first 40 lines) ---")
        lines = prd_path.read_text().splitlines()
        for line in lines[:40]:
            _print(line)
        if len(lines) > 40:
            _print(f"... ({len(lines) - 40} more lines — open the file to read in full)")
    else:
        _print("WARNING: PRD.md not found (Phase 2 may have failed silently)")

    _print()
    _print("=== Smoke PASS ===")
    _print(f"To advance past PRD_APPROVAL:")
    _print(f"    orch.grant({prd_gate.id!r}, 'operator')")


if __name__ == "__main__":
    main()
