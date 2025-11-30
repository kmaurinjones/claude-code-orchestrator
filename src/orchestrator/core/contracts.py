"""Shared dataclasses and enums for the planner/actor/critic loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from ..models import Goal, Task
from .feedback import FeedbackEntry
from .reviewer import ReviewFeedback
from .tester import TestResult


class DecisionType(str, Enum):
    """Planner directive for the orchestrator loop."""

    EXECUTE_TASK = "execute_task"
    WAIT_FOR_JOBS = "wait_for_jobs"
    COMPLETE = "complete"
    IDLE = "idle"


class ActorStatus(str, Enum):
    """Outcome of the actor phase."""

    SUCCESS = "success"
    FAILED = "failed"
    ERROR = "error"


class VerdictStatus(str, Enum):
    """Combined critic verdict after review + production checks."""

    PASS = "pass"
    FAIL = "fail"


@dataclass
class PlanContext:
    """Snapshot of operator guidance + feedback for planner decisions."""

    notes_summary: str
    goals: List[Goal]
    feedback_log: List[Dict[str, Any]]
    user_feedback: List[FeedbackEntry]
    domain: Optional[str]
    surgical_mode: bool
    surgical_paths: List[str]
    progress_summary: str = ""  # Recent progress from PROGRESS.md
    git_status: str = ""  # Current git status for orientation
    git_recent_commits: str = ""  # Recent git commits for context


@dataclass
class PlanDecision:
    """Planner directive for what the actor should do next."""

    type: DecisionType
    task: Optional[Task]
    step: int
    attempt: int
    context: PlanContext
    metadata: Dict[str, Any] = field(default_factory=dict)
    decision_id: str = field(default_factory=lambda: f"plan-{uuid4().hex[:8]}")


@dataclass
class ActorOutcome:
    """Structured output from the actor phase."""

    status: ActorStatus
    task: Task
    step: int
    attempt: int
    agent_result: Dict[str, Any]
    tests: List[TestResult] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class CriticVerdict:
    """Final gate decision that determines whether the task is complete."""

    status: VerdictStatus
    summary: str
    review: Optional[ReviewFeedback] = None
    critic_summary: Optional[str] = None
    findings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    auto_replan: bool = False
