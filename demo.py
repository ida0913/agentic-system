"""End-to-end demo of the control plane on a trivial project.

Runs a project from INTAKE to DONE using stub agents, pausing at every operator
gate and resuming on a simulated grant. No model calls, no network — this proves
the gate model and the state machine in isolation (§25.2, step 3).

Run:  python demo.py
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from control_plane import (
    ApprovalQueue,
    CostGovernor,
    CostLedger,
    DecisionLog,
    Orchestrator,
    State,
    StateHeader,
    StateStore,
    Status,
)

OPERATOR = "adi"


def main() -> None:
    """Drive one project through the full pipeline, narrating each halt."""
    root = Path(tempfile.mkdtemp(prefix="acp-demo-"))
    project = "stephenville-lead-dashboard"

    store = StateStore(root)
    store.init(StateHeader(project_id=project, tier="Standard", mode="greenfield", complexity="M"))
    queue = ApprovalQueue(root)
    log = DecisionLog(root, project)
    governor = CostGovernor(CostLedger(root), allowance=1_000_000)
    orch = Orchestrator(root, store, queue, log, governor)

    print(f"Project: {project}")
    print(f"Workspace: {root}\n")

    step = 0
    while True:
        header = orch.run_to_gate()
        if header.status is Status.DONE:
            print(f"  [{header.current_state.value}] DONE\n")
            break
        pending = queue.pending()
        if not pending:
            print(f"  [{header.current_state.value}] halted: {header.status.value} "
                  f"(budget={header.budget_status})\n")
            break
        gate = pending[0]
        step += 1
        print(f"  GATE {step}: {gate.gate}  (risk={gate.risk_class})")
        print(f"          {gate.action}")
        print(f"          operator '{OPERATOR}' grants...\n")
        orch.grant(gate.id, OPERATOR)

    print("Final state:", store.read_header().current_state.value)
    print(f"Tokens spent: {CostLedger(root).spent():,}")
    print("\nDecision log:")
    for row in log.entries():
        print("  " + row.strip())

    shutil.rmtree(root)


if __name__ == "__main__":
    main()
