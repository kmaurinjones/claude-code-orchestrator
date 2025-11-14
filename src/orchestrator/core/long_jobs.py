"""Manage long-running jobs enqueued by subagents."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List, TextIO

from rich.console import Console

from .experiments import ExperimentLogger

console = Console()


@dataclass
class ManagedJob:
    job_id: str
    metadata_path: Path
    process: subprocess.Popen
    timeout: Optional[int]
    started_at: datetime
    log_handle: TextIO


class LongRunningJobManager:
    """Executes queued long-running jobs outside of Claude sessions."""

    def __init__(self, workspace: Path, project_root: Path):
        self.workspace = Path(workspace).resolve()
        self.project_root = Path(project_root).resolve()
        self.jobs_root = self.workspace / "history" / "jobs"
        self.queue_dir = self.jobs_root / "queue"
        self.running_dir = self.jobs_root / "running"
        self.completed_dir = self.jobs_root / "completed"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.running_dir.mkdir(parents=True, exist_ok=True)
        self.completed_dir.mkdir(parents=True, exist_ok=True)

        self.logger = ExperimentLogger(self.workspace)
        self._running: Dict[str, ManagedJob] = {}

    def process_queue(self) -> None:
        """Start any queued jobs that have not yet been launched."""
        for request_file in sorted(self.queue_dir.glob("*.json")):
            job = json.loads(request_file.read_text())
            job_id = job["job_id"]
            log_path = Path(job["log_file"])
            log_path.parent.mkdir(parents=True, exist_ok=True)

            log_handle = log_path.open("w", encoding="utf-8")
            log_handle.write(f"$ {job['command']}\n\n")
            log_handle.flush()

            process = subprocess.Popen(
                job["command"],
                shell=True,
                cwd=job["workdir"],
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )

            job["status"] = "running"
            job["started_at"] = datetime.now().isoformat()
            job["pid"] = process.pid
            running_path = self.running_dir / request_file.name
            running_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
            request_file.unlink()

            self._running[job_id] = ManagedJob(
                job_id=job_id,
                metadata_path=running_path,
                process=process,
                timeout=job.get("timeout"),
                started_at=datetime.now(),
                log_handle=log_handle,
            )

            console.print(f"[cyan]{datetime.now():%Y-%m-%d--%H-%M-%S} [JOBS][/cyan] Started long-running job {job_id}")

    def poll(self) -> None:
        """Update status for running jobs."""
        for job_id in list(self._running.keys()):
            managed = self._running[job_id]
            job_meta = json.loads(managed.metadata_path.read_text())
            timeout = managed.timeout

            if timeout:
                elapsed = datetime.now() - managed.started_at
                if elapsed > timedelta(seconds=timeout) and managed.process.poll() is None:
                    managed.process.terminate()
                    job_meta["status"] = "timeout"
                    job_meta["finished_at"] = datetime.now().isoformat()
                    job_meta["return_code"] = None
                    self._finalize_job(job_id, managed, job_meta)
                    continue

            result = managed.process.poll()
            if result is None:
                continue

            job_meta["status"] = "completed" if result == 0 else "failed"
            job_meta["return_code"] = result
            job_meta["finished_at"] = datetime.now().isoformat()
            self._finalize_job(job_id, managed, job_meta)

    def _finalize_job(self, job_id: str, managed: ManagedJob, job_meta: Dict) -> None:
        """Move metadata to completed directory and log experiment result."""
        completed_path = self.completed_dir / managed.metadata_path.name
        completed_path.write_text(json.dumps(job_meta, indent=2), encoding="utf-8")
        managed.metadata_path.unlink(missing_ok=True)
        if not managed.log_handle.closed:
            managed.log_handle.flush()
            managed.log_handle.close()
        self._running.pop(job_id, None)

        artifacts = {"log": job_meta.get("log_file")}
        record = self.logger.create_record(
            run_name=job_meta.get("run_name", job_id),
            command=job_meta.get("command", ""),
            return_code=job_meta.get("return_code", 1 if job_meta.get("status") == "failed" else 0),
            started=datetime.fromisoformat(job_meta.get("started_at")),
            finished=datetime.fromisoformat(job_meta.get("finished_at")),
            log_path=Path(job_meta.get("log_file")) if job_meta.get("log_file") else None,
            metrics=None,
            artifacts=artifacts,
            notes=job_meta.get("notes"),
        )
        self.logger.append(record)

        console.print(
            f"[green]{datetime.now():%Y-%m-%d--%H-%M-%S} [JOBS][/green] Job {job_id} "
            f"{job_meta.get('status', 'completed')}"
        )

    def has_pending_jobs(self, task_id: str) -> bool:
        """Check queue and running directories for jobs tied to a task."""
        def _contains(directory: Path) -> bool:
            for path in directory.glob("*.json"):
                data = json.loads(path.read_text())
                if data.get("task_id") == task_id:
                    return True
            return False

        if any(job_id for job_id, managed in self._running.items()
               if json.loads(managed.metadata_path.read_text()).get("task_id") == task_id):
            return True

        return _contains(self.queue_dir) or _contains(self.running_dir)

    def wait_for_task_jobs(self, task_id: str, poll_interval: int = 30) -> None:
        """Block until all queued/running jobs for the given task finish."""
        if not self.has_pending_jobs(task_id):
            return

        console.print(
            f"[yellow]{datetime.now():%Y-%m-%d--%H-%M-%S} [JOBS][/yellow] "
            f"Waiting for long-running jobs spawned by {task_id}"
        )

        while self.has_pending_jobs(task_id):
            self.process_queue()
            self.poll()
            time.sleep(poll_interval)

        console.print(
            f"[green]{datetime.now():%Y-%m-%d--%H-%M-%S} [JOBS][/green] "
            f"All long-running jobs complete for {task_id}"
        )

    def list_recent_jobs(self, limit: int = 5) -> List[Dict]:
        """Return metadata for recently completed jobs."""
        jobs = sorted(self.completed_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        entries: List[Dict] = []
        for path in jobs[:limit]:
            try:
                entries.append(json.loads(path.read_text()))
            except json.JSONDecodeError:
                continue
        return entries
