# Running Scripts and Commands

## CLI Commands

### Main Entry Point

```bash
orchestrate --help
```

**Primary Entry Point**: `orchestrate` (defined in `pyproject.toml` as `orchestrator.cli:main`)

### Subcommands

The orchestrator provides three main subcommands:

#### 1. interview - Interactive Goal Setting

```bash
orchestrate interview --workspace .orchestrator
```

**Purpose**: Start an interactive project setup interview to define goals.

**Implemented in**: `src/orchestrator/cli/__init__.py:main()` (lines 23-213)

**Features**:
- Guides user through goal definition
- Creates `.orchestrator/current/GOALS.md` with structured goals
- Creates `.orchestrator/current/TASKS.md` with decomposed tasks
- Supports `--update` flag to amend existing projects
- Supports `--fresh` flag to ignore existing files

**Example**:
```bash
orchestrate interview --workspace .orchestrator --fresh
```

#### 2. run - Execute Orchestration Loop

```bash
orchestrate run --workspace .orchestrator --max-iterations 100
```

**Purpose**: Main orchestration engine that executes the planning and task execution cycle.

**Implemented in**: `src/orchestrator/cli/__init__.py:main()` (lines 214-281)

**Core Loop**:
1. **Planning Phase**: Decomposes goals into tasks via `Planner.decompose_goals()`
2. **Actor Phase**: Executes tasks via subagent spawning (`ActorPhase.execute()`)
3. **Critic Phase**: Reviews work for quality and acceptance criteria (`CriticPhase.review()`)
4. **Replanning**: Adapts task plan based on feedback via `Replanner.replan()`

**Options**:
- `--min-steps N` - Minimum iterations before checking completion
- `--max-steps N` - Maximum iterations (default: 100)
- `--max-parallel-tasks N` - Parallel task execution limit
- `--surgical` - Run only specific paths
- `--surgical-path PATH` - Specify surgical path

**Example**:
```bash
orchestrate run --workspace .orchestrator --max-steps 50 --max-parallel-tasks 4
```

#### 3. experiment - Schedule Long-Running Tasks

```bash
orchestrate experiment \
  --cmd "python train.py" \
  --run-name "model-v1" \
  --task-id "task-001" \
  --timeout 3600
```

**Purpose**: Queue long-running experiments outside the main orchestrator loop.

**Implemented in**: `src/orchestrator/cli/__init__.py:main()` (lines 283-295)

**Options**:
- `--cmd COMMAND` - Command to execute
- `--run-name NAME` - Experiment identifier
- `--workdir PATH` - Working directory
- `--timeout SECONDS` - Execution timeout
- `--task-id ID` - Associated task ID
- `--metrics-file PATH` - Output metrics location

**Example**:
```bash
orchestrate experiment \
  --cmd "pytest tests/" \
  --run-name "full-test-suite" \
  --task-id "task-002" \
  --timeout 1800
```

### Typical Workflow

```bash
# 1. Start interactive interview to set goals
orchestrate interview --workspace .orchestrator

# 2. Run orchestrator to execute decomposed tasks
orchestrate run --workspace .orchestrator --max-iterations 100

# 3. For long-running commands, use experiment scheduler
orchestrate experiment \
  --cmd "python -m pytest --cov" \
  --run-name "coverage-analysis" \
  --task-id "task-001"
```

### Execution Architecture

**Main Execution Paths**:

1. **CLI Entry Point** (`src/orchestrator/cli/__init__.py:main()`)
   - Argument parsing via argparse
   - Validates workspace and configuration
   - Routes to appropriate subcommand handler

2. **Orchestrator Run Loop** (`src/orchestrator/core/orchestrator.py:Orchestrator.run()`)
   - Manages the core cycle: plan → execute → review → repeat
   - Maintains state in `.orchestrator/current/`
   - Integrates Actor/Critic phases

3. **Subagent Spawner** (`src/orchestrator/core/subagent.py:spawn_subagent()`)
   - Spawns Claude Code CLI subagents for task implementation
   - Uses `claude -p` (non-interactive mode)
   - Parses and validates task results
   - Returns structured execution results

4. **Script Runner Tool** (`src/orchestrator/tools/run_script.py:main()`)
   - Execution: `python -m orchestrator.tools.run_script`
   - Supports `--mode blocking` (synchronous) and `--mode enqueue` (background)
   - Integrates with experiment logger
   - Primary entry point for tests, builds, and heavy computations

---

## Analysis Scripts

### Analyze Codebase Structure

The orchestrator includes Python analysis utilities:

```bash
# List all Python files in src/orchestrator/
find src/orchestrator -name "*.py" -type f | sort

# Show directory tree
tree src/orchestrator/ -I '__pycache__'

# Or using ls recursively
ls -R src/orchestrator/
```

### Generate Import Dependency Graph

For a complete import analysis:

```bash
# This is typically done via the orchestrator planning phase
# but can be run standalone for analysis
python -c "
import ast
import os

for root, dirs, files in os.walk('src/orchestrator'):
    for file in files:
        if file.endswith('.py'):
            filepath = os.path.join(root, file)
            with open(filepath) as f:
                tree = ast.parse(f.read())
                # Process AST here
"
```

---

## Development Commands

### Code Quality

```bash
# Lint with Ruff
ruff check src/ --show-fixes

# Format with Ruff
ruff format src/

# Type check (if mypy is installed)
mypy src/orchestrator/ --ignore-missing-imports
```

### Testing

```bash
# Run unit tests
pytest tests/ -v

# Run specific test
pytest tests/test_orchestrator.py::test_planning -v

# Run with coverage
pytest --cov=src/orchestrator tests/
```

---

## Workspace Management

### Check Workspace Status

```bash
# List current goals
cat .orchestrator/current/GOALS.md

# View task dependency graph
cat .orchestrator/current/TASKS.md

# Check user feedback
cat .orchestrator/current/USER_NOTES.md
```

### View Execution Logs

```bash
# Show subagent logs (JSON format)
ls -la .orchestrator/logs/subagents/

# Show execution history
ls -la .orchestrator/history/

# View specific subagent result
cat .orchestrator/logs/subagents/sub-<id>.json | python -m json.tool
```

---

## Long-Running Jobs

### Enqueue Background Task

```bash
# For commands expected to run >2 minutes
python -m orchestrator.tools.run_script \
  --cmd "python heavy_computation.py" \
  --run-name "analysis-v1" \
  --task-id "task-001" \
  --mode enqueue
```

The orchestrator will:
1. Queue the job
2. Return immediately
3. Monitor completion asynchronously
4. Store results in `.orchestrator/history/`

### Check Long-Running Job Status

```bash
# View queued/completed jobs
cat .orchestrator/history/experiments.jsonl

# Pretty print job metrics
cat .orchestrator/history/experiments.jsonl | jq '.'
```

---

## Documentation Generation

### Update Documentation

Documentation is typically auto-updated by the orchestrator after task completion via `core.docs:DocsManager`.

To manually trigger:

```bash
# The docs maintainer agent handles this:
# python -m orchestrator.core.docs [task_id] [changes_summary]
```

### View Generated Artifacts

```bash
# Check changelog updates
cat CHANGELOG.md | head -30

# View architecture docs
cat docs/architecture.md

# Check refactor analysis
cat refactor-analysis.md
```

---

## Troubleshooting Commands

### Quick Sanity Checks

```bash
# Verify directory structure exists
ls -d src/orchestrator/cli src/orchestrator/core src/orchestrator/planning

# Check module imports are valid
python -m py_compile src/orchestrator/cli/__init__.py
python -m py_compile src/orchestrator/core/orchestrator.py

# Verify pyproject.toml is valid
python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb')))"
```

### Debug Subagent Issues

```bash
# Look at most recent subagent execution
ls -lt .orchestrator/logs/subagents/ | head -5

# Check for errors in latest run
grep -A5 '"errors"' .orchestrator/logs/subagents/sub-*.json | head -30

# View summary of recent runs
jq '.parsed_result.status' .orchestrator/logs/subagents/sub-*.json
```

---

## Environment Variables

```bash
# Set workspace location (defaults to .orchestrator)
export ORCHESTRATOR_WORKSPACE=/path/to/workspace

# Enable debug logging
export DEBUG=1

# Set max iterations
export MAX_ITERATIONS=100
```

