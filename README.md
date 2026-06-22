# Agentic Control Plane

The deterministic foundation of the personal agentic AI system — step 1 of the
v4 architecture's implementation order. No model calls live here; this is the
infrastructure that dispatches agents, tracks state, enforces the cost budget,
records decisions, and halts at operator gates.

This package is intentionally small and self-contained so the **gate model can be
proven end-to-end before any real agent or Slack integration exists**. Agents are
stubbed; everything else is real.

## What's implemented

| Component | File | Architecture ref |
|-----------|------|------------------|
| Split state store (header + detail) with compare-and-swap | `state.py` | §4.2, §6 |
| State machine (states, gates, transitions) | `machine.py` | §5, §7.1 |
| Durable approval queue (source of truth; Slack is a view) | `approvals.py` | §6.4 |
| Append-only decision log | `audit.py` | §4.4 |
| Cost governor (session-token model, BUDGET_UNKNOWN fallback) | `cost.py` | §4.3 |
| Orchestrator (dispatch, retry, escalation, idempotent) | `orchestrator.py` | §4.1 |
| Agent protocol + stubs | `agents.py` | §6, §9–20 |

## Design invariants enforced in code

- **Operator sovereignty.** Blocking gates (`PRD_APPROVAL`, `DESIGN_APPROVAL`,
  `PUSH_APPROVAL`, `MERGE_APPROVAL`, `DEPLOY_APPROVAL`) halt the project until an
  authenticated operator grants them. No timeout implies consent.
- **State concurrency safety.** Only the orchestrator writes the header, and every
  write is a versioned compare-and-swap; a stale write is rejected, not applied.
- **Token economy.** State is split into a tiny header every agent reads and a
  heavy detail blob fetched only on demand.
- **Durable audit.** Every agent completion, gate event, retry, escalation, and
  budget halt is appended to an immutable decision log.

## Run it

```bash
pip install pytest
python -m pytest -q        # 18 tests, all green
python demo.py             # drive one project INTAKE -> DONE through 5 gates
```

The demo writes real state files to a temp workspace and narrates each gate as it
halts and resumes, then prints the full decision log.

## What is stubbed (and what replaces it next)

- **Agents** return deterministic results instead of issuing model calls. Replace
  each stub in `agents.default_registry()` with a real implementation that loads
  the agent's system prompt and calls its assigned model (`agent-config.yaml`).
- **The approval surface** is the in-process queue. The next integration layer is
  the Slack bot + local web dashboard that render `ApprovalQueue.pending()` and
  call `grant` / `deny` — the queue stays the source of truth.
- **Token telemetry** is passed to `CostGovernor` as a fixed allowance. Wire it to
  the live session/subscription reading; pass `allowance=None` to exercise the
  `BUDGET_UNKNOWN` path.

## Next steps (architecture §25.2)

1. ✅ Control plane (this package).
2. Slack bot + durable approval queue surface + local web dashboard fallback.
3. Replace the PM stub with the real PM agent; prove `DEFINE -> PRD_APPROVAL`
   against a live model on one trivial project.
4. Architect + Review Panel (start with 3 seats), then Dev + QA, then CI/CD +
   Monitor, then the Prompt Engineer.
