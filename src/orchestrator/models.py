"""Core data models for orchestration system."""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pathlib import Path
from pydantic import BaseModel, Field
from uuid import uuid4


class TaskStatus(str, Enum):
    BACKLOG = "📋"
    IN_PROGRESS = "🚧"
    COMPLETE = "✅"
    FAILED = "❌"
    OBSOLETE = "⏸️"
    REFACTOR = "🔄"


class GoalTier(str, Enum):
    CORE = "core"
    QUALITY = "quality"
    NICE_TO_HAVE = "nice"


class EventType(str, Enum):
    DECISION = "decision"
    SPAWN = "spawn"
    COMPLETE = "complete"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    FILE_WRITE = "file_write"
    FILE_READ = "file_read"
    TASK_UPDATE = "task_update"
    METRIC_CHECK = "metric_check"
    ERROR = "error"
    CHECKPOINT = "checkpoint"
    GOAL_CHECK = "goal_check"
    GOAL_ACHIEVED = "goal_achieved"
    REPLAN = "replan"
    REPLAN_REJECTED = "replan_rejected"
    REFLECTION = "reflection"


class Goal(BaseModel):
    id: str = Field(default_factory=lambda: f"goal-{uuid4().hex[:8]}")
    description: str
    measurable_criteria: str
    tier: GoalTier
    is_negotiable: bool = Field(default=False)
    achieved: bool = Field(default=False)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class VerificationCheck(BaseModel):
    """A verification check to prove task completion.

    Supported types:
    - file_exists: Check if file/directory exists
    - command_passes: Run command, expect exit code 0
    - pattern_in_file: Search for regex pattern in file
    - http_endpoint: Check HTTP endpoint returns expected status
    - metric_threshold: Check metric meets threshold (e.g., "accuracy >= 0.95")
    - schema_valid: Validate JSON/YAML against schema
    - security_scan: Run security linter (bandit, eslint, etc.)
    - type_check: Run type checker (mypy, tsc, etc.)
    - data_quality: Check dataset quality (nulls, duplicates, ranges)
    """
    type: str
    target: str  # File path, URL, command, or metric name
    expected: Optional[str] = None  # Expected value/pattern
    description: str  # Human-readable description of what's being checked
    timeout: Optional[int] = None  # Timeout in seconds (for commands/HTTP)
    metadata: Dict[str, Any] = Field(default_factory=dict)  # Extra config per check type


class Task(BaseModel):
    id: str = Field(default_factory=lambda: f"task-{uuid4().hex[:8]}")
    title: str
    description: str
    status: TaskStatus = TaskStatus.BACKLOG
    priority: int = Field(default=5, ge=1, le=10)
    depends_on: List[str] = Field(default_factory=list)
    blocks: List[str] = Field(default_factory=list)
    related_goals: List[str] = Field(default_factory=list)
    attempt_count: int = 0
    max_attempts: int = 3
    owner: Optional[str] = None
    summary: List[str] = Field(default_factory=list)
    next_action: Optional[str] = None
    acceptance_criteria: List[VerificationCheck] = Field(default_factory=list)
    test_history: List[str] = Field(default_factory=list)
    review_feedback: List[str] = Field(default_factory=list)
    critic_feedback: List[str] = Field(default_factory=list)


class LogEvent(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    step: int  # Every Claude Code call (orchestrator or subagent) increments this
    actor: str
    event: EventType
    trace_id: str
    parent_trace_id: Optional[str] = None
    payload: Dict[str, Any]
    version: Optional[str] = None  # Orchestrator version for debugging


class ClaudeResponse(BaseModel):
    """Parsed response from Claude Code CLI --output-format json"""
    content: str
    stop_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    model: Optional[str] = None


class OrchestratorConfig(BaseModel):
    """Configuration for orchestrator runtime parameters."""
    min_steps: int = Field(default=50, description="Minimum steps before considering stopping")
    max_steps: int = Field(default=100, description="Maximum steps")
    max_parallel_tasks: int = Field(default=1, description="Maximum number of tasks to run in parallel (default sequential execution)")
    subagent_max_turns: int = Field(default=15, ge=1, le=50, description="Maximum number of turns each subagent conversation may use")
    skip_integration_tests: bool = Field(default=True, description="Skip pytest tests marked with @pytest.mark.integration during verification")
    pytest_addopts: Optional[str] = Field(default=None, description="Additional PYTEST_ADDOPTS applied during verification runs")

    @classmethod
    def load(cls, config_path: Path) -> "OrchestratorConfig":
        """Load config from YAML file."""
        if not config_path.exists():
            return cls()

        import yaml
        with open(config_path, 'r') as f:
            data = yaml.safe_load(f) or {}

        return cls(**data)

    def save(self, config_path: Path) -> None:
        """Save config to YAML file."""
        import yaml
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, 'w') as f:
            yaml.safe_dump(
                self.model_dump(),
                f,
                default_flow_style=False,
                sort_keys=False
            )
