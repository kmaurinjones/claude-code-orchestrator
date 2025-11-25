"""CLI entry point."""

import sys
import subprocess
from pathlib import Path
from rich.console import Console
import argparse

from ..core.orchestrator import Orchestrator
from ..core.subagent import find_claude_executable
from ..models import OrchestratorConfig
from .. import __version__

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Agentic Orchestrator")
    parser.add_argument("--version", action="store_true", help="Show orchestrator version and exit")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Interview command
    interview_parser = subparsers.add_parser("interview", help="Start project with interview")
    interview_parser.add_argument("--workspace", type=Path, default=Path(".orchestrator"))
    interview_parser.add_argument("--update", action="store_true", help="Update existing goals and tasks instead of starting fresh")
    interview_parser.add_argument("--fresh", action="store_true", help="Ignore existing GOALS/TASKS even if they exist")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run orchestrator")
    run_parser.add_argument("--workspace", type=Path, default=Path(".orchestrator"))
    run_parser.add_argument("--min-steps", type=int, default=None, help="Minimum iterations (overrides config)")
    run_parser.add_argument("--max-steps", type=int, default=None, help="Maximum iterations (overrides config)")
    run_parser.add_argument("--surgical", action="store_true", help="Enable surgical mode (tight scope, minimal edits)")
    run_parser.add_argument(
        "--surgical-path",
        dest="surgical_paths",
        action="append",
        default=None,
        help="Paths that the surgical run should focus on (repeat for multiple).",
    )

    args = parser.parse_args()

    if getattr(args, "version", False):
        console.print(__version__)
        return

    if args.command == "interview":
        # Check Claude Code availability
        claude_path = find_claude_executable()
        if not claude_path:
            console.print("[red]ERROR:[/red] Claude Code CLI not found")
            console.print("Searched in:")
            console.print("  - ~/.claude/local/node_modules/.bin/claude")
            console.print("  - /usr/local/bin/claude")
            console.print("  - System PATH")
            console.print("\nInstall: npm install -g @anthropic-ai/claude-code")
            console.print("Or ensure you have Claude Max subscription")
            sys.exit(1)

        console.print(f"[green]✓[/green] Found Claude CLI: {claude_path}")

        # Ensure workspace exists
        args.workspace.mkdir(parents=True, exist_ok=True)
        (args.workspace / "current").mkdir(exist_ok=True)

        # Check if updating existing project
        goals_file = args.workspace / "current" / "GOALS.md"
        tasks_file = args.workspace / "current" / "TASKS.md"

        has_existing = goals_file.exists() and tasks_file.exists()
        use_update_flow = args.update or (has_existing and not args.fresh)

        if use_update_flow:
            # Update mode
            if not has_existing:
                console.print("[red]ERROR:[/red] --update requires existing GOALS.md and TASKS.md")
                console.print("Run 'orchestrate interview' without --update first.")
                sys.exit(1)

            console.print("[bold]Updating Existing Project...[/bold]\n")
            console.print(f"Working directory: {Path.cwd()}")
            console.print(f"Workspace: {args.workspace.absolute()}\n")

            # Load existing content
            existing_goals = goals_file.read_text()
            existing_tasks = tasks_file.read_text()

            # Build update prompt
            prompt = f"""You are helping update an existing project in the current directory: {Path.cwd()}

The user wants to amend their project goals and tasks.

## Current GOALS.md:
```
{existing_goals}
```

## Current TASKS.md:
```
{existing_tasks}
```

Conduct an interactive discussion with the user to understand what they want to change:
- Add new goals or tasks
- Remove existing ones
- Modify priorities or dependencies
- Adjust constraints

After gathering all amendments, UPDATE the TWO files (.orchestrator/current/GOALS.md and .orchestrator/current/TASKS.md) with the changes while preserving the format. Treat the existing content as the baseline and continue the plan rather than restarting from scratch.

IMPORTANT: All tasks in TASKS.md must have (priority: X) where X is 1-10, with 10 being highest priority.

When done, tell the user they can now run: orchestrate run

Start the discussion now.
"""
        else:
            # Fresh interview mode
            console.print("[bold]Starting Interview...[/bold]\n")
            console.print(f"Working directory: {Path.cwd()}")
            console.print(f"Workspace will be created at: {args.workspace.absolute()}\n")

            prompt = f"""You are helping set up a new project in the current directory: {Path.cwd()}

Conduct a project planning interview with the user.

Ask the user questions to establish:
1. Core success criteria (3-5 specific, measurable goals that MUST be achieved)
2. Nice-to-have features (flexible, can be skipped)
3. Out of scope items (what this project will NOT do)
4. Technical constraints (language, frameworks, requirements)

After gathering all information, create TWO files:

1. Create .orchestrator/current/GOALS.md with this EXACT format:

# GOALS.md
Generated: [current timestamp]

## Core Success Criteria (IMMUTABLE)
1. **[Goal title]**
   - Measurable: [How to verify this is done]
   - Non-negotiable: [Why this matters]

2. **[Goal title]**
   - Measurable: [How to verify this is done]
   - Non-negotiable: [Why this matters]

[Continue for all core goals...]

## Nice-to-Have (FLEXIBLE)
- [Feature 1]
- [Feature 2]

## Out of Scope
- [Item 1]
- [Item 2]

## Constraints (IMMUTABLE)
- [Constraint 1]
- [Constraint 2]

2. Create .orchestrator/current/TASKS.md with initial structure:

# TASKS.md

## Backlog
- [📋] task-001: [First task description] (priority: 10)
  - Verify: file_exists:path/to/file.py "Check that file was created"
  - Verify: command_passes:pytest tests/ "All tests pass"
- [📋] task-002: [Second task description] (priority: 8)

IMPORTANT:
- Always include (priority: X) for every task where X is 1-10, with 10 being highest priority.
- Add verification checks under each task using format: "Verify: <type>:<target> "<description>""
- Verification types: file_exists, command_passes, pattern_in_file
- These checks prove task completion objectively
- **CRITICAL**: All file paths in verification checks must be relative to the project root, NOT inside `.orchestrator/`. The `.orchestrator/` directory is reserved for orchestrator metadata only. Example: use `research/notes.md` NOT `.orchestrator/current/research/notes.md`.

Tell the user the interview is complete and they should now run: orchestrate run

Start the interview now.
"""

        # Run interactive Claude session (Opus for planning/interview quality)
        subprocess.run([
            claude_path,
            "--model", "opus",
            "--dangerously-skip-permissions",
            prompt
        ])

        # Create default config file
        config_path = args.workspace / "orchestrator.config.yaml"
        if not config_path.exists():
            default_config = OrchestratorConfig()
            default_config.save(config_path)
            console.print(f"\n[green]✓[/green] Created config file: {config_path}")
            console.print("[dim]Edit this file to customize orchestrator settings[/dim]")

    elif args.command == "run":
        # Check workspace exists
        if not args.workspace.exists():
            console.print(f"[red]ERROR:[/red] Workspace not found: {args.workspace.absolute()}")
            console.print("\nRun 'orchestrate interview' first to set up your project.")
            sys.exit(1)

        # Check GOALS.md exists
        goals_file = args.workspace / "current" / "GOALS.md"
        if not goals_file.exists():
            console.print(f"[red]ERROR:[/red] GOALS.md not found: {goals_file}")
            console.print("\nRun 'orchestrate interview' first to create project goals.")
            sys.exit(1)

        # Load config file if exists
        config_path = args.workspace / "orchestrator.config.yaml"
        config = OrchestratorConfig.load(config_path)

        # CLI args override config
        min_steps = args.min_steps if args.min_steps is not None else config.min_steps
        max_steps = args.max_steps if args.max_steps is not None else config.max_steps

        console.print("[bold]Starting Orchestrator...[/bold]\n")
        console.print(f"Working directory: {Path.cwd()}")
        console.print(f"Workspace: {args.workspace.absolute()}")
        if config_path.exists():
            console.print(f"[dim]Config: {config_path}[/dim]")
        console.print(f"Min iterations: {min_steps}")
        console.print(f"Max iterations: {max_steps}")
        console.print(f"Subagent max turns: {config.subagent_max_turns}")
        console.print(f"Skip integration tests: {config.skip_integration_tests}")
        if config.pytest_addopts:
            console.print(f"Additional pytest opts: {config.pytest_addopts}")
        console.print()

        console.print("[green]✓[/green] Workspace found")
        console.print("[green]✓[/green] GOALS.md found")
        console.print("\n[bold cyan]Starting autonomous execution...[/bold cyan]\n")

        orch = Orchestrator(
            workspace=args.workspace,
            min_steps=min_steps,
            max_steps=max_steps,
            subagent_max_turns=config.subagent_max_turns,
            skip_integration_tests=config.skip_integration_tests,
            pytest_addopts=config.pytest_addopts,
            surgical_mode=args.surgical,
            surgical_paths=args.surgical_paths,
            docs_update_interval=config.docs_update_interval,
        )
        result = orch.run()

        console.print("\n" + "="*60)
        console.print(f"[bold]Final Result:[/bold] {result}")
        console.print("="*60)

        if result == "SUCCESS":
            console.print("\n[green]✓ All core goals achieved![/green]")
        elif result == "NO_TASKS_AVAILABLE":
            console.print("\n[yellow]⚠ No tasks available to execute[/yellow]")
            console.print("Check .orchestrator/current/TASKS.md")
        elif result == "MAX_ITERATIONS_REACHED":
            console.print(f"\n[yellow]⚠ Reached max iterations ({max_steps})[/yellow]")
            console.print("Some goals may not be complete. Check .orchestrator/current/TASKS.md")

        console.print(f"\nEvent log: {args.workspace / 'full_history.jsonl'}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
