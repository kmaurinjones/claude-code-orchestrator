"""PROGRESS.md manager for session continuity across context windows.

This module implements the progress tracking pattern from Anthropic's long-running
agent research. Actors read progress at session start to understand what happened
in previous sessions, and append their work summary at the end.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional


class ProgressManager:
    """Manages PROGRESS.md for cross-session continuity."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.progress_path = self.workspace / "current" / "PROGRESS.md"

    def initialize(self) -> None:
        """Create PROGRESS.md with initial template if it doesn't exist."""
        if self.progress_path.exists():
            return

        self.progress_path.parent.mkdir(parents=True, exist_ok=True)

        template = """# PROGRESS.md

This file tracks progress across orchestrator sessions. Each session appends
its work summary here. Actors read this at the start of each task to understand
what happened in previous sessions.

---

## Session Log

"""
        self.progress_path.write_text(template)

    def get_recent_progress(self, max_entries: int = 5) -> str:
        """Read recent progress entries for actor context."""
        if not self.progress_path.exists():
            return "No previous progress recorded."

        content = self.progress_path.read_text()

        lines = content.split("\n")
        session_starts: List[int] = []

        for i, line in enumerate(lines):
            if line.startswith("### Session") or line.startswith("### Task"):
                session_starts.append(i)

        if not session_starts:
            return "No previous progress recorded."

        recent_starts = session_starts[-max_entries:]
        start_idx = recent_starts[0]

        recent_content = "\n".join(lines[start_idx:])
        return recent_content.strip() or "No previous progress recorded."

    def append_task_progress(
        self,
        task_id: str,
        task_title: str,
        status: str,
        summary: str,
        step: int,
        files_changed: Optional[List[str]] = None,
    ) -> None:
        """Append progress entry after task completion."""
        if not self.progress_path.exists():
            self.initialize()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        files_section = ""
        if files_changed:
            files_list = "\n".join(f"  - `{f}`" for f in files_changed[:10])
            if len(files_changed) > 10:
                files_list += f"\n  - ... and {len(files_changed) - 10} more"
            files_section = f"\n- **Files changed**:\n{files_list}"

        entry = f"""
### Task {task_id} (Step {step}) - {status}
**Time**: {timestamp}
**Title**: {task_title}

**Summary**: {summary}{files_section}

---
"""
        with open(self.progress_path, "a") as f:
            f.write(entry)

    def append_session_start(self, trace_id: str, goals_summary: str) -> None:
        """Record session start marker."""
        if not self.progress_path.exists():
            self.initialize()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        entry = f"""
### Session Started: {trace_id}
**Time**: {timestamp}
**Goals**: {goals_summary}

"""
        with open(self.progress_path, "a") as f:
            f.write(entry)

    def get_git_recent_commits(self, project_root: Path, count: int = 5) -> str:
        """Get recent git commits for context."""
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"-{count}"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            return "No git commits found."
        except Exception:
            return "Git history unavailable."

    def get_git_status_summary(self, project_root: Path) -> str:
        """Get current git status for context."""
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                if len(lines) > 10:
                    return (
                        "\n".join(lines[:10])
                        + f"\n... and {len(lines) - 10} more files"
                    )
                return result.stdout.strip()
            return "Working directory clean."
        except Exception:
            return "Git status unavailable."
