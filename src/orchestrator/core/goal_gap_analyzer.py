"""Analyze unmet goals and generate tasks to address the gap.

When all tasks complete but goals remain unachieved, this analyzer
identifies what's missing and generates new tasks to close the gap.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Dict, Any

from rich.console import Console

from ..models import Goal, Task, TaskStatus, VerificationCheck
from ..planning.tasks import TaskGraph
from .logger import EventLogger
from .subagent import Subagent

console = Console()


class GoalGapAnalyzer:
    """Analyzes gaps between completed tasks and unmet goals.

    Called when all tasks are complete/failed but core goals remain unachieved.
    Uses a planning subagent to generate new tasks that address the gap.
    """

    def __init__(
        self,
        project_root: Path,
        logger: EventLogger,
        log_workspace: Path,
        max_new_tasks: int = 5,
    ):
        self.project_root = Path(project_root).resolve()
        self.logger = logger
        self.log_workspace = Path(log_workspace).resolve()
        self.max_new_tasks = max_new_tasks

    def analyze_and_generate(
        self,
        unmet_goals: List[Goal],
        completed_tasks: List[Task],
        failed_tasks: List[Task],
        task_graph: TaskGraph,
        step: int,
        trace_id: str,
    ) -> List[Task]:
        """Analyze the gap between unmet goals and completed work.

        Returns:
            List of new Task objects to address the gap (may be empty if
            the analyzer determines no additional tasks can help).
        """
        if not unmet_goals:
            return []

        console.print(
            f"[cyan]GoalGapAnalyzer[/cyan] Analyzing gap for {len(unmet_goals)} unmet goals"
        )
        console.print(
            f"[dim]GoalGapAnalyzer[/dim] Context: {len(completed_tasks)} completed, "
            f"{len(failed_tasks)} failed tasks"
        )

        prompt = self._build_prompt(unmet_goals, completed_tasks, failed_tasks)
        context = self._build_context(unmet_goals, completed_tasks, failed_tasks)

        agent = Subagent(
            task_id=f"goal-gap-{step}",
            task_description=prompt,
            context=context,
            parent_trace_id=trace_id,
            logger=self.logger,
            step=step,
            workspace=self.project_root,
            max_turns=20,  # Enough turns for exploration + JSON output
            model="sonnet",
            log_workspace=self.log_workspace,
        )

        result = agent.execute()
        status = result.get("status", "").lower()

        if status != "success":
            console.print(
                f"[yellow]GoalGapAnalyzer[/yellow] Unable to generate tasks: "
                f"{result.get('error') or result.get('summary')}"
            )
            return []

        raw_output = result.get("output", "")

        # Debug logging
        console.print(
            f"[dim]GoalGapAnalyzer[/dim] Subagent returned {len(raw_output)} chars"
        )

        # Extract actual content from nested structure if present
        # The output may be a Python string repr of a dict with 'result' key
        actual_content = self._extract_content(raw_output)

        proposals = self._parse_task_proposals(actual_content)

        if not proposals:
            console.print("[yellow]GoalGapAnalyzer[/yellow] No viable tasks proposed")
            # Log a snippet of the output for debugging
            snippet = raw_output[:500] if raw_output else "(empty)"
            console.print(f"[dim]GoalGapAnalyzer[/dim] Output snippet: {snippet}...")
            return []

        new_tasks: List[Task] = []
        for payload in proposals[: self.max_new_tasks]:
            task = self._build_task_from_payload(payload, unmet_goals)
            new_tasks.append(task)

        console.print(
            f"[green]GoalGapAnalyzer[/green] Generated {len(new_tasks)} new tasks"
        )
        return new_tasks

    def _build_prompt(
        self,
        unmet_goals: List[Goal],
        completed_tasks: List[Task],
        failed_tasks: List[Task],
    ) -> str:
        goals_text = "\n".join(
            f"- **{g.id}**: {g.description}\n  Measurable: {g.measurable_criteria}"
            for g in unmet_goals
        )

        completed_text = "\n".join(
            f"- {t.id}: {t.title}"
            for t in completed_tasks[-15:]  # Last 15 completed
        )

        failed_text = (
            "\n".join(
                f"- {t.id}: {t.title} (attempts: {t.attempt_count})"
                for t in failed_tasks[-5:]  # Last 5 failed
            )
            if failed_tasks
            else "None"
        )

        return f"""You are the Goal Gap Analyzer. All planned tasks have been attempted, but some goals remain unmet.

## CRITICAL: OUTPUT JSON IMMEDIATELY

You have limited turns. Your FIRST priority is generating the JSON task array.

## Unmet Goals
{goals_text}

## Previously Completed Tasks
{completed_text}

## Failed Tasks
{failed_text}

## Your Process (BE EFFICIENT)

1. **Quick scan only**: Spend at most 2-3 turns checking key files if needed
2. **Generate tasks immediately**: Based on what you know, output the JSON

## Task Generation Rules

- You MUST output at least 1 task - the orchestrator needs tasks to proceed
- Focus on VERIFICATION tasks if work might be done but not confirmed
- For quantitative gaps (word count, sources), create specific tasks to close them
- Tasks must be concrete with clear acceptance criteria

## REQUIRED OUTPUT FORMAT

Output this JSON array (1-5 tasks):
```json
[
  {{
    "title": "Specific task title",
    "description": "Detailed description of what must be done",
    "priority": 9,
    "related_goals": ["goal-xxx"],
    "acceptance": [
      {{
        "type": "file_exists",
        "target": "path/to/expected/output",
        "description": "Output file is generated"
      }}
    ]
  }}
]
```

DO NOT spend many turns exploring. Output the JSON quickly based on the goal requirements you can see above.
"""

    def _build_context(
        self,
        unmet_goals: List[Goal],
        completed_tasks: List[Task],
        failed_tasks: List[Task],
    ) -> str:
        lines = [
            "## Goal Gap Analysis Context",
            "",
            f"Unmet goals: {len(unmet_goals)}",
            f"Completed tasks: {len(completed_tasks)}",
            f"Failed tasks: {len(failed_tasks)}",
            "",
        ]

        # Include summaries from completed tasks for context
        if completed_tasks:
            lines.append("## What Was Done (Task Summaries)")
            for task in completed_tasks[-10:]:
                if task.summary:
                    lines.append(f"\n### {task.title}")
                    lines.extend(f"- {s}" for s in task.summary[-2:])

        # Include failure reasons
        if failed_tasks:
            lines.append("\n## What Failed")
            for task in failed_tasks[-5:]:
                lines.append(f"\n### {task.title}")
                if task.review_feedback:
                    lines.append(f"Feedback: {task.review_feedback[-1]}")

        return "\n".join(lines)

    def _extract_content(self, raw_output: str) -> str:
        """Extract actual content from nested Claude output structure.

        The subagent may return output in the form of a Python dict repr like:
        "{'type': 'result', 'result': 'actual content with ```json blocks```'}"

        This method attempts to extract the 'result' field if present.
        """
        if not raw_output:
            return ""

        # If output directly contains JSON blocks at the top level, use as-is
        if raw_output.strip().startswith("Now") or raw_output.strip().startswith("##"):
            return raw_output

        # Try to parse as Python literal and extract result
        # This handles the case where output is like:
        # "{'type': 'result', 'result': 'content...', ...}"
        try:
            import ast

            parsed = ast.literal_eval(raw_output)
            if isinstance(parsed, dict) and "result" in parsed:
                extracted = parsed["result"]
                console.print(
                    f"[dim]GoalGapAnalyzer[/dim] Extracted nested result: "
                    f"{len(extracted)} chars"
                )
                return extracted
        except (ValueError, SyntaxError):
            pass

        # If output looks like it contains a nested 'result' field, extract via regex
        # This is a fallback for malformed Python literals
        result_match = re.search(
            r"['\"]result['\"]:\s*['\"](.+?)['\"],\s*['\"]session_id",
            raw_output,
            re.DOTALL,
        )
        if result_match:
            extracted = result_match.group(1)
            # Handle escaped newlines and quotes
            extracted = extracted.replace("\\n", "\n").replace("\\'", "'")
            console.print(
                f"[dim]GoalGapAnalyzer[/dim] Extracted via regex: {len(extracted)} chars"
            )
            return extracted

        # Fallback: return as-is
        return raw_output

    def _parse_task_proposals(self, output: str) -> List[Dict[str, Any]]:
        """Extract JSON array of task proposals from agent output."""
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
                    # Filter out empty arrays that indicate "no tasks possible"
                    if len(data) == 0:
                        return []
                    return [item for item in data if isinstance(item, dict)]
            except json.JSONDecodeError:
                continue
        return []

    def _build_task_from_payload(
        self, payload: Dict[str, Any], unmet_goals: List[Goal]
    ) -> Task:
        """Convert JSON payload to Task model."""
        title = payload.get("title", "Goal gap remediation task")
        description = payload.get("description", title)
        priority = int(payload.get("priority", 8))  # Default high priority
        related_goals = payload.get("related_goals", [])

        # If no related goals specified, link to all unmet goals
        if not related_goals:
            related_goals = [g.id for g in unmet_goals]

        acceptance_checks = []
        for check in payload.get("acceptance", []):
            if not isinstance(check, dict):
                continue
            try:
                acceptance_checks.append(
                    VerificationCheck(
                        type=check.get("type", "file_exists"),
                        target=check.get("target", ""),
                        description=check.get("description", "Goal gap verification"),
                        expected=check.get("expected"),
                        timeout=check.get("timeout"),
                        metadata=check.get("metadata") or {},
                    )
                )
            except Exception:
                continue

        return Task(
            title=title,
            description=description,
            priority=max(1, min(10, priority)),
            related_goals=related_goals,
            acceptance_criteria=acceptance_checks,
            status=TaskStatus.BACKLOG,
        )
