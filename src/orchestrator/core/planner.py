"""Planner coordinates state management for the orchestration loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

from rich.console import Console

from .. import __version__
from ..models import EventType, Task, TaskStatus
from ..planning.goals import GoalsManager
from ..planning.tasks import TaskGraph
from .contracts import (
    ActorOutcome,
    ActorStatus,
    DecisionType,
    PlanContext,
    PlanDecision,
    VerdictStatus,
    CriticVerdict,
)
from .docs import DocsManager
from .changelog import ChangelogManager, ChangeType
from .feedback import FeedbackEntry, FeedbackTracker
from .logger import EventLogger
from .notes import NotesManager
from .replanner import Replanner
from .reviewer import ReviewFeedback
from .subagent import Subagent
from .tester import TestResult

if TYPE_CHECKING:
    from .progress import ProgressManager

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
        replanner: Replanner,
        progress_manager: "ProgressManager",
        logger: EventLogger,
        domain: Optional[str],
        trace_id: str,
        step_allocator: Callable[[], int],
        surgical_mode: bool = False,
        surgical_paths: Optional[List[str]] = None,
        user_feedback_ttl: int = 5,
        max_replan_depth: int = 3,
        docs_update_interval: int = 10,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.workspace = Path(workspace).resolve()
        self.goals = goals
        self.tasks = tasks
        self.notes_manager = notes_manager
        self.feedback_tracker = feedback_tracker
        self.docs_manager = docs_manager
        self.changelog_manager = changelog_manager
        self.replanner = replanner
        self.progress_manager = progress_manager
        self.logger = logger
        self.domain = domain
        self.trace_id = trace_id
        self.step_allocator = step_allocator
        self.surgical_mode = surgical_mode
        self.surgical_paths = [str(Path(p)) for p in (surgical_paths or [])]
        self.user_feedback_ttl = user_feedback_ttl
        self.max_replan_depth = max_replan_depth
        self.docs_update_interval = docs_update_interval

        self._active_user_feedback: List[Tuple[FeedbackEntry, int]] = []
        self._task_replan_depth: Dict[str, int] = {}
        for existing_task_id in self.tasks._tasks.keys():
            self._task_replan_depth.setdefault(existing_task_id, 0)

        self.feedback_log: List[Dict[str, str]] = []
        self._notes_summary = self.notes_manager.concise_summary()
        self._cached_context = self._build_context()
        self._last_flush_step: int = (
            -1
        )  # Track step of last flush (-1 means never flushed)
        self._pending_docs_updates: List[Dict[str, object]] = []
        self._pending_changelog_entries: List[Dict[str, object]] = []

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

        # Get progress and git context for cross-session orientation
        progress_summary = self.progress_manager.get_recent_progress(max_entries=3)
        git_status = self.progress_manager.get_git_status_summary(self.project_root)
        git_commits = self.progress_manager.get_git_recent_commits(
            self.project_root, count=5
        )

        return PlanContext(
            notes_summary=self._notes_summary,
            goals=list(self.goals.core_goals),
            feedback_log=list(self.feedback_log),
            user_feedback=entries,
            domain=self.domain,
            surgical_mode=self.surgical_mode,
            surgical_paths=list(self.surgical_paths),
            progress_summary=progress_summary,
            git_status=git_status,
            git_recent_commits=git_commits,
        )

    # ------------------------------------------------------------------ #
    # Decision making                                                     #
    # ------------------------------------------------------------------ #

    def next_decision(self) -> Optional[PlanDecision]:
        """Return the next task to execute, or None if no tasks are ready."""
        ready_tasks = self.tasks.get_ready_tasks()
        if not ready_tasks:
            return None

        # Use Claude to select the best task and validate readiness
        step = self.step_allocator()
        task, reasoning = self._select_task_with_reasoning(ready_tasks, step)

        if task is None:
            console.print(
                f"[yellow]{self._timestamp()} [PLANNER][/yellow] No semantically ready tasks"
            )
            return None

        console.print(
            f"[cyan]{self._timestamp()} [PLANNER][/cyan] {task.id}: {reasoning}"
        )

        task.status = TaskStatus.IN_PROGRESS
        task.attempt_count += 1
        return PlanDecision(
            type=DecisionType.EXECUTE_TASK,
            task=task,
            step=step,
            attempt=task.attempt_count,
            context=self._cached_context,
            metadata={
                "replan_depth": self._task_replan_depth.get(task.id, 0),
                "selection_reasoning": reasoning,
            },
        )

    def _select_task_with_reasoning(
        self, ready_tasks: List[Task], step: int
    ) -> Tuple[Optional[Task], str]:
        """Use Claude to select best task and validate it's semantically ready."""
        if len(ready_tasks) == 1:
            # Single task - still validate readiness
            task = ready_tasks[0]
            is_ready, reasoning = self._check_task_readiness(task, step)
            if is_ready:
                return (task, f"Only ready task: {task.title}")
            else:
                console.print(
                    f"[yellow]{self._timestamp()} [PLANNER][/yellow] "
                    f"Skipping {task.id}: {reasoning}"
                )
                return (None, reasoning)

        # Multiple ready tasks - use Claude to select
        completed = [
            t for t in self.tasks._tasks.values() if t.status == TaskStatus.COMPLETE
        ]
        incomplete = [
            t
            for t in self.tasks._tasks.values()
            if t.status
            in (TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS, TaskStatus.FAILED)
        ]

        task_options = "\n".join(
            f"- {t.id}: {t.title} (priority: {t.priority}, attempts: {t.attempt_count})"
            for t in ready_tasks[:10]
        )

        completed_summary = (
            "\n".join(f"- {t.id}: {t.title}" for t in completed[:10]) or "None"
        )
        incomplete_summary = (
            "\n".join(f"- {t.id}: {t.title}" for t in incomplete[:10]) or "None"
        )

        goals_summary = "\n".join(
            f"- {g.description} ({'ACHIEVED' if g.achieved else 'PENDING'})"
            for g in self.goals.core_goals[:5]
        )

        prompt = f"""You are a task scheduler. Select the best task to execute next.

## Ready Tasks (dependencies satisfied)
{task_options}

## Project Goals
{goals_summary}

## Completed Tasks
{completed_summary}

## Incomplete Tasks
{incomplete_summary}

## Selection Rules
1. NEVER select "final review", "verify", or "validation" tasks until content/implementation tasks are done
2. Prefer foundational tasks (research, implementation) over review tasks
3. Consider priority values (higher = more important)
4. If a task says "verify X exists" but X hasn't been created, skip it

Respond with EXACTLY this JSON:
```json
{{
    "selected_task_id": "task-XXX",
    "reasoning": "Brief explanation (one sentence)",
    "skip_tasks": ["task-YYY"] (tasks that are NOT ready despite passing dependency check)
}}
```"""

        agent = Subagent(
            task_id="task-selector",
            task_description=prompt,
            context="",
            parent_trace_id=self.trace_id,
            logger=self.logger,
            step=step,
            workspace=self.project_root,
            max_turns=3,
            model="haiku",
            log_workspace=self.workspace,
        )

        result = agent.execute()
        output = result.get("output", "")

        try:
            json_start = output.find("{")
            json_end = output.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(output[json_start:json_end])
                task_id = parsed.get("selected_task_id", "")
                reasoning = parsed.get("reasoning", "No reasoning")

                for t in ready_tasks:
                    if t.id == task_id:
                        return (t, reasoning)

        except (json.JSONDecodeError, KeyError):
            pass

        # Fallback: return highest priority non-review task
        for t in ready_tasks:
            title_lower = t.title.lower()
            if not any(
                kw in title_lower for kw in ("review", "verify", "final", "check")
            ):
                return (t, f"Fallback: {t.title} (non-review task)")

        return (ready_tasks[0], f"Fallback: {ready_tasks[0].title}")

    def _check_task_readiness(self, task: Task, step: int) -> Tuple[bool, str]:
        """Validate a single task is semantically ready to execute."""
        title_lower = task.title.lower()

        # Quick heuristic for obvious review/final tasks
        review_keywords = [
            "final review",
            "verify",
            "validation",
            "check that",
            "ensure",
        ]
        is_review_task = any(kw in title_lower for kw in review_keywords)

        if not is_review_task:
            return (True, "Implementation task, ready")

        # Review task - check if content exists
        completed = [
            t for t in self.tasks._tasks.values() if t.status == TaskStatus.COMPLETE
        ]
        incomplete = [
            t
            for t in self.tasks._tasks.values()
            if t.status
            in (TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS, TaskStatus.FAILED)
            and t.id != task.id
        ]

        # If most tasks are still incomplete, review is premature
        if len(completed) < len(incomplete):
            return (
                False,
                f"Review task but {len(incomplete)} tasks still incomplete vs {len(completed)} complete",
            )

        return (True, "Review task, prerequisites appear complete")

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
            review_summary = (
                verdict.review.summary if verdict.review else verdict.summary
            )
            task.status = TaskStatus.COMPLETE
            if review_summary:
                task.summary.append(review_summary)
            task.next_action = None
            self._record_feedback(task, outcome.tests, verdict)
            self._queue_docs_update(task, verdict, success=True)
            self._maybe_flush_docs_updates(decision.step)
            # Record progress for cross-session continuity
            self._record_progress(
                task, "COMPLETED", review_summary or "Task completed", decision.step
            )
            self._save_tasks()
            return

        # Verdict failure
        self._record_feedback(task, outcome.tests, verdict)
        next_hint = verdict.summary or "Critic rejected the current changes."
        if verdict.review and verdict.review.next_steps:
            next_hint = verdict.review.next_steps
        task.summary.append(next_hint)
        task.next_action = next_hint

        if verdict.review:
            task.review_feedback.append(verdict.review.summary)
            if verdict.review.suggestions:
                task.review_feedback.extend(verdict.review.suggestions)
        if verdict.findings:
            task.critic_feedback.extend(verdict.findings[:3])

        if task.attempt_count >= task.max_attempts:
            task.status = TaskStatus.FAILED
            self._record_progress(task, "FAILED", next_hint, decision.step)
            self._handle_replan(
                task, verdict, outcome.tests, decision.metadata.get("replan_depth", 0)
            )
        else:
            task.status = TaskStatus.BACKLOG
            self._record_progress(task, "RETRY_NEEDED", next_hint, decision.step)

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
            "next_steps": review.next_steps
            if review and review.next_steps
            else verdict.summary,
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

    def _record_progress(
        self, task: Task, status: str, summary: str, step: int
    ) -> None:
        """Record task progress to PROGRESS.md for cross-session continuity."""
        # Get changed files from git for context
        changed_files = self._get_changed_files()
        self.progress_manager.append_task_progress(
            task_id=task.id,
            task_title=task.title,
            status=status,
            summary=summary[:200] if summary else "No summary",
            step=step,
            files_changed=changed_files[:10] if changed_files else None,
        )

    def _get_changed_files(self) -> List[str]:
        """Get list of changed files from git."""
        import subprocess

        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split("\n")
        except Exception:
            pass
        return []

    def _queue_docs_update(
        self, task: Task, verdict: CriticVerdict, success: bool
    ) -> None:
        """Queue docs and changelog updates for batch processing."""
        review = verdict.review

        # Queue changelog entry for batch processing
        if success and review:
            title_lower = task.title.lower()
            if "fix" in title_lower or "bug" in title_lower:
                change_type = ChangeType.FIXED
            elif any(
                keyword in title_lower for keyword in ("add", "implement", "create")
            ):
                change_type = ChangeType.ADDED
            elif any(keyword in title_lower for keyword in ("remove", "delete")):
                change_type = ChangeType.REMOVED
            else:
                change_type = ChangeType.CHANGED

            review_snippet = (review.summary or "").strip()
            desc = f"{task.title}" + (f" — {review_snippet}" if review_snippet else "")

            self._pending_changelog_entries.append(
                {
                    "change_type": change_type,
                    "description": desc,
                    "task_id": task.id,
                }
            )

        # Queue the docs update info for batch processing
        review_summary = review.summary if review else verdict.summary
        next_steps = review.next_steps if review else verdict.summary

        self._pending_docs_updates.append(
            {
                "task": task,
                "success": success,
                "review_summary": review_summary,
                "next_steps": next_steps,
            }
        )

    def _maybe_flush_docs_updates(self, current_step: int) -> None:
        """Flush pending docs/changelog updates if step interval reached.

        Updates occur at step 0 (start), every N steps (10, 20, 30...), and at end.
        """
        if not self._pending_changelog_entries and not self._pending_docs_updates:
            return

        # First call (step 0) or hasn't flushed yet
        if self._last_flush_step < 0 and current_step == 0:
            self.flush_docs_updates()
            self._last_flush_step = 0
            return

        # Check if we've crossed an interval boundary
        # E.g., interval=10: flush at steps 10, 20, 30...
        last_interval = self._last_flush_step // self.docs_update_interval
        current_interval = current_step // self.docs_update_interval

        if current_interval > last_interval:
            self.flush_docs_updates()
            self._last_flush_step = current_step

    def flush_docs_updates(self) -> None:
        """Force flush all pending docs/changelog updates (call at end of run or on interval)."""
        # Process pending changelog entries first
        if self._pending_changelog_entries:
            console.print(
                f"[cyan]{self._timestamp()} [CHANGELOG][/cyan] Updating changelog with "
                f"{len(self._pending_changelog_entries)} entries"
            )
            for entry in self._pending_changelog_entries:
                try:
                    version = self.changelog_manager.add_entry(
                        change_type=entry["change_type"],
                        description=entry["description"],
                        task_id=entry["task_id"],
                    )
                    console.print(
                        f"[dim]{self._timestamp()} [CHANGELOG][/dim] Updated ({version})"
                    )
                except Exception as exc:
                    console.print(
                        f"[yellow]{self._timestamp()} [CHANGELOG][/yellow] Failed: {exc}"
                    )
            self._pending_changelog_entries = []

        if not self._pending_docs_updates:
            return

        console.print(
            f"[cyan]{self._timestamp()} [DOCS][/cyan] Updating docs for "
            f"{len(self._pending_docs_updates)} task(s)"
        )

        # Build combined summary
        summaries = []
        last_task = None
        last_success = False
        for update in self._pending_docs_updates:
            task = update["task"]
            success = update["success"]
            review_summary = update["review_summary"]
            next_steps = update["next_steps"]
            last_task = task
            last_success = success

            task_summary = f"""
## Task: {task.title}
**Status**: {"✓ SUCCESS" if success else "✗ FAILED"}
**Review**: {review_summary}

## Summary
{chr(10).join(f"- {s}" for s in task.summary[-3:])}

{f"## Next Steps{chr(10)}{next_steps}" if next_steps else ""}
"""
            summaries.append(task_summary)

        combined_summary = "\n---\n".join(summaries)

        try:
            docs_result = self.docs_manager.update_after_task(
                task=last_task,
                success=last_success,
                changes_summary=combined_summary,
                workspace=self.project_root,
                step=self._current_step,
                parent_trace_id=self.trace_id,
                log_workspace=self.workspace,
            )

            self.docs_manager.ensure_readme_alignment(
                project_readme=self.project_root / "README.md",
                docs_directory=self.project_root / "docs",
                recent_task=last_task,
                success=last_success,
                logger=self.logger,
                step=self._current_step,
            )

            if docs_result.get("success"):
                updated = docs_result.get("updated_files", [])
                if updated:
                    console.print(
                        f"[dim]{self._timestamp()} [DOCS][/dim] Updated {len(updated)} files"
                    )
        except Exception as exc:
            console.print(f"[yellow]{self._timestamp()} [DOCS][/yellow] Failed: {exc}")

        # Reset tracking
        self._pending_docs_updates = []

    def _handle_actor_failure(self, task: Task, outcome: ActorOutcome) -> None:
        summary = outcome.error or "Subagent failed unexpectedly."
        task.summary.append(f"Attempt {task.attempt_count}: {summary}")
        task.next_action = summary
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
