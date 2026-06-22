# Build brief — wire the real PM agent (step 2)

This is the spec for Claude Code. The prompt and output contract already exist in
`control_plane/prompts/pm.py`. Your job is to wire a real Claude (Sonnet) call
around it and slot it into the existing control plane **without changing the
control plane's public behavior**. All 18 existing tests must still pass.

## Context you must respect

- The control plane is built and tested. Do not modify `state.py`, `machine.py`,
  `approvals.py`, `audit.py`, `cost.py`, or the orchestrator's public methods.
- Agents are stateless callables matching the `Agent` protocol in `agents.py`:
  `(header, fetch_detail, workspace) -> AgentResult`.
- Clarification uses **Option A** (stretched approval): the PM raises its
  questions as an approval-style pause via the existing approval queue, the
  project parks `AWAITING_OPERATOR`, and the operator's answers come back through
  the same resume path. Do NOT add a new state.
- Billing: authenticate through Claude **subscription credentials**, NOT an
  `ANTHROPIC_API_KEY` env var (a key flips you onto metered pay-as-you-go). Leave
  usage credits disabled so exhaustion halts rather than spends.

## What to build

1. **`control_plane/agents_pm.py`** — the real PM agent, two phases:
   - **Phase 1 (clarify):** on first run in DEFINE, call Sonnet with
     `PM_PHASE1_SYSTEM` and the operator's raw request (read from
     `state.detail.json` under `request`). Parse the strict-JSON reply. Write the
     `provisional` classification and the questions into the detail blob. Raise a
     clarification pause (reuse `ApprovalQueue`, gate name `PM_CLARIFY`) carrying
     the questions, and return an `AgentResult` that parks the project.
   - **Phase 2 (draft):** after the operator answers (answers land in the detail
     blob under `clarify_answers`), call Sonnet with `PM_PHASE2_SYSTEM` plus the
     request, questions, and answers. Parse the strict-JSON reply. Write the PRD
     to `wiki/projects/<id>/PRD.md` (render the JSON into readable markdown),
     persist the full structured object into the detail blob, set the header's
     `tier`/`mode`/`complexity` from `classification`, and return success so the
     orchestrator raises the existing `PRD_APPROVAL` gate.
   - Phase detection: if `clarify_answers` is absent in detail -> phase 1; if
     present and no PRD yet -> phase 2.

2. **A thin model-call wrapper** (`control_plane/llm.py`) so the SDK is isolated
   in one place and mockable in tests. One function:
   `call_claude(system: str, user: str, model: str, max_tokens: int) -> str`
   returning the raw text. Use the Claude Agent SDK / Messages API. Keep the
   system prompt as a stable cacheable prefix (do not rebuild it per call).

3. **Strict-JSON parsing** that tolerates the model wrapping output in stray
   whitespace but rejects anything genuinely non-JSON — raise a clear error the
   orchestrator's retry path can catch (the orchestrator already retries twice
   then escalates).

4. **Tests** (`tests/test_pm.py`) with `call_claude` MOCKED — never hit the
   network in tests:
   - phase 1 produces 3-5 questions and parks the project at `PM_CLARIFY`
   - supplying answers and stepping produces a PRD file and parks at
     `PRD_APPROVAL`
   - a malformed (non-JSON) model reply triggers the orchestrator's retry, then
     escalation to FAILED on repeated failure
   - granting `PRD_APPROVAL` advances to DESIGN

5. **Register** the real PM in `default_registry()` behind a flag or by direct
   swap, so the demo can run live while tests use the stub/mock.

## Definition of done

- `python -m pytest -q` is green (existing 18 + your new PM tests).
- A live run (`python demo.py` adapted, or a small script) against your Sonnet
  credentials produces real clarifying questions, accepts typed answers, and
  writes a real PRD.md, halting at `PRD_APPROVAL`.
- `desloppify scan --path control_plane --profile ci` strict score >= 90.
- No network calls in the test suite.

## Quality bar (non-negotiable, from the architecture)

Type hints on every function; docstrings on public functions and non-obvious
helpers (not on trivial ones); a test file alongside the new module; conventional
commits. Write to the desloppify dimensions from the first line — clean naming,
right-sized abstractions, consistent error handling.
