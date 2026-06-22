"""The project state machine.

Defines every state a project can occupy, the agent that owns each state, the
transition that follows it, and whether a blocking operator gate sits between a
state and its successor. This module is pure data and pure functions: it holds
no mutable state and performs no I/O, so it can be reasoned about and tested in
isolation. The orchestrator (see ``orchestrator.py``) is the only component that
acts on these definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class State(str, Enum):
    """The node a project currently occupies in the pipeline."""

    INTAKE = "INTAKE"
    DEFINE = "DEFINE"
    TIER_CHECK = "TIER_CHECK"
    DESIGN = "DESIGN"
    DESIGN_REVIEW = "DESIGN_REVIEW"
    BUILD = "BUILD"
    QA = "QA"
    FIX = "FIX"
    PR_REVIEW = "PR_REVIEW"
    DEPLOY = "DEPLOY"
    CONTROL = "CONTROL"
    HALTED_BUDGET = "HALTED_BUDGET"
    BUDGET_UNKNOWN = "BUDGET_UNKNOWN"
    FAILED = "FAILED"
    DONE = "DONE"


class Status(str, Enum):
    """The disposition of a project within its current state."""

    RUNNING = "RUNNING"
    AWAITING_OPERATOR = "AWAITING_OPERATOR"
    FAILED = "FAILED"
    DONE = "DONE"


@dataclass(frozen=True)
class StateSpec:
    """Static description of a single state.

    Attributes:
        owner: The agent role responsible for doing the work of this state.
        nxt: The state to advance to once this state's work (and any gate) is
            complete. ``None`` marks a terminal state.
        gate: The name of the blocking operator gate that must be granted before
            advancing to ``nxt``. ``None`` means the transition is automatic and
            the operator is merely notified.
    """

    owner: str
    nxt: Optional[State]
    gate: Optional[str] = None


# The canonical happy-path pipeline. Conditional states (TIER_CHECK challenge,
# the FIX loop, the Full-tier PR_REVIEW) are represented here and selected by the
# orchestrator according to project tier and runtime conditions.
MACHINE: dict[State, StateSpec] = {
    State.INTAKE: StateSpec(owner="-", nxt=State.DEFINE),
    State.DEFINE: StateSpec(owner="PM", nxt=State.DESIGN, gate="PRD_APPROVAL"),
    State.TIER_CHECK: StateSpec(owner="Architect", nxt=State.DESIGN, gate="TIER_RECLASSIFY"),
    State.DESIGN: StateSpec(owner="Architect", nxt=State.DESIGN_REVIEW),
    State.DESIGN_REVIEW: StateSpec(owner="ReviewPanel", nxt=State.BUILD, gate="DESIGN_APPROVAL"),
    State.BUILD: StateSpec(owner="Dev", nxt=State.QA, gate="PUSH_APPROVAL"),
    State.QA: StateSpec(owner="QA", nxt=State.PR_REVIEW),
    State.FIX: StateSpec(owner="Dev", nxt=State.QA),
    State.PR_REVIEW: StateSpec(owner="ReviewPanel", nxt=State.DEPLOY, gate="MERGE_APPROVAL"),
    State.DEPLOY: StateSpec(owner="CICD", nxt=State.CONTROL, gate="DEPLOY_APPROVAL"),
    State.CONTROL: StateSpec(owner="Monitor", nxt=State.DONE),
    State.DONE: StateSpec(owner="-", nxt=None),
    State.FAILED: StateSpec(owner="Orchestrator", nxt=None),
    State.HALTED_BUDGET: StateSpec(owner="Governor", nxt=None),
    State.BUDGET_UNKNOWN: StateSpec(owner="Governor", nxt=None),
}

# Fix-cycle cap: after this many Dev<->QA round trips on the same defect cluster,
# the loop is broken and the project escalates to the operator (see §16.2).
FIX_CYCLE_CAP = 3


def spec(state: State) -> StateSpec:
    """Return the :class:`StateSpec` for ``state``."""
    return MACHINE[state]


def has_gate(state: State) -> bool:
    """Whether a blocking operator gate guards the exit from ``state``."""
    return MACHINE[state].gate is not None


def is_terminal(state: State) -> bool:
    """Whether ``state`` has no successor."""
    return MACHINE[state].nxt is None
