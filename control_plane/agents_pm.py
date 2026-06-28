"""The real PM agent — two-phase PRD generation with operator clarification.

Phase 1 (clarify): called when ``clarify_answers`` is absent from the detail
blob. Sends the operator's raw request to Sonnet, parses the JSON reply, raises
a ``PM_CLARIFY`` approval so the project parks at AWAITING_OPERATOR, and returns
the approval id in ``detail_patch`` so the orchestrator can use it as the open
gate (Option A stretched-approval pattern).

Phase 2 (draft): called when ``clarify_answers`` is present but no ``prd`` key
exists yet. Sends the full context — request, questions, answers — to Sonnet,
parses the JSON reply, renders the PRD to ``wiki/projects/<id>/PRD.md``, and
returns success so the orchestrator raises the normal ``PRD_APPROVAL`` gate.

Both phases catch ``LLMError`` and ``LLMParseError`` and return
``AgentResult(ok=False)`` so the orchestrator's built-in retry/escalation path
handles transient failures without leaking exceptions.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Callable

from .protocol import AgentResult
from .approvals import ApprovalQueue
from .llm import DETAIL_KEY_CLARIFY_GATE, DETAIL_KEY_CLASSIFICATION, LLMError, LLMParseError, call_claude, parse_json
from .prompts.pm import PM_MAX_TOKENS, PM_MODEL, PM_PHASE1_SYSTEM, PM_PHASE2_SYSTEM
from .state import StateHeader


class PMAgent:
    """Two-phase PM agent that produces clarifying questions then a full PRD."""

    def __call__(
        self,
        header: StateHeader,
        fetch_detail: Callable[[], dict[str, Any]],
        workspace: Path,
    ) -> AgentResult:
        """Run the appropriate phase based on what the detail blob contains.

        Phase detection:
        - No ``clarify_answers`` key → Phase 1 (clarify).
        - ``clarify_answers`` present, no ``prd`` key → Phase 2 (draft).
        - Both present → PRD already written; return success immediately.
        """
        detail = fetch_detail()
        try:
            if "clarify_answers" not in detail:
                return self._phase1(header, detail, workspace)
            if "prd" not in detail:
                return self._phase2(header, detail, workspace)
        except (LLMError, LLMParseError) as exc:
            return AgentResult(ok=False, summary=f"PM error: {exc}")

        return AgentResult(ok=True, tokens=0, summary="PM: PRD already present (no-op)")

    # ------------------------------------------------------------------
    # Private — Phase 1
    # ------------------------------------------------------------------

    def _phase1(
        self, header: StateHeader, detail: dict[str, Any], workspace: Path
    ) -> AgentResult:
        """Ask clarifying questions; raise PM_CLARIFY to park the project."""
        request = detail.get("request", "")
        raw = call_claude(PM_PHASE1_SYSTEM, request, PM_MODEL, PM_MAX_TOKENS)
        parsed = parse_json(raw)
        _validate_phase1(parsed)

        queue = ApprovalQueue(workspace)
        approval = queue.request(
            gate="PM_CLARIFY",
            project_id=header.project_id,
            action=(
                "Operator must answer clarifying questions before the PRD "
                "can be drafted. See 'questions' in the project detail blob."
            ),
            risk_class="low",
            requested_by="PM",
        )

        return AgentResult(
            ok=True,
            tokens=PM_MAX_TOKENS // 4,  # conservative estimate; no token count from CLI
            detail_patch={
                "questions": parsed["questions"],
                "provisional": parsed["provisional"],
                "reasoning_note": parsed.get("reasoning_note", ""),
                # Signals the orchestrator to park on PM_CLARIFY instead of PRD_APPROVAL.
                DETAIL_KEY_CLARIFY_GATE: approval.id,
            },
            summary=(
                f"PM Phase 1: {len(parsed['questions'])} clarifying question(s) raised "
                f"(provisional tier={parsed['provisional']['tier']}, "
                f"complexity={parsed['provisional']['complexity']})"
            ),
        )

    # ------------------------------------------------------------------
    # Private — Phase 2
    # ------------------------------------------------------------------

    def _phase2(
        self, header: StateHeader, detail: dict[str, Any], workspace: Path
    ) -> AgentResult:
        """Draft the PRD from answers; write PRD.md; signal PRD_APPROVAL."""
        request = detail.get("request", "")
        questions = detail.get("questions", [])
        answers = detail.get("clarify_answers", {})

        user_msg = _build_phase2_user(request, questions, answers)
        raw = call_claude(PM_PHASE2_SYSTEM, user_msg, PM_MODEL, PM_MAX_TOKENS)
        parsed = parse_json(raw)
        _validate_phase2(parsed)
        parsed["classification"] = _coerce_classification(parsed["classification"])

        prd_path = _write_prd(parsed, header, workspace)

        cls = parsed["classification"]
        return AgentResult(
            ok=True,
            tokens=PM_MAX_TOKENS // 2,  # conservative estimate
            detail_patch={
                "prd": parsed["prd"],
                "dmaic_plan": parsed.get("dmaic_plan", []),
                "sipoc": parsed.get("sipoc", {}),
                "ctq_tree": parsed.get("ctq_tree", []),
                "gemba_guide": parsed.get("gemba_guide"),
                "summary_card": parsed.get("summary_card", ""),
                "links": {"prd": str(prd_path.relative_to(workspace))},
                # Signals the orchestrator to patch header tier/mode/complexity.
                DETAIL_KEY_CLASSIFICATION: cls,
            },
            summary=(
                f"PM Phase 2: PRD drafted — tier={cls['tier']}, "
                f"mode={cls['mode']}, complexity={cls['complexity']}"
            ),
            artifacts=[str(prd_path.relative_to(workspace))],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_phase1(parsed: dict) -> None:
    """Raise LLMParseError if the Phase 1 reply is missing required keys."""
    for key in ("questions", "provisional"):
        if key not in parsed:
            raise LLMParseError(f"Phase 1 reply missing required key: {key!r}")
    if not isinstance(parsed["questions"], list) or not parsed["questions"]:
        raise LLMParseError("Phase 1 'questions' must be a non-empty list")


_TIER_COERCE: dict[str, str] = {
    "1": "Micro", "micro": "Micro",
    "2": "Standard", "standard": "Standard",
    "3": "Full", "full": "Full",
}
_COMPLEXITY_COERCE: dict[str, str] = {
    "s": "S", "small": "S",
    "m": "M", "medium": "M",
    "l": "L", "large": "L",
    "xl": "XL", "extra-large": "XL", "extralarge": "XL", "extra_large": "XL",
}
_VALID_TIERS = {"Micro", "Standard", "Full"}
_VALID_MODES = {"greenfield", "improvement"}
_VALID_COMPLEXITIES = {"S", "M", "L", "XL"}


def _coerce_classification(cls: dict) -> dict:
    """Coerce obvious model drift in classification enum fields; raise on unrecognised values."""
    tier = str(cls.get("tier", ""))
    if tier not in _VALID_TIERS:
        coerced = _TIER_COERCE.get(tier.lower()) or _TIER_COERCE.get(tier)
        if coerced is None:
            raise LLMParseError(f"unrecognised tier {tier!r}; expected Micro/Standard/Full")
        cls = {**cls, "tier": coerced}

    mode = str(cls.get("mode", ""))
    if mode not in _VALID_MODES:
        raise LLMParseError(f"unrecognised mode {mode!r}; expected greenfield/improvement")

    complexity = str(cls.get("complexity", ""))
    if complexity not in _VALID_COMPLEXITIES:
        coerced = _COMPLEXITY_COERCE.get(complexity.lower()) or _COMPLEXITY_COERCE.get(complexity)
        if coerced is None:
            raise LLMParseError(f"unrecognised complexity {complexity!r}; expected S/M/L/XL")
        cls = {**cls, "complexity": coerced}

    return cls


def _validate_phase2(parsed: dict) -> None:
    """Raise LLMParseError if the Phase 2 reply is missing required keys."""
    for key in ("classification", "prd", "dmaic_plan"):
        if key not in parsed:
            raise LLMParseError(f"Phase 2 reply missing required key: {key!r}")


def _build_phase2_user(
    request: str, questions: list[str], answers: dict[str, Any]
) -> str:
    """Assemble the Phase 2 user message from request, questions, and answers."""
    q_and_a = "\n".join(
        f"Q{i + 1}: {q}\nA{i + 1}: {answers.get(str(i + 1), answers.get(q, '(no answer provided)'))}"
        for i, q in enumerate(questions)
    )
    return textwrap.dedent(f"""\
        ORIGINAL REQUEST
        {request}

        CLARIFYING QUESTIONS AND OPERATOR ANSWERS
        {q_and_a}
    """)


def _write_prd(parsed: dict, header: StateHeader, workspace: Path) -> Path:
    """Render the structured PRD JSON to a markdown file and return its path."""
    prd = parsed["prd"]
    cls = parsed["classification"]

    prd_dir = workspace / "wiki" / "projects" / header.project_id
    prd_dir.mkdir(parents=True, exist_ok=True)
    prd_path = prd_dir / "PRD.md"

    lines: list[str] = [
        f"# PRD — {header.project_id}",
        "",
        f"**Tier:** {cls['tier']}  **Mode:** {cls['mode']}  "
        f"**Complexity:** {cls['complexity']}  **Physical:** {cls.get('physical', False)}",
        "",
    ]

    _section(lines, "Overview & Goals", prd.get("overview_goals", ""))
    _section(lines, "Problem Statement", prd.get("problem_statement", ""))
    _section(lines, "Target Audience", prd.get("target_audience", ""))

    lines += ["## Success Metrics", ""]
    for m in prd.get("success_metrics", []):
        lines.append(f"- {m}")
    lines.append("")

    lines += ["## Features & Requirements", ""]
    fr = prd.get("features_requirements", {})
    for label, key in (
        ("Functional", "functional"),
        ("Non-functional", "non_functional"),
        ("Usability", "usability"),
    ):
        items = fr.get(key, [])
        if items:
            lines.append(f"### {label}")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")

    _section(lines, "User Journey", prd.get("user_journey", ""))

    lines += ["## Assumptions & Constraints", ""]
    for a in prd.get("assumptions_constraints", []):
        lines.append(f"- {a}")
    lines.append("")

    _section(lines, "Competitive Context", prd.get("competitive_context", ""))

    lines += ["## Out of Scope", ""]
    for o in prd.get("out_of_scope", []):
        lines.append(f"- {o}")
    lines.append("")

    lines += ["## Acceptance Criteria", ""]
    for i, ac in enumerate(prd.get("acceptance_criteria", []), 1):
        lines.append(f"{i}. {ac}")
    lines.append("")

    if parsed.get("dmaic_plan"):
        lines += ["## DMAIC Plan", ""]
        for phase in parsed["dmaic_plan"]:
            lines.append(f"### {phase.get('phase', '?')}")
            lines.append(f"**Owner:** {phase.get('owner', '?')}  "
                         f"**Entry:** {phase.get('entry', '?')}  "
                         f"**Exit:** {phase.get('exit', '?')}")
            lines.append("")
            for d in phase.get("deliverables", []):
                lines.append(f"- {d}")
            lines.append("")

    if parsed.get("summary_card"):
        lines += ["---", "", f"_{parsed['summary_card']}_", ""]

    _tmp = prd_path.with_suffix(".tmp")
    _tmp.write_text("\n".join(lines))
    _tmp.replace(prd_path)
    return prd_path


def _section(lines: list[str], title: str, body: str) -> None:
    """Append a two-line markdown section (heading + body + blank line)."""
    lines += [f"## {title}", "", body, ""]
