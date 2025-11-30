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


def _extract_deliverables(task: Task) -> str:
    """Extract concrete deliverables from acceptance criteria for prominent display."""
    if not task.acceptance_criteria:
        return ""

    deliverables = []
    for check in task.acceptance_criteria:
        if check.type == "file_exists":
            deliverables.append(f"- CREATE FILE: `{check.target}`")
        elif check.type == "pattern_in_file":
            deliverables.append(
                f"- FILE WITH CONTENT: `{check.target}` (must contain: `{check.expected or check.description}`)"
            )

    if not deliverables:
        return ""

    return "## REQUIRED DELIVERABLES (CREATE THESE)\n" + "\n".join(deliverables) + "\n"


def _format_acceptance_criteria(task: Task) -> str:
    """Format acceptance criteria with explicit instructions for the actor."""
    if not task.acceptance_criteria:
        return "- None provided"

    lines = []
    lines.append(
        "**CRITICAL: Your work will be automatically verified against these checks.**"
    )
    lines.append(
        "**You MUST ensure your output satisfies ALL of these criteria or the task will FAIL.**"
    )
    lines.append("")
    lines.append(
        "⚠️ **IT IS UNACCEPTABLE TO REMOVE, MODIFY, OR SKIP THESE ACCEPTANCE CRITERIA.**"
    )
    lines.append(
        "These checks exist to verify your work objectively. Attempting to change them"
    )
    lines.append(
        "instead of implementing the required functionality is considered a FAILURE.\n"
    )

    for i, check in enumerate(task.acceptance_criteria, 1):
        lines.append(f"### Check {i}: {check.description}")
        lines.append(f"- Type: `{check.type}`")
        lines.append(f"- Target: `{check.target}`")

        if check.type == "pattern_in_file":
            lines.append(
                f"- **REQUIRED PATTERN**: Your output file MUST contain text matching: `{check.expected or check.description}`"
            )
            lines.append(
                "  - This is a regex pattern. Make sure your content includes words/phrases that match."
            )
            if check.expected:
                # Give examples of what would match
                pattern = check.expected
                if "|" in pattern:
                    options = pattern.split("|")
                    lines.append(
                        f"  - Example valid matches: include ANY of these exact terms: {', '.join(options)}"
                    )
        elif check.type == "file_exists":
            lines.append(f"- **YOU MUST CREATE THIS FILE**: `{check.target}`")
            lines.append(
                "  - This file must exist when you finish. Use Write or Edit tools to create it."
            )
            lines.append("  - The file path is relative to the project root directory.")
        elif check.type == "command_succeeds":
            lines.append(f"  - This command must exit with code 0: `{check.target}`")

        lines.append("")

    return "\n".join(lines)


def build_task_agent_prompt(task: Task, plan_context: PlanContext) -> str:
    """Return the implementation instructions for the actor."""
    feedback_section = ""
    if plan_context.user_feedback:
        feedback_lines = [
            f"- [{'general' if entry.is_general else entry.task_id}] {entry.content}"
            for entry in plan_context.user_feedback[-5:]
        ]
        feedback_section = (
            "\n## User Feedback (PRIORITY)\n" + "\n".join(feedback_lines) + "\n"
        )

    surgical_section = ""
    if plan_context.surgical_mode:
        allowed = plan_context.surgical_paths or [
            "Focus on the smallest viable change."
        ]
        allowed_block = "\n".join(f"- {path}" for path in allowed)
        surgical_section = f"""
## Surgical Constraints
- Limit work to the files/modules listed below.
- Avoid refactors or wide-scoped changes.
- Keep diffs tight and explain every change explicitly.

Allowed focus areas:
{allowed_block}
"""

    acceptance_criteria = _format_acceptance_criteria(task)
    deliverables = _extract_deliverables(task)

    # Get bearings section - helps actors understand current state
    get_bearings_section = """## STEP 1: Get Your Bearings (DO THIS FIRST)

Before implementing anything, orient yourself:

1. **Check git status**: Run `git status` to see what files are modified/staged
2. **Read recent commits**: Run `git log --oneline -5` to understand recent changes
3. **Review progress**: Check the workspace context below for previous task summaries
4. **Verify nothing is broken**: If there are existing tests/checks, run them first
   - If something is broken from a previous session, FIX IT FIRST before new work

Only after understanding the current state should you proceed to implementation.
"""

    # Clean state section - ensures actors leave things in a good state
    clean_state_section = """## STEP 3: Leave Clean State (DO THIS WHEN DONE)

Before reporting completion:

1. **No half-implemented code**: All changes must be complete and functional
2. **Commit your work**: Run `git add` and `git commit -m "descriptive message"` for your changes
3. **Verify acceptance criteria pass**: Re-run any checks to confirm they pass
4. **No debug artifacts**: Remove any debug prints, temporary files, or commented-out code
5. **Code compiles/runs**: Ensure there are no syntax errors or import failures

The environment must be left in a state where the next agent (or human) can
immediately start working on the next task without cleanup.
"""

    return f"""You are the implementation agent for {task.id}.

{get_bearings_section}
{deliverables}
## STEP 2: Implement the Objective
{task.description}

## Acceptance Criteria (MANDATORY)
{acceptance_criteria}

{feedback_section if feedback_section else ""}

{surgical_section if surgical_section else ""}

{clean_state_section}

## Additional Guidelines
- Work incrementally and keep changes minimal but functional.
- Document any limitations directly in code comments where relevant.
- Avoid running slow external services unless required.
- Always review the Operator Notes section for priority guidance before acting.
- **NEVER create files inside the `.orchestrator/` directory** - that directory is reserved for orchestrator metadata only. All project files, outputs, and deliverables must be created in the project root or its subdirectories (NOT inside `.orchestrator/`).
- **DO NOT update CHANGELOG.md** - changelog updates are handled automatically by the orchestrator at specific intervals. Manual updates will cause duplicate entries.
- **DO NOT modify acceptance criteria** - they are immutable verification checks.

Respond with the mandatory JSON block when finished."""


def build_actor_workspace_context(
    task: Task,
    plan_context: PlanContext,
    project_root: Path,
) -> str:
    """Concise project snapshot appended to actor prompt."""
    lines: List[str] = []

    # Session orientation - git status and recent commits
    lines.append("### Current Git Status")
    lines.append("```")
    lines.append(plan_context.git_status or "Working directory clean")
    lines.append("```")
    lines.append("")

    lines.append("### Recent Git Commits")
    lines.append("```")
    lines.append(plan_context.git_recent_commits or "No commits yet")
    lines.append("```")
    lines.append("")

    # Recent progress from previous sessions
    if (
        plan_context.progress_summary
        and plan_context.progress_summary != "No previous progress recorded."
    ):
        lines.append("### Recent Progress (Previous Sessions)")
        lines.append(plan_context.progress_summary)
        lines.append("")

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
