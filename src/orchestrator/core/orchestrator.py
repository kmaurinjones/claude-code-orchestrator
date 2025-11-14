"""Main orchestrator logic with task, tester, and reviewer agents."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set
from uuid import uuid4
from datetime import datetime
import threading

from rich.console import Console

from .. import __version__
from ..models import EventType, TaskStatus, Task
from ..planning.goals import GoalsManager
from ..planning.tasks import TaskGraph
from .logger import EventLogger
from .subagent import Subagent
from .tester import Tester, TestResult
from .reviewer import Reviewer, ReviewFeedback
from .notes import NotesManager
from .feedback import FeedbackTracker
from .parallel_executor import ParallelExecutor, get_ready_tasks_batch
from .replanner import Replanner
from .domain_context import DomainContext, DomainDetector
from .long_jobs import LongRunningJobManager
from .critic import Critic, CriticFeedback

console = Console()


def _timestamp() -> str:
    """Return timestamp in YYYY-MM-DD--HH-MM-SS format."""
    return datetime.now().strftime("%Y-%m-%d--%H-%M-%S")


class Orchestrator:
    """Co-ordinates task execution, testing, and review loops."""

    def __init__(
        self,
        workspace: Path = Path(".agentic"),
        min_steps: int = 50,
        max_steps: int = 100,
        max_parallel_tasks: int = 1,
        subagent_max_turns: int = 12,
        skip_integration_tests: bool = True,
        pytest_addopts: Optional[str] = None,
    ):
        self.workspace = workspace.resolve()
        self.project_root = self.workspace.parent

        if not self.workspace.is_absolute() or not self.project_root.is_absolute():
            raise ValueError("Workspace and project root must be absolute paths.")

        self.min_steps = min_steps
        self.max_steps = max_steps
        self.max_parallel_tasks = max_parallel_tasks
        self.subagent_max_turns = subagent_max_turns

        self.logger = EventLogger(self.workspace / "full_history.jsonl")
        self.goals = GoalsManager(self.workspace / "current" / "GOALS.md")
        self.tasks = TaskGraph(self.workspace / "current" / "TASKS.md")

        self.tester = Tester(self.project_root)
        self.reviewer = Reviewer(self.project_root, self.logger)
        self.notes_manager = NotesManager(self.workspace)
        self._latest_notes_summary = self.notes_manager.concise_summary()

        self.feedback_tracker = FeedbackTracker(self.workspace)
        self.feedback_tracker.initialize()

        # Import here to avoid linter removing unused imports
        from .changelog import ChangelogManager
        from .docs import DocsManager

        self.changelog_manager = ChangelogManager(self.project_root)
        self.changelog_manager.initialize()

        self.docs_manager = DocsManager(self.project_root, self.logger)
        self.docs_manager.initialize()

        self.parallel_executor = ParallelExecutor(max_parallel=self.max_parallel_tasks)
        self.replanner = Replanner(self.project_root, self.logger)
        self.long_jobs = LongRunningJobManager(self.workspace, self.project_root)
        self.critic = Critic(self.project_root)

        self._task_save_lock = threading.Lock()
        self._step_lock = threading.Lock()
        self._active_tasks: Set[str] = set()
        self._task_replan_depth: Dict[str, int] = {}
        self.max_replan_depth = 3

        for existing_task_id in self.tasks._tasks.keys():
            self._task_replan_depth.setdefault(existing_task_id, 0)

        self.current_step = 0
        self.trace_id = f"orch-{uuid4().hex[:8]}"
        self.feedback_log: List[Dict[str, str]] = []

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def run(self) -> str:
        console.print(f"[cyan]{_timestamp()} [ORCHESTRATOR][/cyan] Starting simplified execution loop")
        console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Min steps: {self.min_steps}")
        console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Max steps: {self.max_steps}")
        console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Max parallel tasks: {self.max_parallel_tasks}")
        console.print()

        self._log_checkpoint("start", {"max_steps": self.max_steps})

        while self.current_step < self.max_steps:
            console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Step {self.current_step}/{self.max_steps}")

            if self.current_step >= self.min_steps and self._check_completion():
                console.print(f"[green]{_timestamp()} [ORCHESTRATOR][/green] All core goals achieved")
                return "SUCCESS"

            self._latest_notes_summary = self.notes_manager.concise_summary()
            self.long_jobs.process_queue()
            self.long_jobs.poll()

            ready_tasks = get_ready_tasks_batch(
                self.tasks,
                max_count=self.max_parallel_tasks,
                exclude_ids=self._active_tasks,
            )

            if not ready_tasks:
                console.print(f"[yellow]{_timestamp()} [ORCHESTRATOR][/yellow] No ready tasks remaining")
                return "NO_TASKS_AVAILABLE"

            for task in ready_tasks:
                self._active_tasks.add(task.id)

            result = self.parallel_executor.execute_tasks_parallel(
                ready_tasks,
                process_func=self._process_task,
            )

            finished_ids = set(result["tasks"]["completed"]) | set(result["tasks"]["failed"])
            self._active_tasks.difference_update(finished_ids)

        console.print(f"[yellow]{_timestamp()} [ORCHESTRATOR][/yellow] Reached max iterations ({self.max_steps})")
        return "MAX_ITERATIONS_REACHED"

    # --------------------------------------------------------------------- #
    # Core loop helpers                                                     #
    # --------------------------------------------------------------------- #

    def _get_next_task(self) -> Optional[Task]:
        ready = self.tasks.get_ready_tasks()
        if not ready:
            return None
        # Highest priority first (already sorted)
        return ready[0]

    def _process_task(self, task: Task) -> None:
        console.print(f"[cyan]{_timestamp()} [ORCHESTRATOR][/cyan] Selected task: {task.id} ({task.title})")
        task.status = TaskStatus.IN_PROGRESS

        base_replan_depth = self._task_replan_depth.get(task.id, 0)
        last_review_feedback: Optional[ReviewFeedback] = None
        last_critic_feedback: Optional[CriticFeedback] = None
        last_test_results: List[TestResult] = []

        while task.attempt_count < task.max_attempts:
            task.attempt_count += 1
            attempt_step = self._next_step()

            console.print(
                f"[blue]{_timestamp()} [TASK][/blue] {task.id} attempt "
                f"{task.attempt_count}/{task.max_attempts}"
            )
            self._log_checkpoint(
                "execute_task",
                {
                    "task_id": task.id,
                    "task_title": task.title,
                    "attempt": task.attempt_count,
                    "max_attempts": task.max_attempts,
                },
                step_override=attempt_step,
            )

            agent_result = self._run_task_agent(task, attempt_step)
            if agent_result.get("status") not in {"success", "SUCCESS"}:
                self._handle_agent_failure(task, agent_result)
                continue

            self.long_jobs.wait_for_task_jobs(task.id)

            last_test_results = self._run_tests(task)
            last_review_feedback = self._run_reviewer(task, last_test_results, step=attempt_step)
            last_critic_feedback = self.critic.evaluate(task.id)
            self._record_feedback(task, last_test_results, last_review_feedback, last_critic_feedback)

            if last_critic_feedback and last_critic_feedback.summary:
                task.summary.append(last_critic_feedback.summary[:200])

            if self._task_succeeded(last_test_results, last_review_feedback, last_critic_feedback):
                task.status = TaskStatus.COMPLETE
                task.summary.append(last_review_feedback.summary[:200])
                task.next_action = None
                console.print(f"[green]{_timestamp()} [SUCCESS][/green] ✓ {task.id} accepted by reviewer")

                # Update documentation and changelog
                self._update_docs_and_changelog(task, last_review_feedback, success=True)

                break

            task.summary.append(last_review_feedback.summary[:200])
            fallback_next = f"Review feedback: {last_review_feedback.summary}"[:200]
            if last_critic_feedback and last_critic_feedback.status != "PASS":
                fallback_next = f"Critic feedback: {last_critic_feedback.summary}"[:200]
            task.next_action = (
                last_review_feedback.next_steps
                or (last_critic_feedback.summary if last_critic_feedback.status != "PASS" else None)
                or fallback_next
            )
            console.print(f"[yellow]{_timestamp()} [REWORK][/yellow] {task.id} requires changes: {task.next_action}")

        fallback_review = last_review_feedback or ReviewFeedback(
            status="FAIL",
            summary="Task failed before reviewer feedback was available.",
            next_steps="Retry with additional diagnostics.",
            raw_output="",
        )
        fallback_critic = last_critic_feedback or CriticFeedback(
            status="PASS",
            summary="Critic not executed.",
            findings=[],
        )

        if task.status != TaskStatus.COMPLETE:
            task.status = TaskStatus.FAILED
            console.print(f"[red]{_timestamp()} [FAILED][/red] ✗ {task.id} exhausted attempts")

            if last_critic_feedback and last_critic_feedback.status != "PASS":
                fallback_review.summary += f" | Critic: {last_critic_feedback.summary}"

            self._handle_replan(task, fallback_review, last_test_results, base_replan_depth)

            # Document the failure
            failure_review = fallback_review
            if fallback_critic.status != "PASS":
                failure_review.summary += f" | Critic: {fallback_critic.summary}"
            self._update_docs_and_changelog(task, failure_review, success=False)

        self._save_tasks()

    # --------------------------------------------------------------------- #
    # Agent interactions                                                    #
    # --------------------------------------------------------------------- #

    def _run_task_agent(self, task: Task, step: int) -> Dict[str, str]:
        prompt = self._build_task_agent_prompt(task)
        agent = Subagent(
            task_id=task.id,
            task_description=prompt,
            context=self._gather_context(task),
            parent_trace_id=self.trace_id,
            logger=self.logger,
            step=step,
            workspace=self.project_root,
            max_turns=self.subagent_max_turns,
            model="haiku",
        )
        return agent.execute()

    def _run_tests(self, task: Task) -> List[TestResult]:
        if not task.acceptance_criteria:
            return []

        console.print(f"[cyan]{_timestamp()} [TESTER][/cyan] Running acceptance checks for {task.id}")
        results = self.tester.run(task)

        for result in results:
            status = "PASS" if result.passed else "FAIL"
            console.print(f"[dim]{_timestamp()} [TESTER][/dim] [{status}] {result.check.description}")

        return results

    def _run_reviewer(self, task: Task, tests: List[TestResult], step: int) -> ReviewFeedback:
        console.print(f"[cyan]{_timestamp()} [REVIEW][/cyan] Requesting review for {task.id}")

        # Check for new user feedback
        user_feedback = []
        if self.feedback_tracker.has_new_feedback():
            user_feedback = self.feedback_tracker.consume_feedback()
            console.print(f"[yellow]{_timestamp()} [FEEDBACK][/yellow] Consumed {len(user_feedback)} user feedback entries")

        test_payload = [
            {
                "description": res.check.description,
                "type": res.check.type,
                "target": res.check.target,
                "passed": res.passed,
                "message": res.message,
                "stdout": res.stdout,
                "stderr": res.stderr,
            }
            for res in tests
        ]

        feedback = self.reviewer.review(
            task=task,
            test_feedback=test_payload,
            workspace_context=self._build_reviewer_context(task),
            step=step,
            trace_id=f"review-{uuid4().hex[:8]}",
            parent_trace_id=self.trace_id,
            notes_summary=self._latest_notes_summary,
            user_feedback=user_feedback,
            short_mode=False,
            retry_count=0,
        )

        if self._needs_reviewer_retry(feedback):
            console.print(
                f"[yellow]{_timestamp()} [REVIEW][/yellow] Initial review timed out - retrying with condensed prompt",
            )
            feedback = self.reviewer.review(
                task=task,
                test_feedback=test_payload,
                workspace_context=self._build_reviewer_context(task),
                step=step,
                trace_id=f"review-{uuid4().hex[:8]}",
                parent_trace_id=self.trace_id,
                notes_summary=self._latest_notes_summary,
                user_feedback=user_feedback,
                short_mode=True,
                retry_count=1,
            )

        if test_payload and all(item["passed"] for item in test_payload) and "max turns" in feedback.summary.lower():
            feedback.status = "PASS"
            feedback.summary = "Reviewer timed out, but all acceptance checks passed."
            if not feedback.next_steps:
                feedback.next_steps = "Proceed; reviewer hit max turns but tests are green."

        console.print(
            f"[dim]{_timestamp()} [REVIEW][/dim] Status: {feedback.status} | {feedback.summary}"
        )
        return feedback

    def _needs_reviewer_retry(self, feedback: ReviewFeedback) -> bool:
        summary_lower = feedback.summary.lower() if feedback.summary else ""
        raw_lower = feedback.raw_output.lower() if feedback.raw_output else ""
        timeout_markers = ["max turns", "timed out", "timeout", "error_max_turns"]
        return any(marker in summary_lower for marker in timeout_markers) or any(
            marker in raw_lower for marker in timeout_markers
        )

    # --------------------------------------------------------------------- #
    # Decision helpers                                                      #
    # --------------------------------------------------------------------- #

    def _task_succeeded(
        self,
        tests: List[TestResult],
        review: ReviewFeedback,
        critic: Optional[CriticFeedback],
    ) -> bool:
        tests_ok = all(res.passed for res in tests)
        critic_ok = critic is None or critic.status == "PASS"
        return review.status in {"PASS", "SUCCESS"} and tests_ok and critic_ok

    def _handle_agent_failure(self, task: Task, agent_result: Dict[str, str]) -> None:
        summary = agent_result.get("error") or agent_result.get("output", "")[:200]
        task.summary.append(f"Attempt {task.attempt_count}: Subagent failure")
        task.next_action = f"Previous attempt failed: {summary}"
        console.print(f"[yellow]{_timestamp()} [TASK][/yellow] {task.id} agent failed, retrying")

    def _record_feedback(
        self,
        task: Task,
        tests: List[TestResult],
        review: ReviewFeedback,
        critic: Optional[CriticFeedback] = None,
    ) -> None:
        entry = {
            "task_id": task.id,
            "attempt": task.attempt_count,
            "review_status": review.status,
            "review_summary": review.summary,
            "tests": [
                {
                    "description": res.check.description,
                    "passed": res.passed,
                    "message": res.message,
                }
                for res in tests
            ],
            "next_steps": review.next_steps or review.summary,
            "critic": {
                "status": critic.status,
                "summary": critic.summary,
                "findings": critic.findings,
            }
            if critic
            else None,
        }
        self.feedback_log.append(entry)
        task.review_feedback.append(review.summary[:200])
        if review.suggestions:
            task.review_feedback.extend(review.suggestions)
        if critic and critic.summary:
            task.critic_feedback.append(critic.summary[:200])

    def _handle_replan(
        self,
        task: Task,
        review_feedback: ReviewFeedback,
        test_results: List[TestResult],
        base_replan_depth: int,
    ) -> None:
        """Generate remediation tasks when a task fails."""
        if base_replan_depth >= self.max_replan_depth:
            console.print(
                f"[dim]{_timestamp()} [REPLAN][/dim] "
                f"Skipping replan for {task.id}; max depth reached."
            )
            self.logger.log(
                event_type=EventType.REPLAN_REJECTED,
                actor="orchestrator",
                payload={
                    "task_id": task.id,
                    "reason": "max_depth_reached",
                    "depth": base_replan_depth,
                },
                trace_id=self.trace_id,
                step=self.current_step,
                version=__version__,
            )
            return

        remediation_tasks = self.replanner.analyze_failure(
            failed_task=task,
            review_feedback=review_feedback,
            test_results=test_results,
            step=self.current_step,
        )

        if not remediation_tasks:
            self.logger.log(
                event_type=EventType.REPLAN_REJECTED,
                actor="orchestrator",
                payload={
                    "task_id": task.id,
                    "reason": "no_remediation_tasks_generated",
                },
                trace_id=self.trace_id,
                step=self.current_step,
                version=__version__,
            )
            return

        console.print(
            f"[yellow]{_timestamp()} [REPLAN][/yellow] "
            f"Generated {len(remediation_tasks)} remediation task(s) from {task.id}"
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
                actor="orchestrator",
                payload={
                    "original_task": task.id,
                    "new_task": new_task.id,
                    "reason": "failure_remediation",
                },
                trace_id=self.trace_id,
                step=self.current_step,
                version=__version__,
            )

    def _update_docs_and_changelog(
        self,
        task: Task,
        review: ReviewFeedback,
        success: bool,
    ) -> None:
        """Update documentation and changelog after task completion or failure."""
        from .changelog import ChangeType

        console.print(f"[cyan]{_timestamp()} [DOCS][/cyan] Updating documentation and changelog for {task.id}")

        # Determine change type and description
        if success:
            # Infer change type from task title/description
            title_lower = task.title.lower()
            if "fix" in title_lower or "bug" in title_lower:
                change_type = ChangeType.FIXED
                desc = f"Fixed: {task.title}"
            elif "add" in title_lower or "implement" in title_lower or "create" in title_lower:
                change_type = ChangeType.ADDED
                desc = f"Added: {task.title}"
            elif "update" in title_lower or "change" in title_lower or "modify" in title_lower:
                change_type = ChangeType.CHANGED
                desc = f"Changed: {task.title}"
            elif "remove" in title_lower or "delete" in title_lower:
                change_type = ChangeType.REMOVED
                desc = f"Removed: {task.title}"
            else:
                change_type = ChangeType.CHANGED
                desc = task.title
        else:
            # Task failed - document attempt
            change_type = ChangeType.ATTEMPTED
            desc = f"Attempted {task.title} (failed after {task.attempt_count} attempts)"

        # Add to changelog
        try:
            version = self.changelog_manager.add_entry(
                change_type=change_type,
                description=desc,
                task_id=task.id,
            )
            console.print(f"[dim]{_timestamp()} [DOCS][/dim] Added changelog entry: {version}")
        except Exception as e:
            console.print(f"[yellow]{_timestamp()} [DOCS][/yellow] Failed to update changelog: {e}")

        # Update documentation
        try:
            changes_summary = f"""
## Task: {task.title}
**Status**: {'✓ SUCCESS' if success else '✗ FAILED'}
**Review**: {review.summary}

## Summary
{chr(10).join(f'- {s}' for s in task.summary[-3:])}

{f"## Next Steps{chr(10)}{review.next_steps}" if review.next_steps else ''}
"""

            docs_result = self.docs_manager.update_after_task(
                task=task,
                success=success,
                changes_summary=changes_summary,
                workspace=self.workspace,
                step=self.current_step,
                parent_trace_id=self.trace_id,
            )

            if docs_result.get("success"):
                updated = docs_result.get("updated_files", [])
                if updated:
                    console.print(f"[dim]{_timestamp()} [DOCS][/dim] Updated {len(updated)} doc files")
            else:
                console.print(f"[yellow]{_timestamp()} [DOCS][/yellow] Documentation update had issues")

        except Exception as e:
            console.print(f"[yellow]{_timestamp()} [DOCS][/yellow] Failed to update docs: {e}")

    # --------------------------------------------------------------------- #
    # Utility functions                                                     #
    # --------------------------------------------------------------------- #

    def _build_task_agent_prompt(self, task: Task) -> str:
        return f"""You are the implementation agent for {task.id}.

## Objective
{task.description}

## Acceptance Criteria
{chr(10).join(f'- {check.description} ({check.type}:{check.target})' for check in task.acceptance_criteria) or '- None provided'}

## Guidelines
- Work incrementally and keep changes minimal but functional.
- Document any limitations directly in code comments where relevant.
- Avoid running slow external services unless required.
- Always review the Operator Notes section for priority guidance before acting.
- **Commands expected to run >2 minutes _must_ use the experiment runner**:
  ```
  python -m orchestrator.tools.run_script --cmd "pytest -m slow" --run-name "slow-suite" --task-id "{task.id}" --mode enqueue
  ```
  This hands the job off to the orchestrator so Claude is free to continue; the orchestrator waits for completion,
  captures logs in `.agentic/history/logs/`, and appends metrics/artifacts to `.agentic/history/experiments.jsonl`.
- Blocking commands can still use `--mode blocking` when they finish quickly. The enqueue mode is preferred for
  model training, full test suites, migrations, builds, and heavy data processing.

Respond with the mandatory JSON block when finished."""

    def _gather_context(self, task: Task) -> str:
        lines: List[str] = []
        lines.append("### Operator Notes")
        lines.append(self.notes_manager.concise_summary())
        lines.append("")

        lines.append("### Project Goals")
        for goal in self.goals.core_goals:
            status = "ACHIEVED" if goal.achieved else f"PENDING ({goal.confidence:.2f})"
            lines.append(f"- {goal.description} [{status}]")

        lines.append("\n### Recent Feedback")
        recent = self.feedback_log[-5:]
        if not recent:
            lines.append("- None yet")
        else:
            for item in recent:
                lines.append(
                    f"- {item['task_id']} attempt {item['attempt']}: "
                    f"{item['review_status']} – {item['review_summary']}"
                )

        if task.summary:
            lines.append("\n### Task History")
            for summary in task.summary[-3:]:
                lines.append(f"- {summary}")

        if task.next_action:
            lines.append(f"\n### Requested Next Action\n- {task.next_action}")

        domain = DomainDetector.detect(self.project_root, self.goals.core_goals)
        domain_context = DomainContext.build(domain, self.project_root)
        if domain_context:
            pretty_domain = domain.replace("_", " ").title()
            lines.append(f"\n### Domain Guidance ({pretty_domain})")
            lines.append(domain_context)

        return "\n".join(lines)

    def _build_reviewer_context(self, task: Task) -> str:
        lines: List[str] = []
        lines.append("### Project Snapshot")
        for goal in self.goals.core_goals[:2]:
            status = "ACHIEVED" if goal.achieved else f"PENDING ({goal.confidence:.2f})"
            lines.append(f"- {goal.description} [{status}]")

        lines.append("\n### Operator Notes")
        lines.append(self._latest_notes_summary if hasattr(self, "_latest_notes_summary") else self.notes_manager.concise_summary())

        recent_feedback = self.feedback_log[-2:]
        if recent_feedback:
            lines.append("\n### Recent Reviewer Notes")
            for item in recent_feedback:
                lines.append(
                    f"- {item['task_id']} attempt {item['attempt']}: {item['review_status']} – {item['review_summary']}"
                )

        if task.summary:
            lines.append("\n### Latest Task Summary")
            lines.append(f"- {task.summary[-1]}")

        if task.next_action:
            lines.append("\n### Requested Next Action")
            lines.append(f"- {task.next_action}")

        return "\n".join(lines)

    def _next_step(self) -> int:
        """Atomically increment and return the current step counter."""
        with self._step_lock:
            self.current_step += 1
            return self.current_step

    def _save_tasks(self) -> None:
        """Persist TASKS.md updates with locking for parallel runs."""
        with self._task_save_lock:
            self.tasks.save()

    def _log_checkpoint(self, action: str, payload: Dict[str, object], step_override: Optional[int] = None) -> None:
        self.logger.log(
            event_type=EventType.CHECKPOINT,
            actor="orchestrator",
            payload={"action": action, **payload},
            trace_id=self.trace_id,
            step=step_override if step_override is not None else self.current_step,
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
