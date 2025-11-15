"""Completion summary generator for orchestrator runs."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Dict, List
from uuid import uuid4
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from .subagent import Subagent
from .domain_context import DomainDetector
from .logger import EventLogger
from ..models import Goal, TaskStatus
from ..planning.tasks import TaskGraph

console = Console()


class CompletionSummary:
    """Generates completion summary with usage instructions."""

    def __init__(self, project_root: Path, workspace: Path):
        self.project_root = project_root
        self.workspace = workspace

    def generate_and_display(
        self,
        goals: List[Goal],
        tasks: TaskGraph,
        completion_reason: str,
        step_count: int,
    ) -> None:
        """
        Generate completion summary and display to console.

        Args:
            goals: List of project goals
            tasks: Task graph with execution history
            completion_reason: Why orchestrator stopped (SUCCESS, NO_TASKS_AVAILABLE, MAX_ITERATIONS_REACHED)
            step_count: Total steps executed
        """
        console.print("\n" + "=" * 80)
        console.print("[bold cyan]ORCHESTRATOR RUN COMPLETE[/bold cyan]")
        console.print("=" * 80 + "\n")

        # Display completion status
        status_color = "green" if completion_reason == "SUCCESS" else "yellow"
        console.print(f"[{status_color}]Status:[/{status_color}] {completion_reason}")
        console.print(f"[dim]Steps executed:[/dim] {step_count}")
        console.print()

        # Detect domain for contextual instructions
        domain = DomainDetector.detect(self.project_root, goals)

        # Generate usage instructions via subagent
        usage_instructions = self._generate_usage_instructions(
            domain=domain,
            goals=goals,
            tasks=tasks,
            completion_reason=completion_reason,
        )

        if usage_instructions:
            console.print(Panel(
                Markdown(usage_instructions),
                title="[bold green]How to Use This Project[/bold green]",
                border_style="green",
                padding=(1, 2),
            ))

        # Display goals summary
        self._display_goals_summary(goals)

        # Display task statistics
        self._display_task_statistics(tasks)

    def _generate_usage_instructions(
        self,
        *,
        domain: str,
        goals: List[Goal],
        tasks: TaskGraph,
        completion_reason: str,
    ) -> str:
        """Generate contextual usage instructions using subagent."""

        # Build context for subagent
        goals_summary = "\n".join(
            f"- [{goal.id}] {goal.description} (achieved: {goal.achieved})"
            for goal in goals
        )

        recent_task_lines = self._recent_completed_tasks(tasks)
        task_summary = "\n".join(recent_task_lines) if recent_task_lines else "- No completed tasks recorded yet."

        task_stats = self._task_statistics(tasks)
        goals_done = len([goal for goal in goals if goal.achieved])
        goals_total = len(goals)
        incomplete_goals = [goal.description for goal in goals if not goal.achieved]
        incomplete_goal_lines = (
            "\n".join(f"- {desc}" for desc in incomplete_goals[:5])
            if incomplete_goals
            else "- None"
        )
        status_snapshot = (
            f"- Completion result: {completion_reason}\n"
            f"- Goals achieved: {goals_done}/{goals_total}\n"
            f"- Tasks: {task_stats['completed']} completed / {task_stats['failed']} failed / {task_stats['pending']} pending"
        )

        instruction = f"""Analyze this project and generate concise usage instructions.

## Project Context
Domain: {domain}
Project root: {self.project_root}

## Goals
{goals_summary}

## Recently Completed Tasks
{task_summary}

## Status Snapshot
{status_snapshot}

## Incomplete Goals
{incomplete_goal_lines}

## Your Task
Generate a concise markdown guide (200-400 words) explaining how to use this project:

1. **Quick Start**: Single command to run/test the project (if applicable)
2. **Key Commands**: List 3-5 most important CLI commands with brief explanations
3. **Configuration**: Where to find/modify configuration (if applicable)
4. **Next Steps**: 1-2 suggested actions for users

**Domain-Specific Focus:**
{self._get_domain_instructions(domain)}

**Important:**
- Use actual file paths from the project
- Include real command examples (not placeholders)
- Be specific and actionable
- Keep it concise
- Only describe the project as production-ready if all goals are achieved, no tasks failed, and completion_reason == SUCCESS. Otherwise explicitly warn the reader about outstanding work or failures.

Return ONLY the markdown guide, no preamble."""

        # Create minimal logger for subagent
        logger = EventLogger(self.workspace / "full_history.jsonl")
        trace_id = str(uuid4())

        agent = Subagent(
            task_id="completion-summary",
            task_description=instruction,
            context="",
            parent_trace_id=trace_id,
            logger=logger,
            step=0,
            workspace=self.project_root,
            max_turns=15,
            model="sonnet",  # Use Sonnet for higher quality summary
            log_workspace=self.workspace,
        )

        result = agent.execute()

        if result.get("status") == "success":
            content = result.get("output") or result.get("summary") or ""
            markdown = self._extract_markdown(content)
            if markdown:
                return markdown

        # Fallback: basic instructions if subagent fails
        return self._generate_fallback_instructions(domain, task_summary)

    def _get_domain_instructions(self, domain: str) -> str:
        """Get domain-specific instructions for usage guide generation."""
        if domain == "data_science":
            return """
- Show how to run training scripts with key parameters
- Explain how to load trained models
- Show how to check experiment logs/metrics
- Include dataset preparation if applicable
"""
        elif domain == "backend":
            return """
- Show how to start the development server
- List key API endpoints and how to test them
- Explain environment variable configuration
- Include database setup/migration commands if applicable
"""
        elif domain == "frontend":
            return """
- Show how to start development server
- Explain build process for production
- List available scripts in package.json
- Include environment configuration
"""
        else:  # tooling
            return """
- Show main CLI command(s) with common flags
- Explain configuration file location
- Include example usage scenarios
- Show how to get help/documentation
"""

    def _generate_fallback_instructions(self, domain: str, task_summary: str) -> str:
        """Generate basic fallback instructions if subagent fails."""
        if domain == "data_science":
            return f"""## Quick Start
Run pipeline: `uv run python main.py`
Check experiments: `cat .orchestrator/history/experiments.jsonl`

## Key Files
- Training scripts: Look for `train*.py` files
- Notebooks: Check `.ipynb` files for exploratory analysis
- Metrics: `.orchestrator/history/experiments.jsonl`

## Recent Work
{task_summary}
"""
        elif domain == "backend":
            return f"""## Quick Start
Start server: `uv run python main.py` or `uvicorn app:app --reload`

## Key Commands
- Start dev: see scripts in `pyproject.toml`
- Run tests: `uv run pytest`
- Environment: configure `.env` files

## Recent Work
{task_summary}
"""
        elif domain == "frontend":
            return f"""## Quick Start
Start dev: `npm run dev`
Build: `npm run build`

## Key Files
- Config: `package.json`, `vite.config.ts`, `next.config.js`
- Environment: `.env.local`

## Recent Work
{task_summary}
"""
        else:
            return f"""## Quick Start
Run CLI: `uv run python main.py` (see README.md for options)

## Configuration
- `pyproject.toml` for dependencies/CLI entry points
- `.orchestrator/current/TASKS.md` for remaining work

## Recent Work
{task_summary}
"""

    def _recent_completed_tasks(self, tasks: TaskGraph, limit: int = 10) -> List[str]:
        """Return textual summaries of recent completed tasks."""
        completed = [
            task for task in tasks.tasks.values()
            if task.status == TaskStatus.COMPLETE
        ]
        if completed:
            return [
                f"- {task.title}: {task.description[:120]}"
                for task in completed[-limit:]
            ]

        history_file = self.workspace / "history" / "tasks.jsonl"
        if not history_file.exists():
            return []

        lines = history_file.read_text(encoding="utf-8").splitlines()
        entries: List[str] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(data.get("status", "")).upper() != TaskStatus.COMPLETE.name:
                continue
            title = data.get("title", "Task")
            summary = (data.get("review_summary") or "")[:120]
            text = f"- {title}: {summary}" if summary else f"- {title}"
            entries.append(text)
            if len(entries) >= limit:
                break
        return list(reversed(entries))

    def _task_statistics(self, tasks: TaskGraph) -> Dict[str, int]:
        all_tasks = list(tasks.tasks.values())
        completed = [t for t in all_tasks if t.status == TaskStatus.COMPLETE]
        failed = [t for t in all_tasks if t.status == TaskStatus.FAILED]
        pending = [
            t for t in all_tasks
            if t.status in {TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS}
        ]
        return {
            "completed": len(completed),
            "failed": len(failed),
            "pending": len(pending),
        }

    def _extract_markdown(self, output: str) -> str:
        """Try to extract markdown content from subagent output."""
        if not output:
            return ""

        parsed = None
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            try:
                parsed = ast.literal_eval(output)
            except Exception:
                parsed = None

        if isinstance(parsed, dict):
            for key in ("result", "content", "output", "response"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return self._strip_trailing_json(value.strip())

        return self._strip_trailing_json(output.strip())

    def _strip_trailing_json(self, text: str) -> str:
        """Remove trailing JSON metadata blocks from agent output."""
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("{") and self._looks_like_json_block(lines[idx:]):
                return "\n".join(lines[:idx]).rstrip()
        return text

    def _looks_like_json_block(self, lines: List[str]) -> bool:
        """Heuristic: determine if remaining lines form a JSON object."""
        snippet = "\n".join(lines).strip()
        if not snippet.startswith("{"):
            return False
        try:
            json.loads(snippet)
            return True
        except json.JSONDecodeError:
            return False

    def _display_goals_summary(self, goals: List[Goal]) -> None:
        """Display goals achievement summary."""
        achieved = [g for g in goals if g.achieved]
        not_achieved = [g for g in goals if not g.achieved]

        console.print("\n[bold]Goals Summary[/bold]")
        console.print(f"  ✓ Achieved: {len(achieved)}/{len(goals)}")

        if achieved:
            console.print("\n  [green]Completed:[/green]")
            for goal in achieved:
                console.print(f"    • {goal.description}")

        if not_achieved:
            console.print("\n  [yellow]Incomplete:[/yellow]")
            for goal in not_achieved:
                console.print(f"    • {goal.description}")

    def _display_task_statistics(self, tasks: TaskGraph) -> None:
        """Display task execution statistics."""
        all_tasks = list(tasks.tasks.values())
        completed = [t for t in all_tasks if t.status == TaskStatus.COMPLETE]
        failed = [t for t in all_tasks if t.status == TaskStatus.FAILED]
        pending = [
            t for t in all_tasks
            if t.status in {TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS}
        ]

        console.print("\n[bold]Task Statistics[/bold]")
        console.print(f"  Total tasks: {len(all_tasks)}")
        console.print(f"  [green]✓ Completed:[/green] {len(completed)}")
        if failed:
            console.print(f"  [red]✗ Failed:[/red] {len(failed)}")
        if pending:
            console.print(f"  [yellow]⋯ Pending:[/yellow] {len(pending)}")

        console.print(f"\n[dim]Event logs: {self.workspace / 'current' / 'events.jsonl'}[/dim]")
        console.print(f"[dim]Full history: {self.workspace / 'full_history.jsonl'}[/dim]")
        console.print()
