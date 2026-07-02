# Prompt Failure Log
<!-- PURPOSE: An append-only log of agent behavior failures, one entry per
observed failure. The future Prompt Engineer agent reads this to find RECURRING
patterns (common-cause) versus one-off incidents (special-cause) and proposes
evidence-backed prompt revisions. Entries are never edited or deleted — corrections
are appended as new entries. This is the same append-only discipline as decisions.md. -->

---

## PF-001

- **date:** 2026-06-27
- **agent:** PM
- **prompt_section:** PM_PHASE2_SYSTEM — CLASSIFICATION ENUM VALUES block
- **failure_class:** contract-drift
- **severity:** high (tier routes the whole pipeline)
- **what_happened:** Phase 2 returned `tier=1` and `complexity="small"` instead of the required enum strings `"Standard"` and `"S"`. The orchestrator would have written a numeric tier to the header, breaking all downstream tier-conditional logic.
- **evidence:** Observed in early smoke run before enum enforcement existed; header would have received `tier: 1` rather than `"Standard"`.
- **recurring:** single-observation
- **fix_applied:** Enum values spelled out explicitly in PM_PHASE2_SYSTEM with a CLASSIFICATION ENUM VALUES section; `_coerce_classification()` added to `agents_pm.py` to coerce known model drift variants (e.g. `"1"` → `"Standard"`, `"small"` → `"S"`) or raise `LLMParseError` on unrecognised values.
- **status:** fixed

---

## PF-002

- **date:** 2026-06-27
- **agent:** external reviewer (GPT-5.5, cross-model code review)
- **prompt_section:** n/a (reviewer reasoning, not agent prompt)
- **failure_class:** reviewer-false-positive
- **severity:** low (cosmetic — would have prompted unnecessary work)
- **what_happened:** GPT-5.5 flagged SIPOC and CTQ Tree as "genuine gaps / missing artifacts" in its review. Both fields were fully present in `state.detail.json`; only the `PRD.md` renderer omitted them. The reviewer reasoned from the truncated PRD preview rather than the source-of-truth JSON.
- **evidence:** `state.detail.json` contained populated `sipoc` and `ctq_tree` keys at the time of review; `PRD.md` did not render them. Reviewer cited the PRD preview as evidence of missing output.
- **recurring:** single-observation
- **fix_applied:** None to any agent prompt — lesson logged: external reviewer findings must be verified against the source-of-truth data file (detail JSON) before acting on them.
- **status:** monitoring

---

## PF-003

- **date:** 2026-06-27
- **agent:** PM
- **prompt_section:** `agents_pm.py` — `_write_prd()` renderer
- **failure_class:** missing-artifact
- **severity:** low (rendering omission, not reasoning error)
- **what_happened:** `agents_pm.py` wrote all prose PRD sections to `PRD.md` but silently omitted the `sipoc` and `ctq_tree` blocks the agent had correctly produced and stored. The artifacts existed in the detail blob but were invisible in the human-readable output.
- **evidence:** `state.detail.json` contained populated `sipoc` and `ctq_tree` keys; `PRD.md` contained no SIPOC or CTQ Tree sections.
- **recurring:** single-observation
- **fix_applied:** Added SIPOC and CTQ Tree rendering blocks to `_write_prd()` in `agents_pm.py`; added test assertions confirming both sections appear in `PRD.md` (commit `e17e714`).
- **status:** fixed

---

## PF-004

- **date:** 2026-06-27
- **agent:** PM
- **prompt_section:** PM_PHASE2_SYSTEM — PRD SECTIONS block (no scope-narrowing instruction existed)
- **failure_class:** scope-ambiguity / output-inconsistency
- **severity:** high (safety-relevant decision varies between identical runs; broader "Repost" interpretation carries higher Craigslist ToS and account-ban risk than narrow "Renew")
- **what_happened:** Two runs of the identical request ("Automate reposting my tutoring listing to Craigslist every 48 hours.") with identical clarifying answers produced conflicting PRDs: run 1 resolved the core operation as "Renew" (click the existing listing's Renew button, refreshing only the timestamp); run 2 resolved it as "Repost" (a broader recreate-class operation implying delete-and-resubmit). The clarifying answer "only the post timestamp needs refreshing" makes Renew unambiguously correct.
- **evidence:** Two consecutive smoke runs, identical `REQUEST` and `CLARIFY_ANSWERS` in `scripts/smoke_pm.py`, conflicting `overview_goals` language and `out_of_scope` content in the two resulting `PRD.md` files. "Repost" and "Renew" are mechanically and legally different; the wrong choice changes the entire implementation approach and elevates ToS risk.
- **recurring:** yes — observed across 2 independent runs
- **fix_applied:** (1) Semantic `SCOPE COMMITMENT` principle added to `PM_PHASE2_SYSTEM`: when answers constrain original request scope, adopt most conservative interpretation consistent with all answers, state it in `overview_goals`, enumerate excluded interpretations in `out_of_scope`. Framed semantically, not as a keyword list. (2) Structured `resolved_operation` field added to Phase 2 JSON schema; validated in `_validate_phase2()` and `_validate_resolved_operation()` in `agents_pm.py` (parallel to `_coerce_classification`); persisted to detail blob; rendered in PRD header. Stability confirmed by 3+ smoke re-runs (see monitoring note below).
- **status:** open → monitoring (fix applied 2026-06-27; awaiting 3+ re-run confirmation)

**Confirmation note (2026-06-28):** 3 independent smoke runs all produced `resolved_operation = Renew` with delete-and-repost explicitly listed in `out_of_scope`. Results:
- Run 1: `resolved_operation = "Automated renewal of a single Craigslist tutoring listing by clicking the native Renew button every 48 hours"` — out_of_scope includes "Delete-and-repost / listing recreation"
- Run 2: `resolved_operation = "Automated Craigslist Renew-button click refreshing the tutoring listing post timestamp every 48 hours"` — out_of_scope includes "Delete-and-repost / listing recreation"
- Run 3: `resolved_operation = "Renew existing Craigslist tutoring listing timestamp by clicking the Renew button every 48 hours"` — out_of_scope includes "Delete-and-repost / listing recreation"

Full test suite: 31 passed. No debug lines in production code. `_validate_resolved_operation` strictly rejects absent/empty field (raises `LLMParseError` → `ok=False` → retry path). **Status: fixed.**

---

## PF-005

- **date:** 2026-06-30
- **agent:** Architect
- **prompt_section:** ARCHITECT_SYSTEM — OPERATOR DECISIONS block (section 4)
- **failure_class:** rendering-duplication
- **severity:** low (cosmetic; no reasoning or routing impact)
- **what_happened:** Operator-decision headers in `DESIGN.md` rendered the `[OPERATOR DECISION]` marker twice (`[OPERATOR DECISION] [OPERATOR DECISION] <title>`). Root cause: `ARCHITECT_SYSTEM` instructed the model to list each entry "as an explicit `[OPERATOR DECISION]`", which the model interpreted as embedding the literal marker text inside the `decision` field. `_write_design()` in `agents_architect.py` then prepended the same marker when rendering the `## Operator Decisions` section, doubling it.
- **evidence:** First live Architect run (`architect-smoke`); `state.detail.json` showed `operator_decisions[].decision` values already prefixed with `"[OPERATOR DECISION] ..."` (e.g. `"[OPERATOR DECISION] Scheduler mechanism: cron vs. launchd"`); `DESIGN.md` then rendered `### [OPERATOR DECISION] [OPERATOR DECISION] Scheduler mechanism: cron vs. launchd`.
- **recurring:** single-observation
- **fix_applied:** Reworded `ARCHITECT_SYSTEM` section 4 in `prompts/architect.py` to say the decision is listed "as an explicit decision" (not "[OPERATOR DECISION]") and explicitly state the renderer adds the marker automatically — the model must not include that literal text in the `decision` field. Added a matching line to VALIDATION NOTES. The renderer (`_write_design`) is unchanged and remains the single source of the marker.
- **status:** fixed

---

## PF-006

- **date:** 2026-06-30
- **agent:** Architect (tendency also present in PM Phase 2)
- **prompt_section:** ARCHITECT_SYSTEM — output depth is not scaled to tier
- **failure_class:** over-processing / no-tier-scaling
- **severity:** low (no correctness or routing impact; cost + latency + Lean concern)
- **what_happened:** The Architect produces the same comprehensive output depth regardless of assessed tier. For a Standard project (Craigslist renewer) it emitted 8 components, a setup.sh, and 5 operator decisions — heavier than the work warrants. The tier system exists to right-size process, but the Architect doesn't act on the tier it just assessed. Flagged independently by operator observation and prior cross-model reviews (over-processing tendency).
- **evidence:** architect-smoke DESIGN.md; ~2-4 min generation, large output
- **recurring:** yes — consistent with PM Phase 2's comprehensiveness (16K-char PRDs)
- **fix_applied:** tier-scaled output added to ARCHITECT_SYSTEM: explicit right-size instruction, per-tier scaling of tech-stack-option count / design-doc depth / operator-decisions, plus a tier-aware validator floor (`_validate_tier_assessment` in `agents_architect.py`: >= 1 tech-stack option for Micro, >= 2 for Standard/Full, keyed off `recommended_tier`). Covered by new tests in `tests/test_architect.py` (Micro 1-option pass, Micro 0-option fail, Full 1-option fail). Verified via `desloppify show` that the changed files (`prompts/architect.py`, `agents_architect.py`, `test_architect.py`) carry zero open findings — see `wiki/DEBT.md` DEBT-001 for the unrelated pre-existing debt this scan also surfaced.
- **status:** fixed

---

## PF-007

- **date:** 2026-07-02
- **agent:** PM (classification) AND Architect (tier-challenge) — both layers
- **prompt_section:** PM classification logic + ARCHITECT_SYSTEM tier_assessment
- **failure_class:** over-classification / tier-inflation
- **severity:** medium (costs unnecessary process + tokens on simple projects; the Lean/right-sizing concern the tier system exists to prevent)
- **what_happened:** On the worksheet-generator project, the PM classified tier=Standard, complexity=M — but the PRD it wrote describes a MICRO project by the system's own rubric: fully offline, no persistence beyond output PDFs, no external API, no PII, no integration, runs locally as a single CLI. The PM's own PRD prose ("no cloud account," "only artifact written to disk is the PDF," "no external API call") argues Micro while its classification field says Standard — the structured classification contradicts the evidence in its own output. The Architect then AGREED (verdict=agree, Standard->Standard) rather than challenging downward to Micro, so the tier-challenge mechanism — which exists specifically to catch mis-classification — did not fire in the correcting direction.
- **evidence:** smoke_workspaces/worksheet-generator — PRD.md classification vs. its own constraints/out-of-scope sections; DESIGN.md tier_assessment verdict=agree
- **recurring:** YES — second observation of the over-classification pattern. First: Craigslist project assessed Standard with heavy/comprehensive output (see PF-006, the over-processing note). Two consecutive projects both classified at or above their true tier; neither was ever challenged downward.
- **fix_applied:** none yet — logged for future prompt tuning. Candidate fixes (do NOT implement now): (a) PM classification prompt should map its own "offline / no persistence / no integration / no PII" findings toward Micro rather than defaulting to Standard; (b) ARCHITECT_SYSTEM tier_assessment should explicitly consider challenging DOWNWARD, not just agreeing or challenging up — right-sizing cuts both directions.
- **status:** open
