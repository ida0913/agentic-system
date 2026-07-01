"""The Architect agent — single-shot design package from an approved PRD.

Reads the approved PRD from the detail blob (primary) or PRD.md (fallback),
calls Claude once, validates the structured tier assessment, writes DESIGN.md,
and returns success so the orchestrator advances DESIGN -> DESIGN_REVIEW where
the DESIGN_APPROVAL gate already waits.

Validation failures and LLM errors both return AgentResult(ok=False) so the
orchestrator's built-in retry/escalation path handles them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .llm import LLMError, LLMParseError, call_claude, parse_json
from .prompts.architect import ARCHITECT_MAX_TOKENS, ARCHITECT_MODEL, ARCHITECT_SYSTEM
from .protocol import VALID_TIERS, AgentResult
from .state import StateHeader

_VALID_VERDICTS = {"agree", "challenge"}


class ArchitectAgent:
    """Single-shot Architect agent: reads approved PRD, emits design package."""

    def __call__(
        self,
        header: StateHeader,
        fetch_detail: Callable[[], dict[str, Any]],
        workspace: Path,
    ) -> AgentResult:
        """Run the Architect: PRD in, design package out.

        Reads the approved PRD, calls Claude, validates the reply, writes
        DESIGN.md, and persists the full structured object into the detail blob.
        """
        detail = fetch_detail()
        try:
            user_msg = _build_user_msg(detail, header, workspace)
            raw = call_claude(ARCHITECT_SYSTEM, user_msg, ARCHITECT_MODEL, ARCHITECT_MAX_TOKENS)
            parsed = parse_json(raw)
            _validate_tier_assessment(parsed)
            design_path = _write_design(parsed, header, workspace)
        except (LLMError, LLMParseError) as exc:
            return AgentResult(ok=False, summary=f"Architect error: {exc}")

        ta = parsed["tier_assessment"]
        n_options = len(parsed.get("tech_stack_options", []))
        n_decisions = len(parsed.get("operator_decisions", []))
        return AgentResult(
            ok=True,
            tokens=ARCHITECT_MAX_TOKENS // 2,
            detail_patch={"design": parsed},
            summary=(
                f"Architect: verdict={ta['verdict']} "
                f"({ta['current_tier']} -> {ta['recommended_tier']}), "
                f"{n_options} stack option(s), {n_decisions} operator decision(s)"
            ),
            artifacts=[str(design_path.relative_to(workspace))],
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_tier_assessment(parsed: dict[str, Any]) -> None:
    """Raise LLMParseError if the tier_assessment block violates the contract.

    Enforced rules (parallel to the PM's _validate_resolved_operation):
    - tier_assessment key must be present.
    - verdict must be exactly "agree" or "challenge".
    - current_tier and recommended_tier must each be Micro / Standard / Full.
    - When verdict is "agree", recommended_tier must equal current_tier.
    - tech_stack_options must contain at least 2 entries.
    """
    if "tier_assessment" not in parsed:
        raise LLMParseError("reply missing required key: 'tier_assessment'")
    ta = parsed["tier_assessment"]

    verdict = ta.get("verdict")
    if verdict not in _VALID_VERDICTS:
        raise LLMParseError(
            f"tier_assessment.verdict must be 'agree' or 'challenge', got {verdict!r}"
        )

    current_tier = ta.get("current_tier")
    if current_tier not in VALID_TIERS:
        raise LLMParseError(
            f"tier_assessment.current_tier must be Micro/Standard/Full, got {current_tier!r}"
        )

    recommended_tier = ta.get("recommended_tier")
    if recommended_tier not in VALID_TIERS:
        raise LLMParseError(
            f"tier_assessment.recommended_tier must be Micro/Standard/Full, got {recommended_tier!r}"
        )

    if verdict == "agree" and recommended_tier != current_tier:
        raise LLMParseError(
            f"verdict='agree' but recommended_tier {recommended_tier!r} != current_tier {current_tier!r}"
        )

    options = parsed.get("tech_stack_options", [])
    if len(options) < 2:
        raise LLMParseError(
            f"tech_stack_options must contain >= 2 entries, got {len(options)}"
        )


# ---------------------------------------------------------------------------
# User message construction
# ---------------------------------------------------------------------------


def _build_user_msg(
    detail: dict[str, Any], header: StateHeader, workspace: Path
) -> str:
    """Build the Architect's user message from the approved PRD.

    Primary source: the structured ``prd`` object the PM persisted in the detail
    blob, combined with the classification and resolved_operation fields.
    Fallback: the rendered PRD.md on disk.
    """
    prd = detail.get("prd")
    if prd is not None:
        cls = detail.get("_classification", {})
        resolved_op = detail.get("resolved_operation", "")
        payload: dict[str, Any] = {
            "classification": {
                "tier": cls.get("tier", header.tier),
                "mode": cls.get("mode", header.mode),
                "complexity": cls.get("complexity", header.complexity),
                "physical": cls.get("physical", False),
            },
            "resolved_operation": resolved_op,
            "prd": prd,
        }
        content = json.dumps(payload, indent=2)
        return f"APPROVED PRD\n\n{content}"

    # Fallback: read the rendered markdown file.
    prd_path = workspace / "wiki" / "projects" / header.project_id / "PRD.md"
    if prd_path.exists():
        return f"APPROVED PRD\n\n{prd_path.read_text()}"
    return "APPROVED PRD\n\n(PRD content unavailable)"


# ---------------------------------------------------------------------------
# Artifact rendering
# ---------------------------------------------------------------------------


def _render_tier_assessment(ta: dict[str, Any]) -> list[str]:
    """Render the Tier Assessment section."""
    return [
        "## Tier Assessment",
        "",
        f"**Verdict:** {ta['verdict']}  "
        f"**Current tier:** {ta['current_tier']}  "
        f"**Recommended tier:** {ta['recommended_tier']}",
        "",
        ta.get("reason", ""),
        "",
    ]


def _render_tech_stack_options(options: list[dict[str, Any]]) -> list[str]:
    """Render the Tech-Stack Options section."""
    lines: list[str] = ["## Tech-Stack Options", ""]
    for opt in options:
        lines.append(f"### {opt.get('name', 'Option')}")
        lines.append("")
        pros = opt.get("pros", [])
        if pros:
            lines.append("**Pros:**")
            for p in pros:
                lines.append(f"- {p}")
        cons = opt.get("cons", [])
        if cons:
            lines.append("**Cons:**")
            for c in cons:
                lines.append(f"- {c}")
        best_if = opt.get("best_if", "")
        if best_if:
            lines.append(f"**Best if:** {best_if}")
        lines.append("")
    return lines


def _render_design_doc(dd: dict[str, Any]) -> list[str]:
    """Render the Design Document section (components, data flow, decisions, questions)."""
    lines: list[str] = ["## Design Document", ""]

    components = dd.get("components", [])
    if components:
        lines += ["### Components", ""]
        for comp in components:
            lines.append(f"- {comp}")
        lines.append("")

    data_flow = dd.get("data_flow", "")
    if data_flow:
        lines += ["### Data Flow", "", data_flow, ""]

    key_decisions = dd.get("key_decisions", [])
    if key_decisions:
        lines += ["### Key Decisions", ""]
        for kd in key_decisions:
            lines.append(f"- {kd}")
        lines.append("")

    open_questions = dd.get("open_questions", [])
    if open_questions:
        lines += ["### Open Questions", ""]
        for oq in open_questions:
            lines.append(f"- {oq}")
        lines.append("")

    return lines


def _render_operator_decisions(op_decisions: list[dict[str, Any]]) -> list[str]:
    """Render the Operator Decisions section. Returns an empty list if none were flagged."""
    if not op_decisions:
        return []
    lines: list[str] = ["## Operator Decisions", ""]
    for od in op_decisions:
        lines.append(f"### [OPERATOR DECISION] {od.get('decision', '')}")
        lines.append("")
        options = od.get("options", [])
        if options:
            lines.append("**Options:**")
            for o in options:
                lines.append(f"- {o}")
        why = od.get("why_it_matters", "")
        if why:
            lines.append(f"**Why it matters:** {why}")
        lines.append("")
    return lines


def _write_design(
    parsed: dict[str, Any], header: StateHeader, workspace: Path
) -> Path:
    """Render the structured design package to DESIGN.md and return its path."""
    design_dir = workspace / "wiki" / "projects" / header.project_id
    design_dir.mkdir(parents=True, exist_ok=True)
    design_path = design_dir / "DESIGN.md"

    lines: list[str] = [f"# DESIGN — {header.project_id}", ""]
    lines += _render_tier_assessment(parsed["tier_assessment"])
    lines += _render_tech_stack_options(parsed.get("tech_stack_options", []))
    lines += _render_design_doc(parsed.get("design_doc", {}))
    lines += _render_operator_decisions(parsed.get("operator_decisions", []))

    summary_card = parsed.get("summary_card", "")
    if summary_card:
        lines += ["---", "", f"_{summary_card}_", ""]

    # Atomic write via temp file + os.replace (Path.replace) — a reader never
    # observes a partially written DESIGN.md.
    _tmp = design_path.with_suffix(".tmp")
    _tmp.write_text("\n".join(lines))
    _tmp.replace(design_path)
    return design_path
