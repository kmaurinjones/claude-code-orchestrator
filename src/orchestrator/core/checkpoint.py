"""Checkpoint/resume system for orchestrator state persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

from ..models import TaskStatus

console = Console()


@dataclass
class CheckpointData:
    """Serializable snapshot of orchestrator state."""

    step: int
    trace_id: str
    timestamp: str
    task_states: Dict[str, str]  # task_id -> status
    completed_task_ids: List[str]
    failed_task_ids: List[str]
    current_task_id: Optional[str]
    feedback_log: List[Dict[str, Any]]
    notes_summary: str
    version: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckpointData":
        return cls(
            step=data["step"],
            trace_id=data["trace_id"],
            timestamp=data["timestamp"],
            task_states=data["task_states"],
            completed_task_ids=data["completed_task_ids"],
            failed_task_ids=data["failed_task_ids"],
            current_task_id=data.get("current_task_id"),
            feedback_log=data.get("feedback_log", []),
            notes_summary=data.get("notes_summary", ""),
            version=data.get("version", "unknown"),
        )


class CheckpointManager:
    """Manages checkpoint creation, storage, and restoration."""

    def __init__(self, workspace: Path, max_checkpoints: int = 10):
        self.workspace = Path(workspace).resolve()
        self.checkpoint_dir = self.workspace / "checkpoints"
        self.max_checkpoints = max_checkpoints

    def initialize(self) -> None:
        """Create checkpoint directory if needed."""
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        step: int,
        trace_id: str,
        task_states: Dict[str, TaskStatus],
        completed_task_ids: List[str],
        failed_task_ids: List[str],
        current_task_id: Optional[str],
        feedback_log: List[Dict[str, Any]],
        notes_summary: str,
        version: str,
    ) -> Path:
        """Save a checkpoint at the current step."""
        self.initialize()

        checkpoint = CheckpointData(
            step=step,
            trace_id=trace_id,
            timestamp=datetime.utcnow().isoformat(),
            task_states={tid: status.value for tid, status in task_states.items()},
            completed_task_ids=completed_task_ids,
            failed_task_ids=failed_task_ids,
            current_task_id=current_task_id,
            feedback_log=feedback_log,
            notes_summary=notes_summary,
            version=version,
        )

        # Save with step number in filename
        checkpoint_file = self.checkpoint_dir / f"checkpoint_{step:05d}.json"
        checkpoint_file.write_text(json.dumps(checkpoint.to_dict(), indent=2))

        # Also save as "latest"
        latest_file = self.checkpoint_dir / "latest.json"
        latest_file.write_text(json.dumps(checkpoint.to_dict(), indent=2))

        # Cleanup old checkpoints
        self._cleanup_old_checkpoints()

        console.print(f"[dim]{self._timestamp()} [CHECKPOINT][/dim] Saved checkpoint at step {step}")

        return checkpoint_file

    def load_latest(self) -> Optional[CheckpointData]:
        """Load the most recent checkpoint."""
        latest_file = self.checkpoint_dir / "latest.json"
        if not latest_file.exists():
            return None

        try:
            data = json.loads(latest_file.read_text())
            return CheckpointData.from_dict(data)
        except (json.JSONDecodeError, KeyError) as exc:
            console.print(f"[yellow]{self._timestamp()} [CHECKPOINT][/yellow] Failed to load checkpoint: {exc}")
            return None

    def load_step(self, step: int) -> Optional[CheckpointData]:
        """Load checkpoint from a specific step."""
        checkpoint_file = self.checkpoint_dir / f"checkpoint_{step:05d}.json"
        if not checkpoint_file.exists():
            return None

        try:
            data = json.loads(checkpoint_file.read_text())
            return CheckpointData.from_dict(data)
        except (json.JSONDecodeError, KeyError) as exc:
            console.print(f"[yellow]{self._timestamp()} [CHECKPOINT][/yellow] Failed to load checkpoint: {exc}")
            return None

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """List all available checkpoints with metadata."""
        if not self.checkpoint_dir.exists():
            return []

        checkpoints = []
        for file in sorted(self.checkpoint_dir.glob("checkpoint_*.json")):
            try:
                data = json.loads(file.read_text())
                checkpoints.append({
                    "file": file.name,
                    "step": data["step"],
                    "timestamp": data["timestamp"],
                    "trace_id": data["trace_id"],
                    "completed_count": len(data.get("completed_task_ids", [])),
                    "failed_count": len(data.get("failed_task_ids", [])),
                })
            except (json.JSONDecodeError, KeyError):
                continue

        return checkpoints

    def _cleanup_old_checkpoints(self) -> None:
        """Remove old checkpoints beyond max_checkpoints limit."""
        if not self.checkpoint_dir.exists():
            return

        checkpoint_files = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
        if len(checkpoint_files) > self.max_checkpoints:
            for old_file in checkpoint_files[:-self.max_checkpoints]:
                old_file.unlink()

    def clear_all(self) -> None:
        """Remove all checkpoints."""
        if self.checkpoint_dir.exists():
            for file in self.checkpoint_dir.glob("*.json"):
                file.unlink()
            console.print(f"[dim]{self._timestamp()} [CHECKPOINT][/dim] Cleared all checkpoints")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y-%m-%d--%H-%M-%S")


def restore_task_states(checkpoint: CheckpointData) -> Dict[str, TaskStatus]:
    """Convert checkpoint task states back to TaskStatus enum."""
    result = {}
    for task_id, status_str in checkpoint.task_states.items():
        # Find matching TaskStatus by value
        for status in TaskStatus:
            if status.value == status_str:
                result[task_id] = status
                break
        else:
            # Default to BACKLOG if status not found
            result[task_id] = TaskStatus.BACKLOG
    return result
