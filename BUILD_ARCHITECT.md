# Build brief — wire the minimal Architect agent (step 4, part 1)

The prompt and output contract already exist in
`control_plane/prompts/architect.py`. Your job is to wire a real (subprocess)
Claude call around it and slot it into the existing control plane so that:

  PRD_APPROVAL granted -> Architect runs in DESIGN -> produces design package
  -> halts at DESIGN_REVIEW

without changing the control plane's public behavior. All existing tests
(31) must stay green.

This is MINIMAL-FIRST. Do NOT build Mermaid diagrams, the ADR lifecycle, or the
FMEA seed. Prove the round-trip with tier assessment + tech-stack options +
design doc, then we enrich in a later pass.

## Context you must respect (read these before writing)

- Read: control_plane/prompts/architect.py, agents_pm.py (mirror its shape),
  agents.py, orchestrator.py, machine.py, protocol.py, llm.py.
- The Architect is SINGLE-SHOT: it reads the approved PRD (from the detail blob /
  PRD artifact) and emits one structured JSON package. No clarify phase, no
  second pause. If the design needs an operator call, it emits an
  [OPERATOR DECISION] in its output — it does not pause for it in this minimal
  version.
- Billing/auth: use the SAME subprocess call_claude path the PM uses. Do NOT use
  the SDK, do NOT set ANTHROPIC_API_KEY. The PM seat's subprocess-interactive
  decision applies here too for now.
- Canonical agent role names are: PM, Architect, ReviewPanel, Dev, QA, CICD,
  Monitor. Use exactly these. (Note: "Dev", never "Engineer".)

## What to build

1. **`control_plane/agents_architect.py`** — the Architect agent, mirroring the
   structure of agents_pm.py:
   - Reads the approved PRD. Source of truth is the structured PRD object in the
     detail blob (the PM persisted the full object); fall back to the PRD.md path
     if needed. Pass the PRD content as the user message.
   - Calls call_claude(ARCHITECT_SYSTEM, user_msg, ARCHITECT_MODEL,
     ARCHITECT_MAX_TOKENS), parses strict JSON (reuse parse_json — it already
     strips fences).
   - VALIDATES the tier_assessment as a strict structured field, parallel to the
     PM's _validate_resolved_operation / _coerce_classification:
       * verdict in {"agree","challenge"} or raise LLMParseError
       * current_tier, recommended_tier each in {"Micro","Standard","Full"} or raise
       * if verdict == "agree", recommended_tier must equal current_tier or raise
       * tech_stack_options length >= 2 or raise
     A validation failure returns AgentResult(ok=False) so the orchestrator's
     retry/escalation path handles it (do NOT loosen validation to tolerate
     missing/empty fields — strict, like the PM's resolved_operation).
   - Writes a human-readable design artifact to
     wiki/projects/<id>/DESIGN.md (render tier assessment, the tech-stack options,
     the design doc sections, and the operator decisions). Persist the full
     structured object into the detail blob under a "design" key.
   - Returns AgentResult(ok=True, ...) on success so the orchestrator advances
     DESIGN -> DESIGN_REVIEW and raises the DESIGN_APPROVAL gate (this already
     exists in machine.py; do not modify the machine).

2. **Register** the Architect in live_registry() (agents.py) so the live pipeline
   dispatches it in the DESIGN state. Keep default_registry() (stubs) unchanged so
   existing tests are unaffected.

3. **Tests** (`tests/test_architect.py`) with call_claude MOCKED — never hit the
   network:
   - valid design package: agent succeeds, writes DESIGN.md, persists "design" to
     detail, project advances to DESIGN_REVIEW with DESIGN_APPROVAL pending.
   - tier challenge: a mocked reply with verdict "challenge" + different
     recommended_tier validates and persists correctly.
   - strict validation rejects: verdict not in the allowed set -> ok=False; a
     "agree" verdict with mismatched recommended_tier -> ok=False; fewer than 2
     tech_stack_options -> ok=False. Each should route to retry/escalation.
   - DESIGN.md contains the tier verdict, the stack options, and any operator
     decisions (assert on content, so a rendering gap can't hide — same lesson as
     the PM SIPOC/CTQ gap).

4. **Do NOT** modify state.py, machine.py, approvals.py, audit.py, cost.py,
   protocol.py, or the orchestrator's public methods. The Architect should slot
   into the EXISTING DESIGN -> DESIGN_REVIEW transition with no machine changes.
   If you think the machine needs a change, stop and justify it to me first.

## Definition of done

- python -m pytest -q green (existing 31 + new Architect tests).
- A live smoke run: take a project sitting at PRD_APPROVAL (reuse the PM smoke
  flow or extend it), grant PRD_APPROVAL, and confirm the Architect runs, writes
  a real DESIGN.md, and halts at DESIGN_REVIEW. Provide a scripts/smoke_architect.py
  (or extend smoke_pm.py) for this — NOT in pytest. Do NOT run it yourself; I run
  it manually.
- desloppify scan --path control_plane --profile ci strict >= 90.
- No network in the test suite. No debug prints left in committed code.

## Quality bar (non-negotiable)

Type hints everywhere; docstrings on public functions and non-obvious helpers,
not trivial ones; test file alongside the module; conventional commits. Write to
the desloppify dimensions from line one. Mirror agents_pm.py's patterns so the two
agents are structurally consistent — a future reader should see them as siblings.

## Show me before finalizing

- The _validate tier-assessment function (I want to confirm it's strict).
- How the Architect reads the PRD (detail blob vs PRD.md).
- That live_registry dispatches Architect in DESIGN and the existing
  DESIGN_REVIEW gate fires unchanged.
