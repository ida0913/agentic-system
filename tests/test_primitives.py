"""Unit tests for the control-plane primitives."""

from __future__ import annotations

import pytest

from control_plane.approvals import ApprovalQueue, ApprovalStatus
from control_plane.cost import BudgetStatus, CostGovernor, CostLedger
from control_plane.state import StateConflict, StateHeader, State, Status, StateStore


def test_state_init_and_read(tmp_path):
    store = StateStore(tmp_path)
    store.init(StateHeader(project_id="demo"))
    header = store.read_header()
    assert header.project_id == "demo"
    assert header.version == 1
    assert header.current_state is State.INTAKE


def test_cannot_init_twice(tmp_path):
    store = StateStore(tmp_path)
    store.init(StateHeader(project_id="demo"))
    with pytest.raises(StateConflict):
        store.init(StateHeader(project_id="demo"))


def test_compare_and_swap_increments_version(tmp_path):
    store = StateStore(tmp_path)
    store.init(StateHeader(project_id="demo"))
    header = store.read_header()
    header.status = Status.AWAITING_OPERATOR
    saved = store.write_header(header.version, header)
    assert saved.version == 2
    assert store.read_header().status is Status.AWAITING_OPERATOR


def test_compare_and_swap_rejects_stale_write(tmp_path):
    store = StateStore(tmp_path)
    store.init(StateHeader(project_id="demo"))
    stale = store.read_header()  # version 1
    # A concurrent writer advances the version first.
    other = store.read_header()
    store.write_header(other.version, other)  # now version 2
    with pytest.raises(StateConflict):
        store.write_header(stale.version, stale)  # stale view -> rejected


def test_detail_merge(tmp_path):
    store = StateStore(tmp_path)
    store.init(StateHeader(project_id="demo"), detail={"a": 1})
    store.write_detail({"b": 2})
    assert store.read_detail() == {"a": 1, "b": 2}


def test_approval_grant_is_idempotent(tmp_path):
    queue = ApprovalQueue(tmp_path)
    appr = queue.request("PRD_APPROVAL", "demo", "advance", "low", "PM")
    first = queue.grant(appr.id, "adi")
    second = queue.grant(appr.id, "someone_else")
    assert first.status is ApprovalStatus.GRANTED
    assert second.decided_by == "adi"  # unchanged on second grant


def test_approval_requires_identity(tmp_path):
    queue = ApprovalQueue(tmp_path)
    appr = queue.request("PRD_APPROVAL", "demo", "advance", "low", "PM")
    with pytest.raises(PermissionError):
        queue.grant(appr.id, "")


def test_pending_excludes_decided(tmp_path):
    queue = ApprovalQueue(tmp_path)
    a = queue.request("G1", "demo", "x", "low", "PM")
    queue.request("G2", "demo", "y", "low", "PM")
    queue.grant(a.id, "adi")
    assert len(queue.pending()) == 1


def test_governor_ok_warn_halt(tmp_path):
    ledger = CostLedger(tmp_path)
    gov = CostGovernor(ledger, allowance=1000, warn_fraction=0.8)
    assert gov.check(mutating=True).status is BudgetStatus.OK
    ledger.record("Dev", 850)
    assert gov.check(mutating=True).status is BudgetStatus.WARN
    ledger.record("Dev", 200)
    halted = gov.check(mutating=True)
    assert halted.status is BudgetStatus.HALTED and not halted.allowed


def test_governor_unknown_blocks_mutating_without_override(tmp_path):
    ledger = CostLedger(tmp_path)
    gov = CostGovernor(ledger, allowance=None)
    assert not gov.check(mutating=True).allowed
    assert gov.check(mutating=False).allowed  # non-mutating permitted


def test_governor_unknown_allows_with_override(tmp_path):
    ledger = CostLedger(tmp_path)
    gov = CostGovernor(ledger, allowance=None, override=True)
    assert gov.check(mutating=True).allowed
