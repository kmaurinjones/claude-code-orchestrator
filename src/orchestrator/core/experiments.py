"""Lightweight experiment logging utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


@dataclass
class ExperimentRecord:
    run_name: str
    command: str
    started_at: str
    finished_at: str
    return_code: int
    log_path: Optional[str]
    metrics: Optional[Dict[str, Any]]
    artifacts: Optional[Dict[str, str]]
    notes: Optional[str] = None


class ExperimentLogger:
    """Persists experiment metadata for long-running jobs."""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.history_dir = (self.workspace / "history").resolve()
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.history_dir / "experiments.jsonl"

    def append(self, record: ExperimentRecord) -> None:
        payload = json.dumps(asdict(record), ensure_ascii=False)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(payload + "\n")

    def create_record(
        self,
        run_name: str,
        command: str,
        return_code: int,
        started: datetime,
        finished: datetime,
        log_path: Optional[Path],
        metrics: Optional[Dict[str, Any]] = None,
        artifacts: Optional[Dict[str, str]] = None,
        notes: Optional[str] = None,
    ) -> ExperimentRecord:
        return ExperimentRecord(
            run_name=run_name,
            command=command,
            started_at=started.strftime(TIMESTAMP_FORMAT),
            finished_at=finished.strftime(TIMESTAMP_FORMAT),
            return_code=return_code,
            log_path=str(log_path) if log_path else None,
            metrics=metrics,
            artifacts=artifacts,
            notes=notes,
        )
