"""The append-only decision log (§4.4).

Every verdict, operator decision, gate grant or denial, retry, escalation, and
budget event is appended here and never edited. Slack notifies; this remembers.
Appends are serialised because the orchestrator is the sole writer in normal
operation, so the log is a faithful, ordered record of why the system did what
it did.
"""

from __future__ import annotations

import time
from pathlib import Path


class DecisionLog:
    """Markdown-backed, append-only audit log for one project."""

    def __init__(self, root: Path, project_id: str) -> None:
        wiki = Path(root) / "wiki" / "projects" / project_id
        wiki.mkdir(parents=True, exist_ok=True)
        self._path = wiki / "decisions.md"
        if not self._path.exists():
            header = (
                f"# Decision log — {project_id}\n\n"
                "Append-only. Records verdicts, operator decisions, escalations, "
                "and budget events.\n\n"
                "| Timestamp | Event | Detail | Actor |\n"
                "|-----------|-------|--------|-------|\n"
            )
            self._path.write_text(header)

    @property
    def path(self) -> Path:
        """Filesystem path of the log."""
        return self._path

    def append(self, event: str, detail: str, actor: str) -> None:
        """Append one immutable entry to the log."""
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        safe_detail = detail.replace("|", "\\|")
        with self._path.open("a") as handle:
            handle.write(f"| {stamp} | {event} | {safe_detail} | {actor} |\n")

    def entries(self) -> list[str]:
        """Return the data rows of the log (excluding the header block)."""
        lines = self._path.read_text().splitlines()
        return [ln for ln in lines if ln.startswith("| ") and "Timestamp" not in ln and "---" not in ln]
