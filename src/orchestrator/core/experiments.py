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


class ExperimentManager:
    """Schedules long-running experiments via the job queue."""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()
        self.history_dir = self.workspace / "history"
        self.jobs_dir = self.history_dir / "jobs" / "queue"
        self.logs_dir = self.history_dir / "logs"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_log_path(self, run_name: str) -> Path:
        timestamp = datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
        safe_name = run_name.replace(" ", "_")
        log_path = self.logs_dir / f"{timestamp}_{safe_name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        return log_path

    def schedule(
        self,
        *,
        command: str,
        run_name: Optional[str],
        workdir: Path,
        timeout: Optional[int],
        notes: Optional[str],
        task_id: Optional[str],
        metrics_file: Optional[str],
    ) -> Path:
        run_label = run_name or f"experiment-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        log_path = self._ensure_log_path(run_label)
        job_id = f"{datetime.now().strftime('%Y-%m-%d--%H-%M-%S')}_{run_label.replace(' ', '_')}"
        job_file = self.jobs_dir / f"{job_id}.json"
        payload = {
            "job_id": job_id,
            "run_name": run_label,
            "command": command,
            "workdir": str(Path(workdir).resolve()),
            "timeout": timeout,
            "metrics_file": metrics_file,
            "log_file": str(log_path),
            "notes": notes,
            "task_id": task_id,
            "mode": "enqueue",
            "created_at": datetime.now().isoformat(),
        }
        job_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return job_file
