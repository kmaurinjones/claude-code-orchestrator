# Claude Code Orchestrator

CLI wrapper for Claude Code that decomposes large development projects into autonomous, iteratively-executed tasks.

## Overview

Orchestrator solves Claude Code's fundamental limitation: inability to manage large, multi-step projects in a single prompt. It acts as an intelligent project manager that:

- **Interviews** users to extract goals and constraints interactively
- **Decomposes** goals into properly-scoped tasks with dependency graphs
- **Executes** tasks autonomously via spawned Claude Code subagents
- **Validates** work through Actor/Critic architectural pattern
- **Parallelizes** independent tasks for efficiency
- **Replans** dynamically when tasks fail
- **Auto-documents** changes via semantic versioning and docs updates

## How It Works

The orchestrator implements an autonomous system that:
- Spawns subagents using `claude -p` (non-interactive mode)
- Tracks full execution state via JSONL event logs
- Manages goal-driven task execution with dependency graphs
- Executes independent tasks in parallel waves (configurable `max_parallel_tasks`, defaults to sequential execution)
- Supports dynamic replanning and reflection
- Captures long-running experiment history via the `run_script` tool and surfaces it in reviews
- Implements Actor/Critic loop for code quality validation
- Decides whether to execute code directly or delegate to CC based on task context

## Architecture

```
orchestrator/
├── src/orchestrator/
│   ├── models.py                # Pydantic data models
│   ├── core/
│   │   ├── orchestrator.py      # Main orchestration loop
│   │   ├── actor.py             # Task execution via subagents
│   │   ├── critic.py            # Code quality validation
│   │   ├── reviewer.py          # Task verification & acceptance
│   │   ├── planner.py           # Goal decomposition
│   │   ├── replanner.py         # Dynamic replanning on failures
│   │   ├── subagent.py          # Claude CLI wrapper
│   │   ├── parallel_executor.py # Parallel task execution
│   │   ├── feedback.py          # Live user feedback system
│   │   ├── changelog.py         # Semantic versioning
│   │   ├── docs.py              # Auto-documentation generator
│   │   ├── logger.py            # JSONL event logging
│   │   ├── experiments.py       # Long-running job manager
│   │   ├── domain_context.py    # Domain-specific guardrails
│   │   └── ...                  # Other utilities
│   ├── planning/
│   │   ├── goals.py             # GOALS.md parser
│   │   └── tasks.py             # Task dependency graph
│   ├── tools/
│   │   └── run_script.py        # Long-running job execution
│   └── cli/
│       └── __init__.py          # CLI entry point
├── docs/                        # Comprehensive documentation
├── example-projects/            # Real-world example workflows
└── pyproject.toml               # Project metadata & dependencies
```


## Prerequisites

- Python ≥3.11
- Claude Code CLI: `npm install -g @anthropic-ai/claude-code` (requires Claude Max subscription or local install)

## Installation

```bash
cd /path/to/claude-code-orchestrator
uv sync
uv run orchestrate --version  # Verify installation
```

## Quick Start

Three-step workflow:

### 1. Interview
```bash
cd /path/to/your/project
orchestrate interview --workspace .orchestrator
```
Interactively define project goals, success criteria, and constraints. Creates `GOALS.md` and `TASKS.md`.

**Interview options:**
- `--workspace PATH` - Set workspace directory (default: `.orchestrator`)
- `--update` - Update existing goals and tasks instead of starting fresh
- `--fresh` - Ignore existing GOALS/TASKS even if they exist (restart from scratch)

### 2. Run Orchestrator
```bash
orchestrate run --workspace .orchestrator --max-steps 100
```
Autonomously executes all tasks. Parallelizes independent work, retries failures, and replans dynamically.

**Run options:**
- `--workspace PATH` - Set workspace directory (default: `.orchestrator`)
- `--max-steps N` - Set maximum iterations
- `--max-parallel-tasks N` - Control parallelism (default 1 for safety; override to enable concurrency)
- `--surgical` - Enable tight scope, minimal edits mode (minimal changes to existing code)

### 3. Schedule Experiments (Optional)
```bash
orchestrate experiment --cmd "uv run train.py" --run-name "trial-1" --workspace .orchestrator
```
Enqueue long-running jobs (training, migrations, etc.) without blocking main orchestrator loop.

**Experiment options:**
- `--workspace PATH` - Set workspace directory (default: `.orchestrator`)
- `--cmd COMMAND` - Command to execute (required)
- `--run-name NAME` - Name recorded in experiment history
- `--workdir PATH` - Working directory for command (default: current dir)
- `--timeout SECONDS` - Set execution timeout
- `--notes TEXT` - Record notes with experiment
- `--task-id ID` - Link experiment to specific task
- `--metrics-file PATH` - Track JSON metrics from command output

## Key Features

**Autonomous Task Execution**
- Spawns Claude Code subagents for each task via non-interactive mode
- Tracks full state via JSONL event logs and snapshot files
- Retries failures with feedback from critic (code quality) and reviewer (tests)

**Smart Scheduling**
- Dependency graph tracks task prerequisites
- Parallel execution of independent work (configurable `max_parallel_tasks`, default 1)
- Priority-based task selection

**Long-Running Jobs**
- Enqueue training, migrations, or large builds via `orchestrate experiment`
- Executes outside Claude's time limit constraints
- Streams logs and metrics to `.orchestrator/history/`

**Quality Gates**
- Actor/Critic loop: subagent writes code, critic enforces standards (naming, whitespace, Ruff linting)
- Accepts existing work if tests already pass (enables resume from partial projects)
- Task-specific verification checks (file_exists, command_passes, pattern matching)

**Replanning & Feedback**
- Analyzes test/critic failures and spawns remediation tasks automatically
- Live user feedback via `.orchestrator/current/USER_NOTES.md` (edit anytime during execution)
- Domain-aware guardrails (data science, backend, frontend, tooling)

**Auto-Documentation**
- Updates `CHANGELOG.md` with semantic versioning after each task
- Maintains `docs/` directory (architecture, components, troubleshooting)
- Archives failed attempts for future reference

## Workspace Structure

```
.orchestrator/
    full_history.jsonl       # Complete event log
    snapshots/               # Periodic state snapshots
    current/
        GOALS.md             # Project goals
        PLAN.md              # Execution plan
        TASKS.md             # Task graph
        HISTORY.md           # Human-readable history
    USER_NOTES.md            # Live user feedback during execution
    .feedback_state.json     # Feedback tracking state
```


## User Feedback System

The orchestrator supports live feedback during execution through `USER_NOTES.md`:

**How it works:**
1. When orchestrator starts, it creates `.orchestrator/current/USER_NOTES.md`
2. Edit this file anytime during execution to provide feedback (add under the **New Notes** section)
3. The orchestrator ingests new notes at the beginning of every iteration and before each review
4. Consumed feedback is automatically moved to the **Previously Reviewed** section with timestamps

**Feedback format:**
- `- [task-001] Your task-specific feedback` - applies to specific task
- `- [general] Your general guidance` - applies to all tasks
- Plain text is treated as general feedback

**Example:**
```markdown
## New Notes (Write here - will be consumed on next review)

- [task-003] Use POST instead of GET for this endpoint
- [general] Prioritize error handling over new features

---

## Previously Reviewed
<!-- Reviewed at 2025-11-13 14:32:15 -->
- [task-002] Add validation for user inputs
```

## Event Types

- `DECISION`: Orchestrator decision
- `SPAWN`: Subagent created
- `COMPLETE`: Task completed
- `ERROR`: Failure occurred
- `CHECKPOINT`: System state saved
- `REFLECTION`: Progress analyzed
- `REPLAN`: Plan updated

## Task Status Flow

```
BACKLOG (=)  IN_PROGRESS (=)  COMPLETE (✔)
                                 FAILED (✗)
                                 BLOCKED (⛔)
```

## Automatic Documentation & Changelog

The orchestrator automatically maintains project documentation and a changelog:

**CHANGELOG.md** (project root)
- Semantic versioning (MAJOR.MINOR.PATCH)
- Automatically updated after each task completion
- Newest entries at top
- Categories: Added, Changed, Fixed, Removed, Attempted (failed tasks)

**docs/ directory** (maintained by docs subagent)
- `docs/README.md` - Project overview and getting started
- `docs/architecture.md` - System design and component relationships
- `docs/components/` - Individual component documentation
- `docs/scripts.md` - How to run scripts, what they do
- `docs/api.md` - API documentation (if applicable)
- `docs/troubleshooting.md` - Common issues and solutions (including failed attempts)

**When updates happen:**
- After each successful task: Changelog entry + relevant docs updated
- After task failures: Documented in troubleshooting.md with what was attempted
- Documentation subagent analyzes changes and updates affected docs

## Example Workflow

1. **Interview**: Define goals interactively
2. **Plan**: Orchestrator breaks goals into tasks
3. **Execute**: Spawn subagents to complete tasks
4. **Track**: Monitor progress via TASKS.md and logs
5. **Document**: Auto-update docs/ and CHANGELOG.md after each task
6. **Reflect**: Periodic assessment and replanning
7. **Complete**: All core goals achieved

## Limitations

- Claude Code CLI must be installed and authenticated
- Subagents run with `--dangerously-skip-permissions` (security consideration)
- 10-minute timeout per subagent
- JSON response parsing depends on subagent following format

## Development Resources

### Code Quality & Architecture

The project maintains comprehensive documentation to support development:

- **[refactor-analysis.md](./refactor-analysis.md)** - Complete dependency analysis and architectural structure
  - Import dependency graphs for all 31 modules
  - Zero circular dependencies verified
  - Hub modules and leaf modules identification
  - Entry points and execution paths
  - Refactoring recommendations

- **[docs/architecture.md](./docs/architecture.md)** - System design and component relationships
- **[docs/README.md](./docs/README.md)** - Project documentation hub

### Running Tests & Linting

```bash
# Run tests
uv run pytest

# Lint code
uv run ruff check src/

# Format code
uv run ruff format src/
```

### Contributing

When making architectural changes:
1. Ensure no new circular dependencies are introduced
2. Review the entry points in `refactor-analysis.md` before modifying CLI
3. Consider the hub module recommendations when refactoring `core/orchestrator.py` or `core/planner.py`
4. Keep module count and dependency graph in mind when adding new features

## License

MIT
