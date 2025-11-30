"""Actor wraps the implementation agent plus deterministic acceptance checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from rich.console import Console

from ..models import Task
from .contracts import ActorOutcome, ActorStatus, PlanDecision
from .context import build_actor_workspace_context, build_task_agent_prompt
from .logger import EventLogger
from .subagent import Subagent
from .tester import TestResult, Tester

console = Console()


class Actor:
    """Executes planner decisions by delegating to the Claude subagent + testers."""

    def __init__(
        self,
        project_root: Path,
        workspace: Path,
        tester: Tester,
        logger: EventLogger,
        trace_id: str,
        max_turns: int = 12,
        model: str = "sonnet",
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.workspace = Path(workspace).resolve()
        self.tester = tester
        self.logger = logger
        self.trace_id = trace_id
        self.max_turns = max_turns
        self.model = model

    def execute(self, decision: PlanDecision) -> ActorOutcome:
        """Run the subagent and deterministic tests for a single planner decision."""
        if decision.task is None:
            raise ValueError("Planner request missing task payload.")

        task = decision.task
        console.print(
            f"[cyan]{self._timestamp()} [ACTOR][/cyan] Executing {task.id} (attempt {decision.attempt})"
        )

        prompt = build_task_agent_prompt(task, decision.context)
        workspace_context = build_actor_workspace_context(
            task, decision.context, self.project_root
        )

        agent_result = self._run_subagent(
            task, prompt, workspace_context, decision.step
        )
        status = (agent_result.get("status") or "").lower()
        if status != "success":
            error_summary = agent_result.get("error") or agent_result.get("output", "")
            console.print(
                f"[yellow]{self._timestamp()} [ACTOR][/yellow] {task.id} subagent failed: {error_summary}"
            )
            return ActorOutcome(
                status=ActorStatus.ERROR,
                task=task,
                step=decision.step,
                attempt=decision.attempt,
                agent_result=agent_result,
                tests=[],
                error=error_summary,
            )

        tests = self._run_tests(task)
        return ActorOutcome(
            status=ActorStatus.SUCCESS,
            task=task,
            step=decision.step,
            attempt=decision.attempt,
            agent_result=agent_result,
            tests=tests,
        )

    def _run_subagent(
        self,
        task: Task,
        prompt: str,
        context: str,
        step: int,
    ) -> Dict[str, Any]:
        """Execute the Claude CLI subagent."""
        agent = Subagent(
            task_id=task.id,
            task_description=prompt,
            context=context,
            parent_trace_id=self.trace_id,
            logger=self.logger,
            step=step,
            workspace=self.project_root,
            max_turns=self.max_turns,
            model=self.model,
            log_workspace=self.workspace,
        )
        return agent.execute()

    def _run_tests(self, task: Task) -> List[TestResult]:
        """Execute deterministic acceptance criteria."""
        if not task.acceptance_criteria:
            return []

        console.print(
            f"[cyan]{self._timestamp()} [TESTER][/cyan] Verifying acceptance criteria for {task.id}"
        )
        results = self.tester.run(task)
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            console.print(
                f"[dim]{self._timestamp()} [TESTER][/dim] [{status}] {result.check.description}"
            )
        return results

    @staticmethod
    def _timestamp() -> str:
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d--%H-%M-%S")
