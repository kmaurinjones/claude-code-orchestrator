# Project Documentation

## Overview

This directory contains comprehensive documentation for the **Orchestrator** project—a CLI wrapper for Claude Code designed to handle large, complex development tasks through intelligent decomposition and validation.

## Documentation Structure

- **README.md** (this file) - Documentation overview and quick start
- **architecture.md** - System architecture, layers, and data flow
- **api.md** - Programmatic API reference for library usage
- **scripts.md** - CLI commands and how to run scripts
- **troubleshooting.md** - Common issues, solutions, and debugging tips
- **components/** - Individual component documentation (expanding)

## Development Resources

- **[../refactor-analysis.md](../refactor-analysis.md)** - Complete codebase analysis with dependency graphs
  - Module import dependencies and circular dependency verification
  - Entry points and execution paths
  - Hub and leaf module identification
  - Refactoring recommendations for future improvements

---

## Quick Start

### Installation & Setup

```bash
# Install with uv
uv sync

# Verify installation
orchestrate --version
```

### Basic Usage

```bash
# 1. Start interactive goal interview
orchestrate interview --workspace .orchestrator

# 2. Run orchestrator to execute tasks
orchestrate run --workspace .orchestrator --max-iterations 100

# 3. Check status
orchestrate status --workspace .orchestrator
```

### What It Does

Orchestrator solves a key limitation of Claude Code: handling large, multi-step projects.

**Without Orchestrator**:
- Paste massive prompt to Claude Code
- Result: Incomplete, half-baked work
- Context gets lost mid-execution

**With Orchestrator**:
- Break goal into proper subtasks
- Execute each task with full context
- Validate work against criteria
- Replan when tasks fail
- Generate documentation automatically

---

## Key Concepts

### Goals vs. Tasks

**Goals** are user-provided high-level objectives. Example:
> "Refactor the authentication system from session-based to JWT tokens"

**Tasks** are decomposed, actionable units. From the goal above:
- Task-001: Design JWT token structure
- Task-002: Implement JWT middleware
- Task-003: Migrate existing sessions
- Task-004: Update tests

### Workspace

Orchestrator maintains a `.orchestrator/` directory:

```
.orchestrator/
├── current/
│   ├── GOALS.md          # Your goals
│   ├── TASKS.md          # Task dependency graph
│   └── USER_NOTES.md     # Live feedback
├── logs/
│   └── subagents/        # Subagent execution logs
├── history/
│   ├── logs/             # Long-running job outputs
│   └── experiments.jsonl # Job metrics
└── feedback_history/     # Archived feedback
```

### Acceptance Criteria

Each task has verification criteria:

```markdown
- command_passes: `curl -H 'Authorization: Bearer ...' http://localhost/api`
- pattern_in_file: `src/auth.py` contains `"JWT"`
- file_exists: `src/jwt/middleware.py`
```

If criteria fail, Orchestrator automatically replans remediation tasks.

---

## Architecture Highlights

- **Modular Design**: 31 modules with zero circular dependencies
- **CLI-Driven**: Built as a command-line tool, not a web app
- **Auto-Documentation**: Generates CHANGELOG.md and updates docs/ automatically
- **Failure Recovery**: Replans dynamically when tasks fail
- **Long-Running Jobs**: Supports background execution with `.orchestrator/history/` tracking

See `architecture.md` for detailed system design.

---

## Common Tasks

### Analyze the Codebase

Run the refactor analysis task:

```bash
orchestrate interview \
  --goal "Analyze codebase for refactoring opportunities" \
  --workspace .orchestrator
```

This generates `refactor-analysis.md` with dependency graphs and unused code detection.

### Review Generated Documentation

After task completion, check:
- `CHANGELOG.md` - Semantic versioning of changes
- `docs/` - Updated component and architectural docs
- `refactor-analysis.md` - Dependency and code quality analysis

### Debug Failed Tasks

1. Check `.orchestrator/current/TASKS.md` for failed task and criteria
2. Review `.orchestrator/logs/subagents/` for execution logs
3. Add feedback in `.orchestrator/current/USER_NOTES.md` to redirect execution
4. Orchestrator will pick up feedback and replan

---

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Code Quality

```bash
ruff check src/
ruff format src/
```

### Extending Orchestrator

See `api.md` for details on:
- Custom validators
- Domain-specific safeguards
- Task spawning strategies
- Integration patterns

---

## Version

Current version: **0.8.0** (as of 2025-11-15)

Recent features:
- Actor/Critic architectural refactor
- History recording and feedback TTL
- Parallel task execution
- Replanning on failures
- Production-ready critic

---

## Status: Recent Completion & Known Issues

### Task-001: Codebase Analysis (COMPLETED)

**Status**: ✓ COMPLETED

Successfully created comprehensive `refactor-analysis.md` with:
- Import dependency graph for all 31 modules
- Complete directory structure mapping
- Entry points identification
- Module categorization (hub, leaf, most imported)
- Circular dependency analysis (none found)
- External dependencies documented

Both acceptance criteria verified passing.

### Task-002: Identify Entry Points (PARTIAL)

**Status**: ⚠️ FAILED - Hit max_turns limit (15 turns)

The subagent reached the turn limit before completing verification. However, **both acceptance criteria are already met**:
- ✓ `pyproject.toml` contains `console_scripts` entry
- ✓ `refactor-analysis.md` contains comprehensive "## Entry Points" section

The documentation in `refactor-analysis.md` (lines 134-200) and `scripts.md` fully describes all entry points:
- Main CLI command: `orchestrate`
- Subcommands: `interview`, `run`, `experiment`
- Core execution paths and internal APIs

See `scripts.md` for detailed entry point documentation and `troubleshooting.md` for resolution.

### Task-004: Identify Unused Modules

**Status**: ⚠️ PENDING - Hit max_turns limit (15 turns)

The subagent task-004 was dispatched to identify unused modules (entire files not imported anywhere). While `refactor-analysis.md` was created with substantial content, the required "## Unused Modules" section was not generated before the 15-turn limit was reached.

**Workaround**: Implement a direct Python script using AST parsing to analyze module usage. See `troubleshooting.md` for detailed resolution strategies.

---

## Getting Help

1. **Quick Issues**: Check `troubleshooting.md`
2. **API Questions**: See `api.md`
3. **Commands**: Run `orchestrate --help` or check `scripts.md`
4. **Architecture**: Read `architecture.md` and `refactor-analysis.md`
5. **Debugging**: Check `.orchestrator/logs/subagents/` for detailed execution traces

---

## Contributing

Contributions welcome! Key areas:
- Performance optimization for large codebases
- Additional validators and domain contexts
- Documentation improvements
- Test coverage expansion

Follow the existing patterns in `src/orchestrator/core/` when adding new modules.

---

*Last updated: 2025-11-15*
