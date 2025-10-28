"""Reviewer agent wrapper."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import json
import re

from ..models import Task
from .subagent import Subagent
from .logger import EventLogger
from .. import __version__


@dataclass
class ReviewFeedback:
    status: str
    summary: str
    next_steps: Optional[str]
    raw_output: str
    suggestions: Optional[List[str]] = None


def _build_reviewer_task_description(task: Task, test_feedback: List[Dict[str, Any]]) -> str:
    """Create reviewer instructions."""
    tests_section = "No automated tests were executed."
    if test_feedback:
        total = len(test_feedback)
        failures = [r for r in test_feedback if not r["passed"]]
        summary_line = f"{total - len(failures)}/{total} checks passed."
        lines = [summary_line]
        for result in failures[:3]:
            lines.append(
                f"- [FAIL] {result['description']}\n  Message: {result['message']}"
            )
            if result.get("stdout"):
                lines.append(f"  Stdout: {result['stdout'][:180]}")
            if result.get("stderr"):
                lines.append(f"  Stderr: {result['stderr'][:180]}")
        if len(failures) > 3:
            lines.append(f"- ... {len(failures) - 3} additional failures omitted")
        tests_section = "\n".join(lines)

    return f"""You are the project reviewer. Reflect on the delivered work and provide actionable feedback.

## Task Summary
- ID: {task.id}
- Title: {task.title}
- Description: {task.description}
- Attempts: {task.attempt_count}/{task.max_attempts}

## Acceptance Criteria
{chr(10).join(f'- {check.description}' for check in task.acceptance_criteria[:4]) or '- None'}
{"\n- ..." if len(task.acceptance_criteria) > 4 else ''}

## Automated Test Results
{tests_section}

## Instructions
1. Summarize whether the task meets the requirements.
2. Highlight any remaining gaps or risks.
3. Recommend concrete next steps if work is incomplete.

Respond with a JSON object in a markdown code block using this shape:
```json
{{
  "status": "PASS | FAIL | NEEDS_FOLLOWUP",
  "summary": "Concise verdict (max 2 sentences).",
  "next_steps": "Follow-up actions if status != PASS",
  "suggestions": ["Optional bullet", "Additional notes"]
}}
```
"""


def _extract_json_block(raw_output: str) -> Optional[Dict[str, Any]]:
    """Find and parse the last JSON block in a markdown-formatted string."""
    if not raw_output:
        return None

    code_blocks = re.findall(r"```json\s*([\s\S]*?)```", raw_output, flags=re.IGNORECASE)
    candidates = code_blocks if code_blocks else [raw_output]

    for snippet in reversed(candidates):
        snippet = snippet.strip()
        if not snippet:
            continue
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            continue
    return None


class Reviewer:
    """Drive reviewer subagent and parse structured feedback."""

    def __init__(self, project_root: Path, logger: EventLogger):
        self.project_root = Path(project_root).resolve()
        self.logger = logger

    def review(
        self,
        task: Task,
        test_feedback: List[Dict[str, Any]],
        workspace_context: str,
        step: int,
        trace_id: str,
        parent_trace_id: str,
    ) -> ReviewFeedback:
        """Invoke reviewer agent and parse response."""
        task_description = _build_reviewer_task_description(task, test_feedback)

        agent = Subagent(
            task_id=f"review-{task.id}",
            task_description=task_description,
            context=workspace_context,
            parent_trace_id=parent_trace_id,
            logger=self.logger,
            step=step,
            workspace=self.project_root,
            max_turns=16,
            model="haiku",
        )

        result = agent.execute()

        raw_output = result.get("output", "") if isinstance(result, dict) else ""

        parsed_block: Dict[str, Any] = {}
        if isinstance(result, dict):
            raw_parsed = result.get("parsed_result")
            if isinstance(raw_parsed, dict):
                parsed_block = raw_parsed

        if not parsed_block:
            parsed_block = _extract_json_block(raw_output) or {}

        status = parsed_block.get("status") or parsed_block.get("STATUS") or "NEEDS_FOLLOWUP"

        summary = parsed_block.get("summary")
        next_steps = parsed_block.get("next_steps") if isinstance(parsed_block.get("next_steps"), str) else None
        suggestions = parsed_block.get("suggestions")

        if not summary:
            if raw_output and "error_max_turns" in raw_output:
                summary = "Reviewer hit max turns before providing feedback."
                next_steps = next_steps or "Retry the review with tighter prompt or fewer context details."
            elif raw_output:
                summary = raw_output[:200]
            else:
                summary = "Reviewer response unavailable."

        return ReviewFeedback(
            status=str(status).upper(),
            summary=summary,
            next_steps=next_steps,
            suggestions=suggestions if isinstance(suggestions, list) else None,
            raw_output=raw_output,
        )
