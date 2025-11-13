"""Utilities for loading user-provided NOTES.md guidance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List


NOTES_FILE_NAME = "NOTES.md"
HEADER = "# User Notes\n"
DEFAULT_BODY = (
    "This file is for the human operator to jot down guidance for the orchestrator.\n"
    "- Add high-priority instructions here while the system is running.\n"
    "- The orchestrator will surface these notes to every subagent and reviewer.\n"
)


@dataclass
class NotesSnapshot:
    """Structured representation of the notes file."""

    path: Path
    content: str
    bullet_points: List[str]


class NotesManager:
    """Handles persistence and summarisation of NOTES.md."""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.notes_path = (self.workspace / "current" / NOTES_FILE_NAME).resolve()
        self.notes_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        if not self.notes_path.exists():
            self.notes_path.write_text(f"{HEADER}\n{DEFAULT_BODY}\n", encoding="utf-8")

    def load(self) -> NotesSnapshot:
        content = self.notes_path.read_text(encoding="utf-8")
        bullet_points = [
            line.strip("- ").strip()
            for line in content.splitlines()
            if line.strip().startswith("-")
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
