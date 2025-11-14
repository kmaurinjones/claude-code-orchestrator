# Orchestrator

A CLI wrapper for Claude Code that transforms how you tackle large, complex development tasks.

## The Problem

Claude Code excels at focused tasks but struggles with large, multi-step projects. When you submit one massive prompt trying to accomplish everything, you often get:
- Half-baked implementations
- Incomplete features
- Missed edge cases
- Lost context mid-execution

The core issue: CC lacks a mechanism to break down big goals into properly-sized chunks, track progress, and iteratively complete work.

## The Solution

Orchestrator acts as an intelligent layer around Claude Code that:
- **Collects information** from users about their goals and requirements
- **Breaks down large goals** into appropriately-sized constituent parts
- **Iteratively acts on and completes** these parts with full context
- **Makes intelligent decisions** about when to run files directly vs. delegating to Claude Code
- **Maintains state** across the entire workflow

Think of it as a project manager for Claude Code—turning big ambitions into completed work.

## How It Works

The orchestrator implements an autonomous system that:
- Spawns subagents using `claude -p` (non-interactive mode)
- Tracks full execution state via JSONL event logs
- Manages goal-driven task execution with dependency graphs
- Executes independent tasks in parallel waves (configurable `max_parallel_tasks`)
- Supports dynamic replanning and reflection
- Captures long-running experiment history via the `run_script` tool and surfaces it in reviews
- Decides whether to execute code directly or delegate to CC based on task context

## Architecture

```
orchestrator/
  src/orchestrator/
    models.py           # Pydantic data models
    core/
      orchestrator.py   # Main orchestration loop
      subagent.py       # Claude CLI wrapper
      logger.py         # JSONL event logging
    planning/
      goals.py          # GOALS.md parser
      tasks.py          # Task dependency graph
    cli/
      __init__.py       # CLI entry point
  examples/
    simple_project/     # Test example
```


## Installation

```bash
# Install dependencies
uv sync

# Verify Claude Code CLI is available
claude --version
```

## Usage

### Run Interview (Interactive Goal Setting)

```bash
orchestrate interview --workspace .agentic
```

### Run Orchestrator

```bash
orchestrate run --workspace .agentic --max-iterations 100
```

### Test with Simple Example

```bash
cd examples/simple_project
./setup.sh
python test.py
```

## Key Components

### Orchestrator

Main loop that:
1. Checks goal completion
2. Selects next ready task from dependency graph
3. Spawns subagent to execute task
4. Updates task status based on result
5. Periodically reflects on progress

### Subagent

Wraps Claude Code CLI invocations:
- Uses `-p` flag for non-interactive mode
- Passes structured instructions
- Parses JSON responses with task results
- Logs all events to JSONL

### Event Logger

Provides full traceability:
- Every decision, spawn, completion, error logged
- JSONL format for easy querying
- Trace IDs link parent/child operations

### Goals Manager

Parses GOALS.md to extract:
- Core success criteria (immutable)
- Nice-to-have features (flexible)
- Out of scope items
- Constraints

### Task Graph

NetworkX-based dependency tracking:
- Identifies ready tasks (dependencies met)
- Detects circular dependencies
- Priority-based scheduling

### Parallel Executor

- Uses `ThreadPoolExecutor` to launch multiple Claude Code subagents concurrently
- Honors `max_parallel_tasks` from `orchestrator.config.yaml`
- Ensures TASKS.md writes remain atomic via locks
- Ideal for independent workstreams (e.g., build API + scaffold frontend at once)

### Long-Running Job Queue

- `python -m orchestrator.tools.run_script --mode enqueue --task-id task-001` writes a job request the orchestrator executes outside Claude
- The orchestrator monitors `.agentic/history/jobs/` to start queued commands, stream logs, and block the originating task until they finish
- Critical for multi-hour training runs, migrations, or large builds that would exceed Claude’s time limits

### Auto-Completion of Existing Work

- Before invoking the actor subagent, the orchestrator runs each task’s acceptance criteria and critic checks
- If everything already passes (common in established codebases), the task is auto-accepted without rewriting files
- This lets you resume from partially completed projects or imported repositories without redoing their foundational setup

### Replanner & Experiment History

- When a task exhausts retries, the Replanner agent analyzes reviewer/test feedback and spawns remediation tasks automatically
- Emits `REPLAN` events so you can trace why new work appeared in `TASKS.md`
- Subagents are instructed to enqueue long commands through `python -m orchestrator.tools.run_script --mode enqueue --task-id <task>`
- The orchestrator executes those enqueued jobs outside of Claude, waits for completion, and surfaces experiment logs/metrics under `.agentic/history/`
- If you still want to run a quick command inline, omit `--mode enqueue` to fall back to blocking mode

### Domain Context

- Detects whether the project looks like data science, backend, frontend, or general tooling
- Appends domain-specific guardrails (e.g., leakage/bias checklists for DS, performance/security notes for backend)
- Keeps every subagent aligned with the success criteria of the domain without additional prompting

### Critic (Actor/Critic Loop)

- Every task now flows through an *actor* phase (subagent implementation) followed by a *critic* phase
- The critic verifies coding standards: file naming (snake_case, no spaces), trailing whitespace/tabs, and optional Ruff linting when available
- Findings block task completion until resolved, so existing codebases retain their conventions even during large automated refactors
- Critic feedback is logged alongside reviewer/test results, giving future retries a clear set of corrections to apply

## Claude Code CLI Requirements

Requires Claude Max subscription or Claude Code CLI installed:

```bash
npm install -g @anthropic-ai/claude-code
```

Key flags used:
- `-p`: Non-interactive print mode (exits after response)
- `--output-format json`: Structured output
- `--dangerously-skip-permissions`: No prompts (automation)
- `--add-dir`: Additional working directories
- `--max-turns`: Conversation length limit

## Workspace Structure

```
.agentic/
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
1. When orchestrator starts, it creates `.agentic/current/USER_NOTES.md`
2. Edit this file anytime during execution to provide feedback
3. Before each review, orchestrator checks for new notes
4. Consumed feedback is automatically moved to "Previously Reviewed" section

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
5. **Reflect**: Periodic assessment and replanning
6. **Complete**: All core goals achieved

## Limitations

- Claude Code CLI must be installed and authenticated
- Subagents run with `--dangerously-skip-permissions` (security consideration)
- 10-minute timeout per subagent
- JSON response parsing depends on subagent following format

## Development

```bash
# Run tests
uv run pytest

# Lint code
uv run ruff check src/

# Format code
uv run ruff format src/
```

## License

MIT
