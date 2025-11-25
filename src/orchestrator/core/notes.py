"""Utilities for loading user-provided USER_NOTES.md guidance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from .feedback import FeedbackTracker


NOTES_FILE_NAME = "USER_NOTES.md"
LEGACY_NOTES_FILE = "NOTES.md"
HEADER = "# User Notes\n"


@dataclass
class NotesSnapshot:
    """Structured representation of the notes file."""

    path: Path
    content: str
    bullet_points: List[str]


class NotesManager:
    """Handles persistence and summarisation of USER_NOTES.md."""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.notes_path = (self.workspace / "current" / NOTES_FILE_NAME).resolve()
        self.notes_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        legacy_path = self.notes_path.parent / LEGACY_NOTES_FILE
        if self.notes_path.exists():
            return

        if legacy_path.exists():
            legacy_path.rename(self.notes_path)
            return

        self.notes_path.write_text(self._build_template(), encoding="utf-8")

    def _build_template(self) -> str:
        return f"""{HEADER}

Provide urgent instructions for the orchestrator. Use the format:
- `[task-007] Please redo sentiment plot colors`
- `[general] Pause new work until I inspect data`

New notes go in the section below. The orchestrator automatically moves consumed notes
into the "Previously Reviewed" section with a timestamp.

---

{FeedbackTracker.NEW_NOTES_HEADER}

- [general] Example note here

---

{FeedbackTracker.REVIEWED_HEADER}
<!-- Reviewed at {datetime.utcnow().isoformat()} -->
- None yet
"""

    def load(self) -> NotesSnapshot:
        self._ensure_exists()
        content = self.notes_path.read_text(encoding="utf-8")
        new_notes = self._extract_new_notes_section(content)
        bullet_points = [
            line.strip("- ").strip()
            for line in new_notes.splitlines()
            if line.strip().startswith(("-", "*"))
        ]
        return NotesSnapshot(
            path=self.notes_path,
            content=content.strip(),
            bullet_points=[bp for bp in bullet_points if bp],
        )

    def concise_summary(self, max_items: int = 5) -> str:
        snapshot = self.load()
        if not snapshot.bullet_points:
            return "No user notes recorded."

        selected = snapshot.bullet_points[:max_items]
        remainder = len(snapshot.bullet_points) - len(selected)
        summary_lines = [f"- {item}" for item in selected]
        if remainder > 0:
            summary_lines.append(f"- … {remainder} additional note(s) omitted")
        return "\n".join(summary_lines)

    def _extract_new_notes_section(self, content: str) -> str:
        """Extract only the editable 'New Notes' block for summaries."""
        start = content.find(FeedbackTracker.NEW_NOTES_HEADER)
        end = content.find(FeedbackTracker.REVIEWED_HEADER)

        if start == -1:
            return content

        start += len(FeedbackTracker.NEW_NOTES_HEADER)
        if end == -1:
            return content[start:]

        return content[start:end].strip()
