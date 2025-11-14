"""Completion summary generator for orchestrator runs."""

from pathlib import Path
from typing import List
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from .subagent import Subagent
from .domain_context import DomainDetector
from ..models import Goal
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
        usage_instructions = self._generate_usage_instructions(domain, goals, tasks)

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
        domain: str,
        goals: List[Goal],
        tasks: TaskGraph,
    ) -> str:
        """Generate contextual usage instructions using subagent."""

        # Build context for subagent
        goals_summary = "\n".join(
            f"- [{goal.id}] {goal.description} (achieved: {goal.achieved})"
            for goal in goals
        )

        completed_tasks = [t for t in tasks.tasks.values() if t.status.value == "complete"]
        task_summary = "\n".join(
            f"- {task.title}: {task.description[:100]}"
            for task in completed_tasks[:10]  # Limit to recent 10
        )

        instruction = f"""Analyze this project and generate concise usage instructions.

## Project Context
Domain: {domain}
Project root: {self.project_root}

## Goals
{goals_summary}

## Recently Completed Tasks
{task_summary}

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

Return ONLY the markdown guide, no preamble."""

        agent = Subagent(
            task_id="completion-summary",
            task_description=instruction,
            context="",
            max_turns=15,
            model="sonnet",  # Use Sonnet for higher quality summary
            workspace=self.workspace,
            project_root=self.project_root,
        )

        result = agent.execute()

        if result.get("status") == "success":
            return result.get("response", "").strip()

        # Fallback: basic instructions if subagent fails
        return self._generate_fallback_instructions(domain)

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

    def _generate_fallback_instructions(self, domain: str) -> str:
        """Generate basic fallback instructions if subagent fails."""
        if domain == "data_science":
            return """## Quick Start
Run training: `python train.py` or `python src/train.py`
Check experiments: `cat .agentic/history/experiments.jsonl`

## Key Files
- Training scripts: Look for `train*.py` files
- Notebooks: Check `.ipynb` files for exploratory analysis
- Metrics: `.agentic/history/experiments.jsonl` contains run history
"""
        elif domain == "backend":
            return """## Quick Start
Start server: `python main.py` or `uvicorn app:app --reload`

## Key Commands
- Start dev: Check `pyproject.toml` or `package.json` for scripts
- Run tests: `pytest` or `npm test`
- Migrations: Check for `alembic` or database migration files
"""
        elif domain == "frontend":
            return """## Quick Start
Start dev: `npm run dev` or `npm start`
Build: `npm run build`

## Key Files
- Config: `package.json`, `vite.config.ts`, `next.config.js`
- Environment: `.env.local` or `.env.example`
"""
        else:
            return """## Quick Start
Check README.md or docs/ directory for usage instructions.

## Configuration
Look for:
- `config.yaml`, `pyproject.toml`, or similar configuration files
- `.env` files for environment variables
"""

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
        completed = [t for t in all_tasks if t.status.value == "complete"]
        failed = [t for t in all_tasks if t.status.value == "failed"]
        pending = [t for t in all_tasks if t.status.value in ("pending", "in_progress")]

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
