# Troubleshooting Guide

## Common Issues and Solutions

### Task Execution Failures

#### Task-001: Map Complete Source Directory Structure (COMPLETED)

**Status**: ✓ COMPLETED - Both acceptance criteria passed

**What Happened**:
- Subagent task-001 was dispatched to map the complete source directory structure
- The subagent successfully created comprehensive `refactor-analysis.md` with:
  - Complete import dependency graph for all 31 modules
  - Entry points identification
  - Module dependency analysis
  - Circular dependency detection (none found)
  - Full directory structure mapping
  - Module categorization (hub, leaf, most imported)
- Both acceptance criteria verified:
  - ✓ Source directory can be listed (`ls -R src/orchestrator/`)
  - ✓ Pattern "## Directory Structure" found in `refactor-analysis.md`

**What Was Delivered**:
- Complete directory structure of `src/orchestrator/` with full file tree
- 31 Python files mapped and documented with categorization
- Module statistics: Total files, package directories, categorized by subdirectory
- File categorization: Hub modules, leaf modules, and most imported modules
- External dependencies documented
- Clear hierarchical structure presentation organized by subdirectory (cli, core, planning, tools)

**Artifacts Created**:
- `refactor-analysis.md` - Comprehensive analysis report

**Files Affected**:
- None modified (task was analysis-only, created new report)

---

#### Task-002: Identify All Entry Points (FAILED)

**Status**: ✗ FAILED - Hit max_turns limit (15 turns)

**What Happened**:
- Subagent task-002 was dispatched to identify all entry points (CLI commands, main execution paths)
- The task had two acceptance criteria:
  1. Pattern "console_scripts" in `pyproject.toml`
  2. Pattern "## Entry Points" in `refactor-analysis.md`
- The subagent reached the 15-turn limit before completing the task verification
- Both criteria files already existed with the required patterns (from task-001 completion)

**Trace Information**:
- Subagent ID: `sub-81351a95`
- Duration: 29.45 seconds
- Turns completed: 15/15 (max limit reached)
- Result: `error_max_turns`

**Root Cause**:
- Insufficient turn budget allocated to verification task
- The task was trying to complete work that had already been partially included in task-001

**Current State - Acceptance Criteria Actually Met**:
- ✓ `pyproject.toml` contains: `orchestrate = "orchestrator.cli:main"` (line 25)
- ✓ `refactor-analysis.md` contains comprehensive "## Entry Points" section (lines 134-200) with:
  - Console script definitions
  - CLI subcommands (interview, run, experiment)
  - Main execution paths
  - Actor/Critic loop architecture
  - Planning system entry points

**Entry Points Documented**:
1. **Console Script**: `orchestrate = "orchestrator.cli:main"`
2. **CLI Subcommands**:
   - `interview` - Interactive project setup
   - `run` - Main orchestration loop executor
   - `experiment` - Long-running experiment scheduler
3. **Core Execution Paths**:
   - `src/orchestrator/cli/__init__.py:main()` - CLI argument parsing and routing
   - `src/orchestrator/core/orchestrator.py:Orchestrator.run()` - Main orchestration engine
   - `src/orchestrator/core/subagent.py:spawn_subagent()` - Subagent spawner for task execution
   - `src/orchestrator/tools/run_script.py:main()` - Script runner for long-running commands
   - Actor/Critic loop (Actor → Critic for quality gates)
   - Planning system (Planner → Replanner for adaptive tasks)

**Resolution**:
The acceptance criteria are already met by the existing `refactor-analysis.md`. To mark this task as complete:

1. **Option 1 (Manual Verification)**: Run verification commands
   ```bash
   grep -n "console_scripts" pyproject.toml
   grep -n "## Entry Points" refactor-analysis.md
   ```

2. **Option 2 (Re-run with More Turns)**: Re-run task-002 with increased turn budget (20-25 turns)

3. **Recommended Status**: Task can be considered COMPLETE as the deliverable already exists with both acceptance criteria met

**Artifacts Existing**:
- `refactor-analysis.md` - Contains complete entry point documentation
- `pyproject.toml` - Contains console_scripts definition

**Files Affected**:
- None modified (task failed before verification completion)

---

### Task Timeout/Max Turns

**Symptom**: Subagent completes with `subtype: error_max_turns`

**Causes**:
1. Turn budget exhausted before task completion
2. Task too broad for allocated turns
3. Inefficient tool usage (excessive retries, redundant searches)

**Prevention**:
- Pre-plan complex tasks with explicit step enumeration
- Use shorter prompts with higher focus for subagents
- Parallelize independent analysis tasks
- Cache results between invocations

---

### Documentation Generation

**Note**: Documentation task (docs-task-002) also hit max_turns but was primarily for updating docs after task-001 completion. Focus on completing the core analysis first.

---

#### Task-004: Identify Unused Modules (FAILED)

**Status**: ✗ FAILED - Hit max_turns limit (15 turns)

**What Happened**:
- Subagent task-004 was dispatched to identify unused modules (entire files not imported anywhere)
- Acceptance criteria required:
  1. `## Unused Modules` section in `refactor-analysis.md`
  2. File exists verification for `refactor-analysis.md`
- The subagent ran for 15 turns (62.75 seconds) but did not complete the analysis and report generation
- The `refactor-analysis.md` file exists with substantial content (import graph, entry points, directory structure) but lacks the required "## Unused Modules" section

**Root Cause**:
- Insufficient turn budget for comprehensive module analysis
- Turn limit exhausted before analysis could be completed and documented

**Resolution**:
To complete this task, consider:
1. **Increase turn budget**: Allocate 20-25 turns for complete unused module analysis
2. **Script-based approach**: Create a dedicated Python script to analyze module usage instead of relying on agent-based analysis
3. **Break down scope**: Separate module collection from analysis from reporting phases

**Artifacts Created**:
- `refactor-analysis.md` (partial) - Missing "## Unused Modules" section

**Files Affected**:
- None modified (task was analysis-only)

**Next Steps**:
- Implement a direct analysis script using AST parsing to identify unused modules
- Add the missing section to `refactor-analysis.md` with findings
- Once complete, verify task passes acceptance criteria checks

---

## Development Workflow Tips

### Running Analysis Tasks

For tasks that analyze the entire codebase:

```bash
# Quick check of specific module
python -c "import ast; print(ast.parse(open('src/orchestrator/core/orchestrator.py').read()).body)"

# Find all imports in a file
grep -n "^import\|^from" src/orchestrator/core/*.py | head -50
```

### Validating Changes

Always run:
1. Type checking: `mypy src/` (if configured)
2. Linting: `ruff check src/`
3. Format: `ruff format src/`

---

## Workspace Structure

Understanding `.orchestrator/` directory:

- `.orchestrator/current/GOALS.md` - Current project goals
- `.orchestrator/current/TASKS.md` - Task dependency graph with verification criteria
- `.orchestrator/logs/subagents/` - JSON logs from subagent executions
- `.orchestrator/history/` - Long-running job results and experiment metrics

---

## Getting Help

1. Check recent session logs: `sessions/2025-11-15.md`
2. Review subagent logs: `.orchestrator/logs/subagents/*.json`
3. Inspect execution trace: `parsed_result` field in subagent logs
4. Review task verification criteria: `.orchestrator/current/TASKS.md`
