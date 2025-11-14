# Orchestrator Project Context

## Project Overview

**Orchestrator** is a CLI wrapper for Claude Code designed to address CC's fundamental limitation with large, complex development tasks.

## The Core Problem

Claude Code excels at focused, well-scoped tasks but struggles when given large, multi-step projects. The typical failure mode:
1. User submits one massive prompt trying to accomplish everything
2. CC attempts to do it all in one shot
3. Results are half-baked, incomplete, or miss critical edge cases
4. Context gets lost mid-execution
5. User ends up with partially-working code

**Root cause**: Claude Code lacks a built-in mechanism to:
- Break down big goals into appropriately-sized chunks
- Track progress across multiple subtasks
- Iteratively complete work while maintaining full context
- Make intelligent decisions about execution strategy

## The Orchestrator Solution

Orchestrator acts as an intelligent project manager layer that wraps Claude Code:

### Core Capabilities
1. **Information Collection**: Gathers comprehensive requirements from users
2. **Goal Decomposition**: Breaks large goals into properly-sized constituent parts
3. **Iterative Execution**: Acts on and completes parts systematically with full context
4. **Smart Execution Decisions**: Chooses when to run files directly vs. delegating to Claude Code
5. **State Management**: Maintains execution state across the entire workflow
6. **Progress Tracking**: Uses dependency graphs and event logs to track completion

### Key Distinction: Run vs. Delegate

A critical feature is the orchestrator's ability to decide:
- **Run directly**: Execute scripts/commands when straightforward
- **Delegate to CC**: Use Claude Code when complex reasoning or code generation is needed

This is often an implicit limitation of using CC alone—knowing when to just run something vs. when to engage the full AI.

## Technical Architecture

- **Subagent spawning**: Uses `claude -p` (non-interactive mode) to spawn task-specific subagents
- **Event logging**: JSONL-based full execution trace for auditability
- **Task dependencies**: NetworkX-based dependency graph for proper ordering
- **Dynamic replanning**: Reflects on progress and adjusts plan as needed
- **State persistence**: Workspace-based state management in `.agentic/` directory

## Current Version

v0.5.21 (as of 2025-10-28)

Recent additions:
- NOTES.md integration for operator guidance
- Script-runner/experiment logger workflow
- Reviewer timeout auto-retries with condensed prompts
- CLI `--version` flag
- Parallel task execution with `ParallelExecutor` and thread-safe TASKS.md writes
- Automated replanning agent that converts failures into remediation tasks
- Domain-aware context builder (DS/backend/frontend/tooling guardrails)
- Long-running job queue: subagents enqueue heavy commands via `run_script --mode enqueue --task-id …`, the orchestrator executes them outside Claude, waits for completion, and logs results in `.agentic/history/`
- Actor/Critic loop: after the actor subagent runs, a strict Critic enforces production-readiness standards (naming, whitespace, docstrings, no bare excepts, no TODOs, no debug prints, no hardcoded secrets, no broken links, Ruff linting) acting as the final quality gate before completion
- Completion summary: when orchestrator finishes (success/max steps/no tasks), generates domain-specific usage guide with CLI commands, configuration, and next steps

## Usage Pattern

```bash
# Start interactive goal-setting interview
orchestrate interview --workspace .agentic

# Run orchestrator with goal decomposition
orchestrate run --workspace .agentic --max-iterations 100
```

## Development Guidelines

When working on orchestrator:
1. Remember this is a CLI tool, not a web application
2. Focus on the orchestration layer, not individual task execution
3. Test with real-world complex projects to validate the decomposition logic
4. Maintain clear separation between orchestrator decisions and subagent work
5. Keep event logs comprehensive for debugging and analysis

## Project Structure

```
orchestrator/
├── src/orchestrator/
│   ├── models.py              # Pydantic data models
│   ├── core/
│   │   ├── orchestrator.py    # Main orchestration loop
│   │   ├── subagent.py        # Claude CLI wrapper
│   │   ├── logger.py          # JSONL event logging
│   │   └── reviewer.py        # Review/validation logic
│   ├── planning/
│   │   ├── goals.py           # GOALS.md parser
│   │   └── tasks.py           # Task dependency graph
│   └── cli/
│       └── __init__.py        # CLI entry point
├── examples/                   # Test cases
├── .agentic/                  # Workspace directory
└── sessions/                  # Development session logs
```

## Key Files to Know

- `src/orchestrator/core/orchestrator.py` - Main loop and decision logic
- `src/orchestrator/core/subagent.py` - Claude Code CLI wrapper
- `src/orchestrator/core/reviewer.py` - Task review and validation
- `src/orchestrator/core/feedback.py` - User feedback tracking system
- `.agentic/current/GOALS.md` - Project goals in workspace
- `.agentic/current/TASKS.md` - Task dependency graph
- `.agentic/current/USER_NOTES.md` - Live user feedback during execution

## User Feedback System

As of v0.5.22+, orchestrator supports live user feedback during execution:

**How it works:**
- Orchestrator creates `.agentic/current/USER_NOTES.md` at startup
- Users edit this file during execution to provide feedback
- Before each task review, orchestrator checks for new notes
- Consumed feedback is injected into reviewer prompt and archived

**Feedback format:**
```markdown
## New Notes (Write here - will be consumed on next review)

- [task-003] Use POST instead of GET for this endpoint
- [general] Prioritize error handling over new features
```

**Use cases:**
- Redirect implementation approach mid-execution
- Provide domain-specific constraints the AI doesn't know
- Course-correct when a task is going off-track
- Add priority guidance without stopping the orchestrator

**Implementation details:**
- `FeedbackTracker` class tracks file mtime and content changes
- Section-based parsing with automatic archiving prevents re-processing
- Task-specific feedback (`[task-id]`) routes to that task's review
- General feedback (`[general]`) applies to all subsequent reviews

## Automatic Documentation & Changelog

As of v0.5.22+, orchestrator automatically maintains project documentation:

**CHANGELOG.md**
- Semantic versioning automatically incremented based on change type
- Categories: Added, Changed, Fixed, Removed, Attempted (for failures)
- Version bumping logic:
  - MAJOR: Breaking changes (Removed, Deprecated)
  - MINOR: New features (Added, Changed)
  - PATCH: Bug fixes (Fixed, Security, Attempted)

**docs/ directory**
- Maintained by dedicated documentation subagent
- Updates after each task completion or failure
- Intelligent routing: architecture changes update architecture.md, scripts update scripts.md, etc.
- Failed attempts documented in troubleshooting.md

**Implementation:**
- `ChangelogManager` handles semantic versioning and changelog updates
- `DocsManager` spawns documentation subagent to update relevant files
- Integrated into orchestrator workflow after task completion
- Uses Haiku for cost-efficient docs updates, Sonnet for comprehensive docs generation

## Testing Philosophy

Test with realistic complex projects that would normally fail with a single CC prompt:
- Multi-component applications
- Projects requiring research + implementation
- Tasks with unclear requirements needing clarification
- Workflows with multiple interdependent steps

The orchestrator should turn these from "impossible with one prompt" into "systematically completed."
