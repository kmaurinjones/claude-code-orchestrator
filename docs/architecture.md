# Orchestrator Architecture

## System Overview

Orchestrator is a CLI wrapper for Claude Code that manages large, complex development tasks through intelligent decomposition, execution, and validation.

### Core Philosophy

Rather than submitting massive tasks to Claude Code at once, Orchestrator:
1. Breaks goals into appropriately-sized subtasks
2. Executes tasks systematically with full context
3. Validates work against acceptance criteria
4. Replans dynamically when tasks fail

## Architecture Layers

### Layer 1: CLI Interface (`cli/`)
- **Entry Point**: `orchestrator.cli:main()`
- Routes commands: `interview`, `run`, `status`
- Manages workspace configuration

### Layer 2: Planning & Execution (`core/`)

#### Planning Phase
- `core.planner:Planner.plan()` - Decomposes goals into tasks
- `core.goal_evaluator:GoalEvaluator` - Validates goal completeness
- `planning/` - GOALS.md and TASKS.md parsing

#### Execution Phase
- `core.actor:ActorPhase.execute()` - Runs tasks via subagents
- `core.subagent:spawn_subagent()` - Spawns Claude Code CLI
- `core.tester:Tester.test()` - Validates acceptance criteria

#### Validation Phase
- `core.critic:CriticPhase.review()` - Reviews work against standards
- `core.reviewer:Reviewer.review()` - Detailed task review
- `core.validators:*` - Specific validator implementations

#### Replanning Phase
- `core.replanner:Replanner.replan()` - Adapts to failures
- Converts failures into remediation tasks

### Layer 3: State Management

- `core.logger:EventLogger` - JSONL event logs
- `core.history:HistoryManager` - Execution history
- `core.feedback:FeedbackTracker` - User feedback system
- `core.experiments:ExperimentRunner` - Long-running job tracking

### Layer 4: Support Services

- `core.docs:DocsManager` - Documentation updates
- `core.changelog:ChangelogManager` - Semantic versioning
- `core.completion_summary:CompletionSummary` - Final reports
- `core.domain_context:DomainContext` - Domain-specific safeguards

## Key Models

All core data structures defined in `models.py`:

- `Goal` - User's high-level objective
- `Task` - Decomposed unit of work
- `TestCase` - Acceptance criteria
- `ExecutionResult` - Outcome of task execution
- `Feedback` - User guidance during execution

## Dependency Graph

See `../refactor-analysis.md` for detailed import dependencies.

**Hub modules** (high outbound dependencies):
- `core.orchestrator` (21 imports) - Central coordination
- `core.planner` (14 imports) - Planning logic
- `core.actor` (6 imports) - Execution

**Leaf modules** (no internal dependencies):
- `core.changelog`, `core.experiments`, `core.feedback`, `core.history`, `core.validators`

## Data Flow

```
CLI Input
    ↓
Parse Goals (.orchestrator/current/GOALS.md)
    ↓
Plan: Decompose → TASKS.md
    ↓
Execute Loop:
  - ActorPhase: Spawn subagent
  - CriticPhase: Review results
  - Test: Validate acceptance criteria
    ↓
  If ALL tests pass → Mark task complete
  If tests fail → Replanner creates remediation tasks
    ↓
After all tasks:
  - Generate CHANGELOG.md
  - Update docs/
  - Print completion summary
    ↓
Output Results
```

## Workspace Structure

```
.orchestrator/
├── current/                    # Active workspace
│   ├── GOALS.md               # Project goals
│   ├── TASKS.md               # Task dependency graph
│   └── USER_NOTES.md          # Live feedback
├── logs/
│   └── subagents/             # Subagent JSON logs
├── history/
│   ├── logs/                  # Long-running job logs
│   └── experiments.jsonl      # Job metrics
└── feedback_history/          # Archived feedback
```

## Extension Points

1. **Custom Validators**: Implement `core.validators:BaseValidator`
2. **Domain Context**: Extend `core.domain_context:DomainContext`
3. **Custom Reviewers**: Extend `core.reviewer:Reviewer`
4. **Task Spawning Logic**: Override `core.planner:Planner.plan()`
