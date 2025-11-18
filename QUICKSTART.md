# Quick Start Guide

## Installation

```bash
cd /Users/kmaurinjones/Documents/projects/github-repos/claude-code-orchestrator
uv tool install .
```

This installs `orchestrate` command globally on your system.

## Usage

### The 3-Step Workflow

```bash
# 1. Create your project directory anywhere
mkdir ~/my-awesome-project
cd ~/my-awesome-project

# 2. Run interview to define goals
orchestrate interview

# 3. Let it build
orchestrate run
```

That's it.

## Parallel Task Execution

The orchestrator automatically parallelizes independent tasks:

- **Intelligent Selection**: Identifies up to 5 tasks (configurable) that don't depend on each other
- **Concurrent Execution**: Spawns multiple Claude Code subagents simultaneously
- **Real-time Updates**: Shows progress as each task completes
- **Faster Completion**: Dramatically reduces total execution time for projects with many independent tasks

Example output:
```
2025-10-26--14-32-15 [ORCHESTRATOR] Selected 5 parallel tasks: task-014, task-015, task-016, task-017, task-018
2025-10-26--14-32-15 [TASK AGENT] Spawning subagent for task-014
2025-10-26--14-32-16 [TASK AGENT] Spawning subagent for task-015
2025-10-26--14-32-16 [TASK AGENT] Spawning subagent for task-016
2025-10-26--14-33-42 [TASK AGENT] ✓ task-015 completed
2025-10-26--14-34-18 [TASK AGENT] ✓ task-014 completed
...
```

## What Happens

### Step 1: Interview

The interview will:
- Ask you about your project goals
- Ask what's nice-to-have vs must-have
- Ask what's out of scope
- Ask about technical constraints

Then it creates:
- `.orchestrator/current/GOALS.md` - Your project goals
- `.orchestrator/current/TASKS.md` - Initial task breakdown

### Step 2: Run

The orchestrator will:
- Parse your goals
- Break them into tasks with dependencies
- Spawn subagents to complete each task
- Track progress in real-time
- Log everything to `.orchestrator/full_history.jsonl`

## Monitoring Progress

### Watch Task Status (In Another Terminal)

```bash
# From your project directory
watch -n 2 cat .orchestrator/current/TASKS.md
```

### View Event Log

```bash
# All events
jq '.' .orchestrator/full_history.jsonl | less

# Only errors
jq 'select(.event=="error")' .orchestrator/full_history.jsonl

# Only completions
jq 'select(.event=="complete")' .orchestrator/full_history.jsonl
```

## Options

### Update Existing Goals and Tasks

```bash
# Update goals/tasks in existing project
orchestrate interview --update
```

This loads your current GOALS.md and TASKS.md and lets you make amendments interactively.

### Run with Custom Settings

```bash
# Increase max iterations (default 100)
orchestrate run --max-iterations 200

# Adjust parallel task execution (default 1)
orchestrate run --max-parallel-tasks 3

# Use different workspace location
orchestrate run --workspace /path/to/.orchestrator

# Combine options
orchestrate run --max-iterations 200 --max-parallel-tasks 10
```

## Example: Hello World Project

```bash
# Create directory
mkdir ~/test-project
cd ~/test-project

# Run interview
orchestrate interview
```

When prompted, enter:
- **Core Goal**: "Create a hello.py script that prints 'Hello World'"
- **Measurable**: "Running `python hello.py` outputs 'Hello World'"
- **Nice-to-have**: "Add timestamp to output"
- **Out of scope**: "Everything else"
- **Constraints**: "Python 3.11+, no dependencies"

Then run:
```bash
orchestrate run --max-iterations 10
```

After ~2-5 minutes, you'll have `hello.py` created and tested.

## Models Used

- **Interview & Planning**: `claude-sonnet` (latest Sonnet)
- **Task Execution**: `claude-haiku` (latest Haiku, cost-effective)

## Troubleshooting

### "Claude Code CLI not found"

Install Claude Code:
```bash
# You need Claude Max subscription
claude --version
```

If not installed, follow: https://docs.claude.com/claude-code

### "Workspace not found"

Run `orchestrate interview` first.

### Tasks not progressing

Check for errors:
```bash
jq 'select(.event=="error") | .payload' .orchestrator/full_history.jsonl
```

### Subagent fails repeatedly

- Check `.orchestrator/full_history.jsonl` for specific errors
- Task may need to be broken into smaller pieces
- Check `TASKS.md` for dependency issues

## Project Structure After Run

```
my-project/
├── .orchestrator/
│   ├── full_history.jsonl      # Complete trace
│   └── current/
│       ├── GOALS.md             # Your goals
│       └── TASKS.md             # Task status
├── src/                         # Generated code (varies by project)
├── tests/                       # Generated tests (if in goals)
└── ... (project files)
```

## Advanced: Manual GOALS.md

Skip interview by creating `.orchestrator/current/GOALS.md` manually:

```markdown
# GOALS.md
Generated: 2025-10-27

## Core Success Criteria (IMMUTABLE)
1. **[Goal Title]**
   - Measurable: [How to verify completion]
   - Non-negotiable: [Why this matters]

## Nice-to-Have (FLEXIBLE)
- Feature 1
- Feature 2

## Out of Scope
- Thing 1

## Constraints (IMMUTABLE)
- Python 3.11+
- No external APIs
```

Then run `orchestrate run`.

## Cost Estimation

Using Claude pricing (approximate):
- **Simple project** (hello world): $0.10 - $0.50
- **Medium project** (CLI tool): $1 - $5
- **Complex project** (web app): $5 - $20

Haiku is used for task execution (cheap), Sonnet only for planning (more expensive but infrequent).

We recommend using a Claude Max subscription for the best experience and to keep costs to a minimum.

## Next Steps

After successful completion:
1. Review generated code
2. Run tests if created
3. Check logs for insights: `.orchestrator/full_history.jsonl`
4. Iterate by adding more goals and running `orchestrate run` again

## Getting Help

```bash
# Show help
orchestrate --help

# Show command-specific help
orchestrate interview --help
orchestrate run --help
```

## Uninstall

```bash
uv tool uninstall claude-code-orchestrator
```
