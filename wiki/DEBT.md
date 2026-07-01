# Tech Debt Log
<!-- PURPOSE: An append-only log of code-quality/mechanical debt surfaced by
desloppify scans, distinct from wiki/prompt-failures.md (which tracks agent
prompt/behavior failures, not code health). Entries are never edited or
deleted — corrections are appended as new entries. -->

---

## DEBT-001 — desloppify scan surfaced pre-existing debt (2026-07-01)

Context: `desloppify scan` run while validating the PF-006 tier-scaling fix
(commit landing this entry) showed objective score 89.8/100 (down from a prior
baseline of ~98.2), driven by Test health dropping to 79.0% and 13 open Code
quality findings. Investigation confirmed **none of these findings are in the
files touched by the tier-scaling change** (`control_plane/prompts/architect.py`,
`control_plane/agents_architect.py`, `tests/test_architect.py` — zero open
findings on any of the three). The drop is pre-existing debt that surfaced
in this scan, not a regression introduced by that change.

### Verified false positive — "non-atomic file write" (5 instances)

Flagged at: `control_plane/agents.py:35`, `control_plane/approvals.py:79,145`,
`control_plane/audit.py:32`, `control_plane/cost.py:51,64`, and
`control_plane/agents_pm.py:335`.

Checked each site directly: all six already follow the temp-file + atomic
rename pattern (`_tmp = path.with_suffix(".tmp"); _tmp.write_text(...);
_tmp.replace(path)`) — the identical pattern used in `state.py` and
`agents_architect.py::_write_design`, neither of which the detector flags.
The detector is flagging the `write_text` call on the `.tmp` file without
recognizing the following `.replace()` as making the pair atomic. **This is
a detector false positive, not a regression and not real debt** — these
writes were never unsafe. Action: mark these 6 findings `wontfix` (or
`false_positive`) in desloppify with a note pointing here, rather than
"fixing" code that is already correct.

### Real, pre-existing, out of scope for this task

- `control_plane/agents_pm.py` — high cyclomatic complexity (1 function,
  line 231). Real complexity; `agents_pm.py` is on this task's do-not-touch
  list. Backlog: revisit when PM Phase 2 is next touched.
- `control_plane/Orchestrator.py` — single-use file (229 LOC, only imported
  by `demo.py`). Worth a decision (fold into demo.py or delete) but not part
  of tier-scaling scope.
- `control_plane/__init__.py` — re-export facade (35 LOC, 1 importer).
  Low priority; standard package facade pattern.

### Acceptable / dev-tooling — not real product debt

- `demo.py` — orphaned file, 0 importers, untested. It's a manual demo
  entrypoint, not library code; not wired to be imported or tested.
- `scripts/smoke_architect.py`, `scripts/smoke_pm.py` — untested critical
  (0 importers), `sys.path` mutation at import time, `sys.exit()` outside a
  CLI entry point. These are one-off smoke-test scripts run manually from
  the CLI, not imported modules — the smells detector's "library code"
  assumptions (no sys.exit, no path mutation, needs test coverage) don't
  apply to their intended use. Leave as-is unless these scripts get promoted
  to a real CLI entry point.

**Status:** logged. No code changes made in response to this entry — see
verified-false-positive note above for the one action item (suppress in
desloppify), everything else is backlog or accepted.
