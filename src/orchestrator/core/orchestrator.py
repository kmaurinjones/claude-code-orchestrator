"""Main orchestrator logic with task, tester, and reviewer agents."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4
from datetime import datetime

from rich.console import Console

from .. import __version__
from ..models import EventType, TaskStatus, Task
from ..planning.goals import GoalsManager
from ..planning.tasks import TaskGraph
from .logger import EventLogger
from .subagent import Subagent
from .tester import Tester, TestResult
from .reviewer import Reviewer, ReviewFeedback

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

            task = self._get_next_task()
            if not task:
                console.print(f"[yellow]{_timestamp()} [ORCHESTRATOR][/yellow] No ready tasks remaining")
                return "NO_TASKS_AVAILABLE"

            self._process_task(task)

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

        while task.attempt_count < task.max_attempts:
            task.attempt_count += 1
            self.current_step += 1

            console.print(f"[blue]{_timestamp()} [TASK][/blue] {task.id} attempt {task.attempt_count}/{task.max_attempts}")
            self._log_checkpoint(
                "execute_task",
                {
                    "task_id": task.id,
                    "task_title": task.title,
                    "attempt": task.attempt_count,
                    "max_attempts": task.max_attempts,
                },
            )

            agent_result = self._run_task_agent(task)
            if agent_result.get("status") not in {"success", "SUCCESS"}:
                self._handle_agent_failure(task, agent_result)
                continue

            test_results = self._run_tests(task)
            review_feedback = self._run_reviewer(task, test_results)
            self._record_feedback(task, test_results, review_feedback)

            if self._task_succeeded(test_results, review_feedback):
                task.status = TaskStatus.COMPLETE
                task.summary.append(review_feedback.summary[:200])
                task.next_action = None
                console.print(f"[green]{_timestamp()} [SUCCESS][/green] ✓ {task.id} accepted by reviewer")
                break

            task.summary.append(review_feedback.summary[:200])
            fallback_next = f"Review feedback: {review_feedback.summary}"[:200]
            task.next_action = review_feedback.next_steps or fallback_next
            console.print(f"[yellow]{_timestamp()} [REWORK][/yellow] {task.id} requires changes: {task.next_action}")

        if task.status != TaskStatus.COMPLETE:
            task.status = TaskStatus.FAILED
            console.print(f"[red]{_timestamp()} [FAILED][/red] ✗ {task.id} exhausted attempts")

        self.tasks.save()

    # --------------------------------------------------------------------- #
    # Agent interactions                                                    #
    # --------------------------------------------------------------------- #

    def _run_task_agent(self, task: Task) -> Dict[str, str]:
        prompt = self._build_task_agent_prompt(task)
        agent = Subagent(
            task_id=task.id,
            task_description=prompt,
            context=self._gather_context(task),
            parent_trace_id=self.trace_id,
            logger=self.logger,
            step=self.current_step,
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

    def _run_reviewer(self, task: Task, tests: List[TestResult]) -> ReviewFeedback:
        console.print(f"[cyan]{_timestamp()} [REVIEW][/cyan] Requesting review for {task.id}")
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
            step=self.current_step,
            trace_id=f"review-{uuid4().hex[:8]}",
            parent_trace_id=self.trace_id,
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

    # --------------------------------------------------------------------- #
    # Decision helpers                                                      #
    # --------------------------------------------------------------------- #

    def _task_succeeded(self, tests: List[TestResult], feedback: ReviewFeedback) -> bool:
        tests_ok = all(res.passed for res in tests)
        return feedback.status in {"PASS", "SUCCESS"} and tests_ok

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
        }
        self.feedback_log.append(entry)
        task.review_feedback.append(review.summary[:200])
        if review.suggestions:
            task.review_feedback.extend(review.suggestions)

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

Respond with the mandatory JSON block when finished."""

    def _gather_context(self, task: Task) -> str:
        lines: List[str] = []
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

        return "\n".join(lines)

    def _build_reviewer_context(self, task: Task) -> str:
        lines: List[str] = []
        lines.append("### Project Snapshot")
        for goal in self.goals.core_goals[:2]:
            status = "ACHIEVED" if goal.achieved else f"PENDING ({goal.confidence:.2f})"
            lines.append(f"- {goal.description} [{status}]")

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

    def _log_checkpoint(self, action: str, payload: Dict[str, object]) -> None:
        self.logger.log(
            event_type=EventType.CHECKPOINT,
            actor="orchestrator",
            payload={"action": action, **payload},
            trace_id=self.trace_id,
            step=self.current_step,
            version=__version__,
        )

    def _check_completion(self) -> bool:
        return all(goal.achieved for goal in self.goals.core_goals)

    def _all_tasks_complete(self) -> bool:
        for task in self.tasks._tasks.values():
            if task.status in {TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS}:
                return False
        return True
