"""User feedback tracking system for orchestrator runs."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel


class FeedbackEntry(BaseModel):
    """A single user feedback entry."""
    task_id: Optional[str] = None  # None means general feedback
    content: str
    timestamp: datetime

    @property
    def is_general(self) -> bool:
        return self.task_id is None


class FeedbackTracker:
    """Tracks user feedback from USER_NOTES.md file."""

    NEW_NOTES_HEADER = "## New Notes (Write here - will be consumed on next review)"
    REVIEWED_HEADER = "## Previously Reviewed"

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.notes_file = workspace / "current" / "USER_NOTES.md"
        self.state_file = workspace / "current" / ".feedback_state.json"

    def initialize(self) -> None:
        """Create initial USER_NOTES.md if it doesn't exist."""
        if self.notes_file.exists():
            return

        self.notes_file.parent.mkdir(parents=True, exist_ok=True)

        template = f"""# USER FEEDBACK

This file allows you to provide feedback to the orchestrator during execution.

**How to use:**
1. Add new notes under "New Notes" using `- [task-007] do X` or `- [general] pause work`.
2. The orchestrator ingests the New Notes section at the start of every task attempt.
3. Reviewed notes are automatically moved to "Previously Reviewed" with a timestamp.

---

{self.NEW_NOTES_HEADER}

- [general] Example note


---

{self.REVIEWED_HEADER}

- None yet
"""
        self.notes_file.write_text(template)

    def has_new_feedback(self) -> bool:
        """Check if new feedback exists since last check."""
        if not self.notes_file.exists():
            return False

        current_mtime = self.notes_file.stat().st_mtime

        if self.state_file.exists():
            try:
                state = json.loads(self.state_file.read_text())
                last_mtime = state.get("last_processed_mtime", 0)

                # Check if file was modified AND has content in new notes section
                if current_mtime > last_mtime:
                    content = self.notes_file.read_text()
                    new_notes = self._extract_new_notes_section(content)
                    return bool(new_notes.strip())

                return False
            except (json.JSONDecodeError, KeyError):
                # State file corrupt, assume new feedback
                return True

        # First time checking
        return True

    def consume_feedback(self) -> List[FeedbackEntry]:
        """
        Extract and consume new feedback entries.
        Moves consumed entries to "Previously Reviewed" section.
        Returns list of feedback entries.
        """
        if not self.notes_file.exists():
            return []

        content = self.notes_file.read_text()
        new_notes_section = self._extract_new_notes_section(content)

        if not new_notes_section.strip():
            return []

        # Parse entries
        entries = self._parse_entries(new_notes_section)

        if not entries:
            return []

        # Archive consumed notes and clear new section
        self._archive_and_clear(content, new_notes_section)

        # Update state
        self._update_state()

        return entries

    def _extract_new_notes_section(self, content: str) -> str:
        """Extract content between 'New Notes' and 'Previously Reviewed' headers."""
        pattern = rf"{re.escape(self.NEW_NOTES_HEADER)}(.*?){re.escape(self.REVIEWED_HEADER)}"
        match = re.search(pattern, content, re.DOTALL)

        if not match:
            return ""

        return match.group(1).strip()

    def _parse_entries(self, notes_section: str) -> List[FeedbackEntry]:
        """
        Parse feedback entries from notes section.

        Expected format:
        - [task-001] Some feedback about task 001
        - [general] General feedback
        - Plain text without brackets is treated as general feedback
        """
        entries = []
        timestamp = datetime.now()

        # Split by lines starting with '-'
        lines = notes_section.split('\n')

        for line in lines:
            line = line.strip()

            if not line:
                continue

            # Remove leading bullet if present
            if line.startswith('-') or line.startswith('*'):
                line = line[1:].strip()

            if not line:
                continue

            # Parse [task-id] prefix
            task_match = re.match(r'\[([^\]]+)\]\s*(.*)', line)

            if task_match:
                task_id_raw = task_match.group(1).strip()
                content = task_match.group(2).strip()

                # Handle [general] as no task_id
                task_id = None if task_id_raw.lower() == "general" else task_id_raw

                if content:
                    entries.append(FeedbackEntry(
                        task_id=task_id,
                        content=content,
                        timestamp=timestamp
                    ))
            else:
                # No bracket format - treat as general feedback
                entries.append(FeedbackEntry(
                    task_id=None,
                    content=line,
                    timestamp=timestamp
                ))

        return entries

    def _archive_and_clear(self, original_content: str, consumed_notes: str) -> None:
        """
        Move consumed notes to 'Previously Reviewed' section and clear 'New Notes'.
        """
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Create archive entry
        archive_entry = f"\n<!-- Reviewed at {timestamp_str} -->\n{consumed_notes}\n"

        # Find the Previously Reviewed section
        parts = original_content.split(self.REVIEWED_HEADER)

        if len(parts) != 2:
            # Malformed file, recreate structure
            self.initialize()
            return

        before_reviewed = parts[0]
        after_reviewed = parts[1]

        # Clear New Notes section
        new_notes_cleared = re.sub(
            rf"({re.escape(self.NEW_NOTES_HEADER)})(.*?)(---)",
            r"\1\n\n\n---",
            before_reviewed,
            flags=re.DOTALL
        )

        # Append to Previously Reviewed
        updated_content = (
            new_notes_cleared +
            self.REVIEWED_HEADER +
            archive_entry +
            after_reviewed
        )

        self.notes_file.write_text(updated_content)

    def _update_state(self) -> None:
        """Update state file with current mtime."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "last_processed_mtime": self.notes_file.stat().st_mtime,
            "last_processed_time": datetime.now().isoformat()
        }

        self.state_file.write_text(json.dumps(state, indent=2))
