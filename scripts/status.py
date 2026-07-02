#!/usr/bin/env python3
"""Read-only pipeline status view for one project workspace.

Usage:
    python scripts/status.py <workspace_path>

Reads .agent/state.header.json, .agent/cost-ledger.json,
.agent/approvals.json, and wiki/projects/<id>/decisions.md directly off disk
(plain json.loads / Path.read_text) rather than through the control-plane
classes, since their constructors create missing files/dirs as a side effect.
This script never writes anything.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional


def _load_json(path: Path) -> Optional[dict]:
    """Best-effort JSON load; returns None on malformed content."""
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _print_field(label: str, value: Any) -> None:
    print(f"  {label:<14} {value}")


def _describe_open_gates(open_gates: list[str], approvals: Optional[list[dict]]) -> str:
    if not open_gates:
        return "none"
    by_id = {a.get("id"): a for a in (approvals or [])}
    parts = []
    for gid in open_gates:
        approval = by_id.get(gid)
        if approval:
            parts.append(f"{approval.get('gate')} ({gid})")
        else:
            parts.append(gid)
    return ", ".join(parts)


def _last_decisions(decisions_path: Path, count: int) -> list[str]:
    if not decisions_path.exists():
        return []
    lines = decisions_path.read_text().splitlines()
    rows = [ln for ln in lines if ln.startswith("| ") and "Timestamp" not in ln and "---" not in ln]
    return rows[-count:]


def _format_decision_row(row: str) -> str:
    cols = [c.strip() for c in row.strip().strip("|").split("|")]
    if len(cols) != 4:
        return f"  {row}"
    ts, event, detail, actor = cols
    return f"  [{ts}] {event:<16} {detail}  ({actor})"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: status.py <workspace_path>", file=sys.stderr)
        return 2

    workspace = Path(argv[1])
    if not workspace.exists():
        print(f"error: workspace not found: {workspace}", file=sys.stderr)
        return 1

    header_path = workspace / ".agent" / "state.header.json"
    if not header_path.exists():
        print(
            f"error: no state found at {header_path} (not an agent workspace?)",
            file=sys.stderr,
        )
        return 1

    header = _load_json(header_path)
    if header is None:
        print(f"error: malformed state header at {header_path}", file=sys.stderr)
        return 1

    project_id = header.get("project_id", "?")

    ledger_path = workspace / ".agent" / "cost-ledger.json"
    ledger = _load_json(ledger_path) if ledger_path.exists() else None
    spent = ledger.get("spent_tokens") if ledger else None

    approvals_path = workspace / ".agent" / "approvals.json"
    approvals = None
    if approvals_path.exists():
        raw = _load_json(approvals_path)
        if isinstance(raw, list):
            approvals = raw

    decisions_path = workspace / "wiki" / "projects" / project_id / "decisions.md"
    last_rows = _last_decisions(decisions_path, 5)

    print(f"Project workspace: {workspace}")
    print()
    _print_field("Project", project_id)
    _print_field("Tier", header.get("tier"))
    _print_field("Mode", header.get("mode"))
    _print_field("Complexity", header.get("complexity"))
    _print_field("State", header.get("current_state"))
    _print_field("Status", header.get("status"))
    _print_field("Budget", header.get("budget_status"))
    _print_field("Pending gate", _describe_open_gates(header.get("open_gates") or [], approvals))
    _print_field("Token spend", spent if spent is not None else "unknown (no cost ledger)")

    print()
    print("Last decisions:")
    if last_rows:
        for row in last_rows:
            print(_format_decision_row(row))
    else:
        print("  (no decision log yet)")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
