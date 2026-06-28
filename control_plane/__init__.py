"""Control plane for the personal agentic AI system.

Deterministic infrastructure — no model calls live here. The package provides
the split state store, the project state machine, the durable approval queue,
the append-only decision log, the session-token cost governor, and the
orchestrator that ties them together (architecture document v4, §4–6).
"""

# Intended public API — single import surface for all control-plane consumers.
from .approvals import Approval, ApprovalQueue, ApprovalStatus
from .audit import DecisionLog
from .cost import BudgetStatus, CostGovernor, CostLedger
from .machine import FIX_CYCLE_CAP, State, Status
from .orchestrator import Orchestrator
from .protocol import Agent, AgentResult
from .state import StateConflict, StateHeader, StateStore

__all__ = [
    "Agent",
    "AgentResult",
    "Approval",
    "ApprovalQueue",
    "ApprovalStatus",
    "BudgetStatus",
    "CostGovernor",
    "CostLedger",
    "DecisionLog",
    "FIX_CYCLE_CAP",
    "Orchestrator",
    "State",
    "StateConflict",
    "StateHeader",
    "StateStore",
    "Status",
]
