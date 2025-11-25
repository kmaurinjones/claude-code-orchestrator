"""Main orchestrator logic with task, tester, and reviewer agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
from datetime import datetime

from rich.console import Console

from .. import __version__
from ..models import EventType, TaskStatus
from ..planning.goals import GoalsManager
from ..planning.tasks import TaskGraph
from .logger import EventLogger
from .actor import Actor
from .contracts import DecisionType, PlanDecision
from .planner import Planner
from .tester import Tester
from .reviewer import Reviewer
from .notes import NotesManager
from .feedback import FeedbackTracker
from .replanner import Replanner
from .domain_context import DomainDetector
from .critic import Critic
from .completion_summary import CompletionSummary

console = Console()


def _timestamp() -> str:
    """Return timestamp in YYYY-MM-DD--HH-MM-SS format."""
    return datetime.now().strftime("%Y-%m-%d--%H-%M-%S")


class Orchestrator:
    """Co-ordinates task execution, testing, and review loops."""

    def __init__(
        self,
        workspace: Path = Path(".orchestrator"),
        min_steps: int = 50,
        max_steps: int = 100,
        subagent_max_turns: int = 12,
        skip_integration_tests: bool = True,
        pytest_addopts: Optional[str] = None,
        surgical_mode: bool = False,
        surgical_paths: Optional[List[str]] = None,
        docs_update_interval: int = 10,
    ):
        self.workspace = workspace.resolve()
        self.project_root = self.workspace.parent

        if not self.workspace.is_absolute() or not self.project_root.is_absolute():
            raise ValueError("Workspace and project root must be absolute paths.")

        self.min_steps = min_steps
        self.max_steps = max_steps
        self.subagent_max_turns = subagent_max_turns

        self.logger = EventLogger(self.workspace / "full_history.jsonl")
        self.goals = GoalsManager(self.workspace / "current" / "GOALS.md")
        self.tasks = TaskGraph(self.workspace / "current" / "TASKS.md")

        self.tester = Tester(self.project_root)
        self.reviewer = Reviewer(self.project_root, self.logger, log_workspace=self.workspace)
        self.notes_manager = NotesManager(self.workspace)

        self.feedback_tracker = FeedbackTracker(self.workspace)
        self.feedback_tracker.initialize()

        # Import here to avoid linter removing unused imports
        from .changelog import ChangelogManager
        from .docs import DocsManager

        self.changelog_manager = ChangelogManager(self.project_root)
        self.changelog_manager.initialize()

        self.docs_manager = DocsManager(self.project_root, self.logger)
        self.docs_manager.initialize()

        self.replanner = Replanner(self.project_root, self.logger, log_workspace=self.workspace)
        self.completion_summary = CompletionSummary(self.project_root, self.workspace)
        self.surgical_mode = surgical_mode
        self.surgical_paths = [str(Path(p)) for p in surgical_paths] if surgical_paths else []
        self.project_domain = DomainDetector.detect(self.project_root, self.goals.core_goals)

        self.current_step = 0
        self.trace_id = f"orch-{uuid4().hex[:8]}"

        self.docs_update_interval = docs_update_interval

        self.planner = Planner(
            project_root=self.project_root,
            workspace=self.workspace,
            goals=self.goals,
            tasks=self.tasks,
            notes_manager=self.notes_manager,
            feedback_tracker=self.feedback_tracker,
            docs_manager=self.docs_manager,
            changelog_manager=self.changelog_manager,
            replanner=self.replanner,
            logger=self.logger,
            domain=self.project_domain,
            trace_id=self.trace_id,
            step_allocator=self._next_step,
            surgical_mode=self.surgical_mode,
            surgical_paths=self.surgical_paths,
            docs_update_interval=self.docs_update_interval,
        )

        self.actor = Actor(
            project_root=self.project_root,
            workspace=self.workspace,
            tester=self.tester,
            logger=self.logger,
            trace_id=self.trace_id,
            max_turns=self.subagent_max_turns,
        )

        self.critic = Critic(
            project_root=self.project_root,
            workspace=self.workspace,
            reviewer=self.reviewer,
            logger=self.logger,
            trace_id=self.trace_id,
        )

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def run(self) -> str:
        console.print(f"[cyan]{_timestamp()} [ORCHESTRATOR][/cyan] Starting sequential execution loop")
        console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Min steps: {self.min_steps}")
        console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Max steps: {self.max_steps}")
        console.print()

        self._log_checkpoint("start", {"max_steps": self.max_steps})

        completion_reason = None

        while self.current_step < self.max_steps:
            console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Step {self.current_step}/{self.max_steps}")

            if self.current_step >= self.min_steps and self._check_completion():
                console.print(f"[green]{_timestamp()} [ORCHESTRATOR][/green] All core goals achieved")
                completion_reason = "SUCCESS"
                break

            self.planner.refresh_context(self.current_step)

            decision = self.planner.next_decision()

            if not decision:
                console.print(f"[yellow]{_timestamp()} [ORCHESTRATOR][/yellow] No ready tasks remaining")
                completion_reason = "NO_TASKS_AVAILABLE"
                break

            self._execute_decision(decision)

        if completion_reason is None:
            console.print(f"[yellow]{_timestamp()} [ORCHESTRATOR][/yellow] Reached max iterations ({self.max_steps})")
            completion_reason = "MAX_ITERATIONS_REACHED"

        # Flush any pending docs updates before exit
        self.planner.flush_docs_updates()

        # Generate and display completion summary
        self.completion_summary.generate_and_display(
            goals=list(self.goals.core_goals),
            tasks=self.tasks,
            completion_reason=completion_reason,
            step_count=self.current_step,
        )

        return completion_reason

    # --------------------------------------------------------------------- #
    # Core loop helpers                                                     #
    # --------------------------------------------------------------------- #

    def _execute_decision(self, decision: PlanDecision) -> None:
        """Run a single planner decision through actor + critic."""
        if decision.type != DecisionType.EXECUTE_TASK:
            return

        outcome = self.actor.execute(decision)
        verdict = self.critic.evaluate(decision, outcome)
        self.planner.apply_outcome(decision, outcome, verdict)

    # --------------------------------------------------------------------- #
    # Utility functions                                                     #
    # --------------------------------------------------------------------- #

    def _next_step(self) -> int:
        """Increment and return the current step counter."""
        self.current_step += 1
        return self.current_step

    def _log_checkpoint(self, action: str, payload: Dict[str, object], step_override: Optional[int] = None) -> None:
        self.logger.log(
            event_type=EventType.CHECKPOINT,
            actor="orchestrator",
            payload={"action": action, **payload},
            trace_id=self.trace_id,
            step=step_override if step_override is not None else self.current_step,
            version=__version__,
        )

    def _log_event(self, event_type: EventType, payload: Dict[str, Any]) -> None:
        """Lightweight helper for emitting structured log events."""
        self.logger.log(
            event_type=event_type,
            actor="orchestrator",
            payload=payload,
            trace_id=self.trace_id,
            step=self.current_step,
            version=__version__,
        )

    def _check_completion(self) -> bool:
        """Check if all core goals are achieved using goal evaluator."""
        # Import here to avoid circular dependency
        from .goal_evaluator import GoalEvaluatorRegistry

        console.print(f"[cyan]{_timestamp()} [GOAL-EVAL][/cyan] Evaluating goal achievement")

        # Evaluate all goals
        evaluator = GoalEvaluatorRegistry(self.project_root)
        results = evaluator.evaluate_all_goals(list(self.goals.core_goals))

        # Update goal achieved flags and confidence
        goals_achieved = []
        for goal in self.goals.core_goals:
            result = results.get(goal.id)
            if result:
                goal.achieved = result.achieved
                goal.confidence = result.confidence

                # Log evaluation
                self._log_event(
                    EventType.GOAL_CHECK,
                    {
                        "goal_id": goal.id,
                        "achieved": result.achieved,
                        "confidence": result.confidence,
                        "evidence": result.evidence,
                        "blockers": result.blockers,
                    }
                )

                status_icon = "✓" if result.achieved else "✗"
                console.print(
                    f"[dim]{_timestamp()} [GOAL-EVAL][/dim] {status_icon} {goal.id}: "
                    f"{'ACHIEVED' if result.achieved else 'NOT ACHIEVED'} "
                    f"(confidence: {result.confidence:.2f})"
                )

                if result.evidence:
                    for evidence in result.evidence[:3]:
                        console.print(f"[dim]{_timestamp()}   → {evidence}[/dim]")

                if result.blockers:
                    for blocker in result.blockers[:3]:
                        console.print(f"[yellow]{_timestamp()}   ⚠ {blocker}[/yellow]")

                goals_achieved.append(result.achieved and result.confidence >= 0.7)
            else:
                console.print(f"[yellow]{_timestamp()} [GOAL-EVAL][/yellow] No evaluator for {goal.id}")
                goals_achieved.append(goal.achieved)  # Fallback to existing flag

        # Save updated goal states
        self.goals.save()

        return all(goals_achieved)

    def _all_tasks_complete(self) -> bool:
        for task in self.tasks._tasks.values():
            if task.status in {TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS}:
                return False
        return True
