"""Planner coordinates state management for the orchestration loop."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Callable, Dict, List, Optional, Set, Tuple

from rich.console import Console

from .. import __version__
from ..models import EventType, Task, TaskStatus
from ..planning.goals import GoalsManager
from ..planning.tasks import TaskGraph
from .contracts import ActorOutcome, ActorStatus, DecisionType, PlanContext, PlanDecision, VerdictStatus, CriticVerdict
from .docs import DocsManager
from .changelog import ChangelogManager, ChangeType
from .feedback import FeedbackEntry, FeedbackTracker
from .history import HistoryRecorder
from .logger import EventLogger
from .notes import NotesManager
from .parallel_executor import get_ready_tasks_batch
from .replanner import Replanner
from .reviewer import ReviewFeedback
from .tester import TestResult

console = Console()


class Planner:
    """Stateful decision maker that feeds the actor/critic loop."""

    def __init__(
        self,
        *,
        project_root: Path,
        workspace: Path,
        goals: GoalsManager,
        tasks: TaskGraph,
        notes_manager: NotesManager,
        feedback_tracker: FeedbackTracker,
        docs_manager: DocsManager,
        changelog_manager: ChangelogManager,
        history_recorder: HistoryRecorder,
        replanner: Replanner,
        logger: EventLogger,
        domain: Optional[str],
        trace_id: str,
        step_allocator: Callable[[], int],
        surgical_mode: bool = False,
        surgical_paths: Optional[List[str]] = None,
        user_feedback_ttl: int = 5,
        max_replan_depth: int = 3,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.workspace = Path(workspace).resolve()
        self.goals = goals
        self.tasks = tasks
        self.notes_manager = notes_manager
        self.feedback_tracker = feedback_tracker
        self.docs_manager = docs_manager
        self.changelog_manager = changelog_manager
        self.history_recorder = history_recorder
        self.replanner = replanner
        self.logger = logger
        self.domain = domain
        self.trace_id = trace_id
        self.step_allocator = step_allocator
        self.surgical_mode = surgical_mode
        self.surgical_paths = [str(Path(p)) for p in (surgical_paths or [])]
        self.user_feedback_ttl = user_feedback_ttl
        self.max_replan_depth = max_replan_depth

        self._active_user_feedback: List[Tuple[FeedbackEntry, int]] = []
        self._task_save_lock = threading.Lock()
        self._task_replan_depth: Dict[str, int] = {}
        for existing_task_id in self.tasks._tasks.keys():
            self._task_replan_depth.setdefault(existing_task_id, 0)

        self.feedback_log: List[Dict[str, str]] = []
        self._notes_summary = self.notes_manager.concise_summary()
        self._cached_context = self._build_context()

    # ------------------------------------------------------------------ #
    # Context refresh                                                     #
    # ------------------------------------------------------------------ #

    def refresh_context(self, current_step: int) -> None:
        """Refresh operator notes + live feedback before planning new work."""
        self._current_step = current_step
        self._notes_summary = self.notes_manager.concise_summary()
        self._prune_user_feedback(current_step)
        self._ingest_user_feedback(current_step)
        self._cached_context = self._build_context()

    def planner_context(self) -> PlanContext:
        """Expose latest context snapshot."""
        return self._cached_context

    def _build_context(self) -> PlanContext:
        entries = [entry for entry, _ in self._active_user_feedback]
        return PlanContext(
            notes_summary=self._notes_summary,
            goals=list(self.goals.core_goals),
            feedback_log=list(self.feedback_log),
            user_feedback=entries,
            domain=self.domain,
            surgical_mode=self.surgical_mode,
            surgical_paths=list(self.surgical_paths),
        )

    # ------------------------------------------------------------------ #
    # Decision making                                                     #
    # ------------------------------------------------------------------ #

    def next_decisions(
        self,
        *,
        max_parallel: int,
        active_ids: Set[str],
    ) -> List[PlanDecision]:
        """Return the next batch of work for the actor."""
        ready_tasks = get_ready_tasks_batch(self.tasks, max_parallel, exclude_ids=active_ids)
        decisions: List[PlanDecision] = []
        for task in ready_tasks:
            task.status = TaskStatus.IN_PROGRESS
            task.attempt_count += 1
            decision = PlanDecision(
                type=DecisionType.EXECUTE_TASK,
                task=task,
                step=self.step_allocator(),
                attempt=task.attempt_count,
                context=self._cached_context,
                metadata={"replan_depth": self._task_replan_depth.get(task.id, 0)},
            )
            decisions.append(decision)
        return decisions

    # ------------------------------------------------------------------ #
    # Result handling                                                     #
    # ------------------------------------------------------------------ #

    def apply_outcome(
        self,
        decision: PlanDecision,
        outcome: ActorOutcome,
        verdict: CriticVerdict,
    ) -> None:
        """Update planner state after actor+critic finish."""
        task = decision.task
        if task is None:
            return

        if outcome.status != ActorStatus.SUCCESS:
            self._handle_actor_failure(task, outcome)
            self._save_tasks()
            return

        if verdict.status == VerdictStatus.PASS:
            review_summary = verdict.review.summary if verdict.review else verdict.summary
            task.status = TaskStatus.COMPLETE
            if review_summary:
                task.summary.append(review_summary[:200])
            task.next_action = None
            self._record_feedback(task, outcome.tests, verdict)
            self._update_docs_and_changelog(task, verdict, success=True)
            self._log_task_history_event(task, verdict, outcome.tests)
            self._save_tasks()
            return

        # Verdict failure
        self._record_feedback(task, outcome.tests, verdict)
        next_hint = verdict.summary or "Critic rejected the current changes."
        if verdict.review and verdict.review.next_steps:
            next_hint = verdict.review.next_steps
        task.summary.append(next_hint[:200])
        task.next_action = next_hint[:200]

        if verdict.review:
            task.review_feedback.append(verdict.review.summary[:200])
            if verdict.review.suggestions:
                task.review_feedback.extend(verdict.review.suggestions)
        if verdict.findings:
            task.critic_feedback.extend(verdict.findings[:3])

        if task.attempt_count >= task.max_attempts:
            task.status = TaskStatus.FAILED
            self._log_task_history_event(task, verdict, outcome.tests)
            self._handle_replan(task, verdict, outcome.tests, decision.metadata.get("replan_depth", 0))
        else:
            task.status = TaskStatus.BACKLOG

        self._update_docs_and_changelog(task, verdict, success=False)

        self._save_tasks()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _record_feedback(
        self,
        task: Task,
        tests: List[TestResult],
        verdict: CriticVerdict,
    ) -> None:
        review = verdict.review
        entry = {
            "task_id": task.id,
            "attempt": task.attempt_count,
            "review_status": review.status if review else verdict.status.value.upper(),
            "review_summary": review.summary if review else verdict.summary,
            "tests": self._serialize_tests(tests),
            "next_steps": review.next_steps if review and review.next_steps else verdict.summary,
            "critic_summary": verdict.critic_summary or verdict.summary,
        }
        self.feedback_log.append(entry)

    def _serialize_tests(self, tests: List[TestResult]) -> List[Dict[str, object]]:
        return [
            {
                "description": res.check.description,
                "type": res.check.type,
                "target": res.check.target,
                "passed": res.passed,
                "message": res.message,
            }
            for res in tests
        ]

    def _log_task_history_event(
        self,
        task: Task,
        verdict: CriticVerdict,
        tests: List[TestResult],
    ) -> None:
        review_summary = verdict.review.summary if verdict.review else verdict.summary
        self.history_recorder.record_task_event(
            task_id=task.id,
            title=task.title,
            status=task.status.name,
            attempts=task.attempt_count,
            review_summary=review_summary,
            critic_summary=verdict.critic_summary or verdict.summary,
            tests=self._serialize_tests(tests),
        )

    def _update_docs_and_changelog(self, task: Task, verdict: CriticVerdict, success: bool) -> None:
        """Update docs + changelog after completion or failure."""
        review = verdict.review
        console.print(f"[cyan]{self._timestamp()} [DOCS][/cyan] Updating docs for {task.id}")

        if success and review:
            title_lower = task.title.lower()
            if "fix" in title_lower or "bug" in title_lower:
                change_type = ChangeType.FIXED
            elif any(keyword in title_lower for keyword in ("add", "implement", "create")):
                change_type = ChangeType.ADDED
            elif any(keyword in title_lower for keyword in ("remove", "delete")):
                change_type = ChangeType.REMOVED
            else:
                change_type = ChangeType.CHANGED

            review_snippet = (review.summary or "").strip()
            if len(review_snippet) > 140:
                review_snippet = review_snippet[:137].rstrip() + "..."
            desc = f"{task.title}" + (f" — {review_snippet}" if review_snippet else "")

            try:
                version = self.changelog_manager.add_entry(
                    change_type=change_type,
                    description=desc,
                    task_id=task.id,
                )
                console.print(f"[dim]{self._timestamp()} [DOCS][/dim] Updated CHANGELOG ({version})")
            except Exception as exc:
                console.print(f"[yellow]{self._timestamp()} [DOCS][/yellow] Failed to update changelog: {exc}")

        review_summary = review.summary if review else verdict.summary
        next_steps = review.next_steps if review else verdict.summary

        changes_summary = f"""
## Task: {task.title}
**Status**: {'✓ SUCCESS' if success else '✗ FAILED'}
**Review**: {review_summary}

## Summary
{chr(10).join(f'- {s}' for s in task.summary[-3:])}

{f"## Next Steps{chr(10)}{next_steps}" if next_steps else ''}
"""

        try:
            docs_result = self.docs_manager.update_after_task(
                task=task,
                success=success,
                changes_summary=changes_summary,
                workspace=self.project_root,
                step=self._current_step,
                parent_trace_id=self.trace_id,
                log_workspace=self.workspace,
            )

            self.docs_manager.ensure_readme_alignment(
                project_readme=self.project_root / "README.md",
                docs_directory=self.project_root / "docs",
                recent_task=task,
                success=success,
                logger=self.logger,
                step=self._current_step,
            )

            if docs_result.get("success"):
                updated = docs_result.get("updated_files", [])
                if updated:
                    console.print(
                        f"[dim]{self._timestamp()} [DOCS][/dim] Updated {len(updated)} documentation files"
                    )
        except Exception as exc:
            console.print(f"[yellow]{self._timestamp()} [DOCS][/yellow] Failed to update docs: {exc}")

    def _handle_actor_failure(self, task: Task, outcome: ActorOutcome) -> None:
        summary = outcome.error or "Subagent failed unexpectedly."
        task.summary.append(f"Attempt {task.attempt_count}: {summary}")
        task.next_action = summary[:200]
        if task.attempt_count >= task.max_attempts:
            task.status = TaskStatus.FAILED
        else:
            task.status = TaskStatus.BACKLOG

    def _handle_replan(
        self,
        task: Task,
        verdict: CriticVerdict,
        test_results: List[TestResult],
        base_replan_depth: int,
    ) -> None:
        """Generate remediation tasks when a task ultimately fails."""
        if base_replan_depth >= self.max_replan_depth:
            console.print(
                f"[dim]{self._timestamp()} [REPLAN][/dim] Skipping replan for {task.id}; max depth reached."
            )
            self.logger.log(
                event_type=EventType.REPLAN_REJECTED,
                actor="planner",
                payload={
                    "task_id": task.id,
                    "reason": "max_depth_reached",
                    "depth": base_replan_depth,
                },
                trace_id=self.trace_id,
                step=self._current_step,
                version=__version__,
            )
            return

        review_feedback = verdict.review or ReviewFeedback(
            status="FAIL",
            summary=verdict.summary,
            next_steps=verdict.summary,
            raw_output="",
        )

        remediation_tasks = self.replanner.analyze_failure(
            failed_task=task,
            review_feedback=review_feedback,
            test_results=test_results,
            step=self._current_step,
        )

        if not remediation_tasks:
            self.logger.log(
                event_type=EventType.REPLAN_REJECTED,
                actor="planner",
                payload={
                    "task_id": task.id,
                    "reason": "no_remediation_tasks_generated",
                },
                trace_id=self.trace_id,
                step=self._current_step,
                version=__version__,
            )
            return

        console.print(
            f"[yellow]{self._timestamp()} [REPLAN][/yellow] Generated {len(remediation_tasks)} remediation task(s)"
        )

        with self._task_save_lock:
            for new_task in remediation_tasks:
                if task.id not in new_task.depends_on:
                    new_task.depends_on.append(task.id)
                new_task.status = TaskStatus.BACKLOG
                self._task_replan_depth[new_task.id] = base_replan_depth + 1
                self.tasks.add_task(new_task)

        for new_task in remediation_tasks:
            self.logger.log(
                event_type=EventType.REPLAN,
                actor="planner",
                payload={
                    "original_task": task.id,
                    "new_task": new_task.id,
                    "reason": "failure_remediation",
                },
                trace_id=self.trace_id,
                step=self._current_step,
                version=__version__,
            )

    def _save_tasks(self) -> None:
        with self._task_save_lock:
            self.tasks.save()

    def _ingest_user_feedback(self, current_step: int) -> None:
        if not self.feedback_tracker.has_new_feedback():
            return
        entries = self.feedback_tracker.consume_feedback()
        if not entries:
            return
        self._active_user_feedback.extend((entry, current_step) for entry in entries)
        self._active_user_feedback = self._active_user_feedback[-10:]
        console.print(
            f"[yellow]{self._timestamp()} [FEEDBACK][/yellow] "
            f"Ingested {len(entries)} user feedback entr{'y' if len(entries) == 1 else 'ies'}"
        )

    def _prune_user_feedback(self, current_step: int) -> None:
        if not self._active_user_feedback:
            return
        self._active_user_feedback = [
            (entry, seen_step)
            for entry, seen_step in self._active_user_feedback
            if current_step - seen_step <= self.user_feedback_ttl
        ]

    @staticmethod
    def _timestamp() -> str:
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
