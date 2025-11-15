"""History recording utilities."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class HistoryRecorder:
    """Persists summarized task information under .orchestrator/history/."""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        self.history_dir = self.workspace / "history"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        (self.history_dir / "logs").mkdir(parents=True, exist_ok=True)
        self.tasks_file = self.history_dir / "tasks.jsonl"
        self.tasks_file.touch(exist_ok=True)
        self.experiments_file = self.history_dir / "experiments.jsonl"
        self.experiments_file.touch(exist_ok=True)

    def record_task_event(
        self,
        *,
        task_id: str,
        title: str,
        status: str,
        attempts: int,
        review_summary: str,
        critic_summary: Optional[str],
        tests: List[Dict[str, Any]],
    ) -> None:
        """Append a single task event to history."""
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "task_id": task_id,
            "title": title,
            "status": status,
            "attempts": attempts,
            "review_summary": review_summary,
            "critic_summary": critic_summary,
            "tests": tests,
        }

        with self.tasks_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
