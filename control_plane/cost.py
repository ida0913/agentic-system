"""The cost governor (§4.3, §4.4 fallback).

Spend is tracked against a session/subscription token allowance, not a dollar
figure. The governor wraps every agent call: it checks remaining allowance
before, and records actual usage after.

Three regimes:
  * OK / WARN — allowance is readable and not exhausted; work proceeds (with a
    warning past the warn threshold).
  * HALTED — allowance is exhausted; no agent runs until refresh and operator
    approval. Pay-as-you-go credits are never spent without explicit opt-in.
  * UNKNOWN — allowance cannot be read reliably; only non-mutating / Micro work
    proceeds unless the operator grants a one-run override.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class BudgetStatus(str, Enum):
    """The governor's current regime."""

    OK = "OK"
    WARN = "WARN"
    HALTED = "HALTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class BudgetDecision:
    """The governor's ruling on whether a call may proceed."""

    allowed: bool
    status: BudgetStatus
    reason: str


class CostLedger:
    """File-backed running tally of token spend for one project."""

    def __init__(self, root: Path) -> None:
        self._path = Path(root) / ".agent" / "cost-ledger.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            _tmp = self._path.with_suffix(".tmp")
            _tmp.write_text(json.dumps({"spent_tokens": 0, "by_agent": {}}, indent=2))
            _tmp.replace(self._path)

    def spent(self) -> int:
        """Total tokens spent so far on this project."""
        return int(self._load()["spent_tokens"])

    def record(self, agent: str, tokens: int) -> int:
        """Add ``tokens`` spent by ``agent`` to the ledger; return new total."""
        data = self._load()
        data["spent_tokens"] = int(data["spent_tokens"]) + tokens
        data["by_agent"][agent] = int(data["by_agent"].get(agent, 0)) + tokens
        _tmp = self._path.with_suffix(".tmp")
        _tmp.write_text(json.dumps(data, indent=2))
        _tmp.replace(self._path)
        return data["spent_tokens"]

    def _load(self) -> dict:
        return json.loads(self._path.read_text())


class CostGovernor:
    """Gatekeeper for agent calls against a session-token allowance.

    Args:
        ledger: The project's cost ledger.
        allowance: Remaining session tokens, or ``None`` if telemetry is
            unreadable (which puts the governor in the UNKNOWN regime).
        warn_fraction: Fraction of allowance at which to start warning.
        override: Operator one-run override permitting work under UNKNOWN.
    """

    def __init__(
        self,
        ledger: CostLedger,
        allowance: Optional[int],
        warn_fraction: float = 0.8,
        override: bool = False,
    ) -> None:
        self._ledger = ledger
        self._allowance = allowance
        self._warn = warn_fraction
        self._override = override

    def check(self, mutating: bool) -> BudgetDecision:
        """Rule on whether the next call may proceed.

        Args:
            mutating: Whether the call would mutate state or produce side effects.
                Under the UNKNOWN regime, only non-mutating calls proceed without
                an operator override.
        """
        if self._allowance is None:
            if self._override or not mutating:
                return BudgetDecision(True, BudgetStatus.UNKNOWN, "telemetry unreadable; permitted")
            return BudgetDecision(
                False, BudgetStatus.UNKNOWN, "telemetry unreadable; mutating work needs override"
            )
        spent = self._ledger.spent()
        if spent >= self._allowance:
            return BudgetDecision(False, BudgetStatus.HALTED, "session allowance exhausted")
        if spent >= self._warn * self._allowance:
            return BudgetDecision(True, BudgetStatus.WARN, "approaching session allowance")
        return BudgetDecision(True, BudgetStatus.OK, "within allowance")
