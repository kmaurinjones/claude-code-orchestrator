"""Helpers for building prompts and workspace context for each role."""

from __future__ import annotations

from pathlib import Path
from typing import List

from ..models import Goal, Task
from .contracts import PlanContext
from .domain_context import DomainContext


def _format_goal_line(goal: Goal) -> str:
    status = "ACHIEVED" if goal.achieved else f"PENDING ({goal.confidence:.2f})"
    return f"- {goal.description} [{status}]"


def build_task_agent_prompt(task: Task, plan_context: PlanContext) -> str:
    """Return the implementation instructions for the actor."""
    feedback_section = ""
    if plan_context.user_feedback:
        feedback_lines = [
            f"- [{'general' if entry.is_general else entry.task_id}] {entry.content}"
            for entry in plan_context.user_feedback[-5:]
        ]
        feedback_section = f"\n## User Feedback (PRIORITY)\n" + "\n".join(feedback_lines) + "\n"

    surgical_section = ""
    if plan_context.surgical_mode:
        allowed = plan_context.surgical_paths or ["Focus on the smallest viable change."]
        allowed_block = "\n".join(f"- {path}" for path in allowed)
        surgical_section = f"""
## Surgical Constraints
- Limit work to the files/modules listed below.
- Avoid refactors or wide-scoped changes.
- Keep diffs tight and explain every change explicitly.

Allowed focus areas:
{allowed_block}
"""

    return f"""You are the implementation agent for {task.id}.

## Objective
{task.description}

## Acceptance Criteria
{chr(10).join(f'- {check.description} ({check.type}:{check.target})' for check in task.acceptance_criteria) or '- None provided'}

{feedback_section if feedback_section else ''}

{surgical_section if surgical_section else ''}

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


def build_actor_workspace_context(
    task: Task,
    plan_context: PlanContext,
    project_root: Path,
) -> str:
    """Concise project snapshot appended to actor prompt."""
    lines: List[str] = []
    lines.append("### Operator Notes")
    lines.append(plan_context.notes_summary)
    lines.append("")

    lines.append("### Project Goals")
    for goal in plan_context.goals:
        lines.append(_format_goal_line(goal))

    lines.append("\n### Recent Feedback")
    recent = plan_context.feedback_log[-5:]
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

    if plan_context.surgical_mode:
        lines.append("\n### Surgical Constraints")
        if plan_context.surgical_paths:
            lines.extend(f"- Focus on: {path}" for path in plan_context.surgical_paths)
        else:
            lines.append("- Keep scope minimal; no broad refactors")

    domain = plan_context.domain
    domain_context = DomainContext.build(domain, project_root)
    if domain_context:
        pretty_domain = domain.replace("_", " ").title() if domain else "General"
        lines.append(f"\n### Domain Guidance ({pretty_domain})")
        lines.append(domain_context)

    return "\n".join(lines)


def build_reviewer_context(
    task: Task,
    plan_context: PlanContext,
) -> str:
    """Workspace context for the qualitative reviewer stage."""
    lines: List[str] = []
    lines.append("### Project Snapshot")
    for goal in plan_context.goals[:2]:
        lines.append(_format_goal_line(goal))

    lines.append("\n### Operator Notes")
    lines.append(plan_context.notes_summary or "No operator notes.")

    recent_feedback = plan_context.feedback_log[-2:]
    if recent_feedback:
        lines.append("\n### Recent Reviewer Notes")
        for item in recent_feedback:
            lines.append(
                f"- {item['task_id']} attempt {item['attempt']}: "
                f"{item['review_status']} – {item['review_summary']}"
            )

    if task.summary:
        lines.append("\n### Latest Task Summary")
        lines.append(f"- {task.summary[-1]}")

    if task.next_action:
        lines.append("\n### Requested Next Action")
        lines.append(f"- {task.next_action}")

    if plan_context.surgical_mode:
        lines.append("\n### Surgical Constraints")
        if plan_context.surgical_paths:
            lines.extend(f"- Focus on: {path}" for path in plan_context.surgical_paths)
        else:
            lines.append("- Maintain minimal diffs; no wide-ranging edits")

    if plan_context.user_feedback:
        lines.append("\n### Latest User Feedback (Priority)")
        for entry in plan_context.user_feedback[-5:]:
            scope = entry.task_id or "general"
            lines.append(f"- [{scope}] {entry.content}")

    return "\n".join(lines)
