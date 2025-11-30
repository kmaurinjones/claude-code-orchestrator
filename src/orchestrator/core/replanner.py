"""Generate remediation tasks when work fails."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Any, Dict

from rich.console import Console

from ..models import Task, TaskStatus, VerificationCheck
from .logger import EventLogger
from .subagent import Subagent
from .tester import TestResult
from .reviewer import ReviewFeedback

console = Console()


class Replanner:
    """Analyzes failed tasks and proposes follow-up remediation work."""

    def __init__(
        self,
        project_root: Path,
        logger: EventLogger,
        log_workspace: Path,
        max_tasks: int = 3,
    ):
        self.project_root = Path(project_root).resolve()
        self.logger = logger
        self.max_tasks = max_tasks
        self.log_workspace = Path(log_workspace).resolve()

    def analyze_failure(
        self,
        failed_task: Task,
        review_feedback: ReviewFeedback,
        test_results: List[TestResult],
        step: int,
    ) -> List[Task]:
        """
        Use a planning subagent to generate remediation tasks.

        Returns:
            List of Task objects (may be empty) describing remediation work.
        """
        prompt = self._build_prompt(failed_task, review_feedback, test_results)

        agent = Subagent(
            task_id=f"replan-{failed_task.id}",
            task_description=prompt,
            context=self._build_context(failed_task, test_results),
            parent_trace_id=f"replan-{failed_task.id}",
            logger=self.logger,
            step=step,
            workspace=self.project_root,
            max_turns=12,
            model="sonnet",
            log_workspace=self.log_workspace,
        )

        result = agent.execute()
        status = result.get("status", "").lower()
        if status != "success":
            console.print(
                f"[yellow]Replanner[/yellow] Unable to generate remediation tasks: "
                f"{result.get('error') or result.get('summary')}"
            )
            return []

        raw_output = result.get("output", "")
        proposals = self._parse_task_proposals(raw_output)
        if not proposals:
            return []

        remediation_tasks: List[Task] = []
        for payload in proposals[: self.max_tasks]:
            task = self._build_task_from_payload(payload, failed_task)
            remediation_tasks.append(task)

        return remediation_tasks

    def _build_context(self, failed_task: Task, test_results: List[TestResult]) -> str:
        """Build context summary for the replanner subagent."""
        lines = [
            "## Failed Task Context",
            f"- ID: {failed_task.id}",
            f"- Title: {failed_task.title}",
            f"- Attempts: {failed_task.attempt_count}/{failed_task.max_attempts}",
            f"- Status: {failed_task.status.value}",
        ]

        if failed_task.summary:
            lines.append("\n### Recent Summaries")
            lines.extend(f"- {entry}" for entry in failed_task.summary[-3:])

        if test_results:
            lines.append("\n### Test Results")
            for result in test_results:
                status = "PASS" if result.passed else "FAIL"
                lines.append(
                    f"- [{status}] {result.check.description} :: {result.message}"
                )

        return "\n".join(lines)

    def _build_prompt(
        self,
        failed_task: Task,
        review_feedback: ReviewFeedback,
        test_results: List[TestResult],
    ) -> str:
        failed_tests = len([t for t in test_results if not t.passed])
        total_tests = len(test_results)

        return f"""You are the replanner. A task failed and needs remediation.

## Failed Task
- ID: {failed_task.id}
- Title: {failed_task.title}
- Attempts: {failed_task.attempt_count}
- Review: {review_feedback.summary}
- Reviewer Status: {review_feedback.status}
- Test Failures: {failed_tests}/{total_tests}

## Analysis Needed
1. Why did this fail?
2. What follow-up tasks would fix it?
3. Should we try a different approach?

Generate 1-3 focused remediation tasks. Make them specific and actionable.

Respond with a JSON array of task definitions:
```json
[
  {{
    "title": "Fix failing integration test",
    "description": "Describe exactly what must be done",
    "priority": 8,
    "depends_on": ["{failed_task.id}"],
    "acceptance": [
      {{
        "type": "command_passes",
        "target": "pytest tests/test_integration.py",
        "description": "Integration tests pass"
      }}
    ]
  }}
]
```
"""

    def _parse_task_proposals(self, output: str) -> List[Dict[str, Any]]:
        """Extract JSON array of remediation tasks from agent output."""
        code_blocks = re.findall(
            r"```json\s*([\s\S]*?)```", output, flags=re.IGNORECASE
        )
        candidates = code_blocks if code_blocks else [output]

        for snippet in reversed(candidates):
            snippet = snippet.strip()
            if not snippet:
                continue
            try:
                data = json.loads(snippet)
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)]
            except json.JSONDecodeError:
                continue
        return []

    def _build_task_from_payload(
        self, payload: Dict[str, Any], failed_task: Task
    ) -> Task:
        """Convert JSON payload to Task model."""
        title = payload.get("title") or f"Remediate {failed_task.title}"
        description = payload.get("description") or title
        priority = int(payload.get("priority", min(10, failed_task.priority)))
        depends_on = payload.get("depends_on") or [failed_task.id]

        acceptance_checks = []
        for check in payload.get("acceptance", []):
            if not isinstance(check, dict):
                continue
            try:
                acceptance_checks.append(
                    VerificationCheck(
                        type=check.get("type", "command_passes"),
                        target=check.get("target", ""),
                        description=check.get(
                            "description", "Remediation verification"
                        ),
                        expected=check.get("expected"),
                        timeout=check.get("timeout"),
                        metadata=check.get("metadata") or {},
                    )
                )
            except Exception:
                # Skip malformed checks but continue processing others
                continue

        return Task(
            title=title,
            description=description,
            priority=max(1, min(10, priority)),
            depends_on=[dep for dep in depends_on if dep],
            acceptance_criteria=acceptance_checks,
            status=TaskStatus.BACKLOG,
        )
