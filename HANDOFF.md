# Orchestrator Development Handoff

**Date**: 2025-11-13
**From**: Initial implementation agent
**To**: Advanced coding agent
**Project**: Orchestrator - Claude Code wrapper for complex multi-step projects

---

## Context You Already Have

You know orchestrator is a CLI wrapper for Claude Code that:
- Breaks large goals into tasks
- Executes tasks via Claude Code subagents
- Reviews work and maintains state
- Addresses CC's limitation with half-baked large projects

---

## What Was Completed Today

### ✅ Feature 1: User Feedback System (100% Complete)
**Files**: `src/orchestrator/core/feedback.py`

Live feedback during execution via `.agentic/current/USER_NOTES.md`. Works perfectly. No action needed.

### ✅ Feature 2: Documentation & Changelog (100% Complete)
**Files**:
- `src/orchestrator/core/changelog.py`
- `src/orchestrator/core/docs.py`

Automatic CHANGELOG.md and docs/ maintenance with semantic versioning. Works perfectly. No action needed.

### ✅ Feature 3a: Goal Evaluator (100% Complete)
**Files**: `src/orchestrator/core/goal_evaluator.py`

Goal completion is now data-driven:
- `GoalEvaluatorRegistry` evaluates goals using adapters
- `TestSuiteEvaluator` - runs pytest/npm test
- `MetricThresholdEvaluator` - checks DS metrics (accuracy >= 0.95)
- `APIContractEvaluator` - validates OpenAPI specs
- Wired into `orchestrator.py:_check_completion()` (lines 492-546)

**Status**: Fully integrated and working. No action needed.

### ✅ Feature 3b: Rich Validators (100% Complete)
**Files**: `src/orchestrator/core/validators.py`, `src/orchestrator/core/tester.py`

Extended verification checks from 3 to 9 types:
- `HTTPEndpointValidator` - Check API status codes
- `MetricThresholdValidator` - Verify metric thresholds
- `SchemaValidator` - JSON Schema validation
- `SecurityScanValidator` - bandit, eslint, safety, npm audit
- `TypeCheckValidator` - mypy, pyright, tsc
- `DataQualityValidator` - nulls, duplicates, ranges

All wired into `Tester.run()` (lines 31-260).

**Status**: Fully integrated and working. No action needed.

---

## What Needs Your Work

### 🔴 CRITICAL 1: Integrate Parallel Execution into Run Loop

**Problem**: Orchestrator still runs one task at a time despite logging `max_parallel_tasks`.

**What I Built**:
- `src/orchestrator/core/parallel_executor.py` - Complete parallel execution infrastructure
- `ParallelExecutor` class with ThreadPoolExecutor
- `execute_tasks_parallel()` method ready to use
- `get_ready_tasks_batch()` for fetching multiple ready tasks

**What You Need to Do**:

1. **Modify `orchestrator.py` run loop** (currently lines 85-111):

```python
# CURRENT (sequential):
while self.current_step < self.max_steps:
    task = self._get_next_task()  # Gets ONE task
    if not task:
        return "NO_TASKS_AVAILABLE"
    self._process_task(task)

# NEEDED (parallel):
from .parallel_executor import ParallelExecutor, get_ready_tasks_batch

executor = ParallelExecutor(max_parallel=self.max_parallel_tasks)

while self.current_step < self.max_steps:
    # Get multiple ready tasks
    ready_tasks = get_ready_tasks_batch(
        self.tasks,
        max_count=self.max_parallel_tasks,
        exclude_ids=currently_running_task_ids  # Track active tasks
    )

    if not ready_tasks:
        return "NO_TASKS_AVAILABLE"

    # Execute in parallel
    result = executor.execute_tasks_parallel(
        ready_tasks,
        process_func=self._process_task
    )

    # Increment step counter
    self.current_step += result['completed'] + result['failed']
```

2. **Handle Thread Safety**:
   - `self.tasks.save()` is called in `_process_task()` - add a lock:
     ```python
     # In __init__:
     import threading
     self._task_save_lock = threading.Lock()

     # In _process_task() after task updates:
     with self._task_save_lock:
         self.tasks.save()
     ```

3. **Track Active Tasks**:
   - Add `self._active_tasks: Set[str] = set()` to prevent re-queueing running tasks
   - Update when tasks start/complete

4. **Test**:
   - Create project with 3+ independent tasks
   - Set `max_parallel_tasks=3` in config
   - Verify concurrent execution (check timestamps in logs)

**Files to Modify**:
- `src/orchestrator/core/orchestrator.py` (lines 85-111, __init__)

**Estimated Time**: 1-2 hours

**Risk**: Medium. Main concern is race conditions on TASKS.md writes. The lock should handle it.

---

### 🔴 CRITICAL 2: Implement Replan-Based Failure Handling

**Problem**: When tasks fail, orchestrator just retries the same prompt until exhausted. Never spawns remediation tasks.

**What's Needed**:

1. **Create `src/orchestrator/core/replanner.py`**:

```python
"""Replanner - generates remediation tasks from failures."""

from typing import List, Dict, Any
from ..models import Task, TaskStatus
from .subagent import Subagent
from .logger import EventLogger

class Replanner:
    """Analyzes failures and generates follow-up tasks."""

    def __init__(self, project_root: Path, logger: EventLogger):
        self.project_root = project_root
        self.logger = logger

    def analyze_failure(
        self,
        failed_task: Task,
        review_feedback: ReviewFeedback,
        test_results: List[TestResult],
    ) -> List[Task]:
        """
        Generate remediation tasks from failure.

        Returns list of new Task objects to inject into graph.
        """
        # Use subagent to analyze and propose tasks
        prompt = f'''You are the replanner. A task failed and needs remediation.

## Failed Task
- ID: {failed_task.id}
- Title: {failed_task.title}
- Attempts: {failed_task.attempt_count}
- Review: {review_feedback.summary}
- Test Failures: {len([t for t in test_results if not t.passed])}/{len(test_results)}

## Analysis Needed
1. Why did this fail?
2. What follow-up tasks would fix it?
3. Should we try a different approach?

## Output Format
Respond with JSON array of remediation tasks:
```json
[
  {{
    "title": "Fix test_user_login failure",
    "description": "Test is failing because...",
    "priority": 8,
    "depends_on": []
  }},
  ...
]
```

Generate 1-3 focused remediation tasks. Make them specific and actionable.
'''

        agent = Subagent(
            task_id=f"replan-{failed_task.id}",
            task_description=prompt,
            context=self._build_context(failed_task, test_results),
            parent_trace_id="replan",
            logger=self.logger,
            step=0,
            workspace=self.project_root,
            max_turns=10,
            model="sonnet",  # Use sonnet for better planning
        )

        result = agent.execute()

        # Parse task proposals and create Task objects
        # ... implementation details

        return new_tasks
```

2. **Modify `orchestrator.py:_process_task()`** (currently lines 124-175):

```python
# CURRENT:
if task.status != TaskStatus.COMPLETE:
    task.status = TaskStatus.FAILED
    console.print(f"[red]... exhausted attempts")
    self._update_docs_and_changelog(task, review_feedback, success=False)

# NEEDED:
if task.status != TaskStatus.COMPLETE:
    task.status = TaskStatus.FAILED
    console.print(f"[red]... exhausted attempts")

    # Generate remediation tasks
    from .replanner import Replanner
    replanner = Replanner(self.project_root, self.logger)

    remediation_tasks = replanner.analyze_failure(
        task,
        review_feedback,
        test_results
    )

    if remediation_tasks:
        console.print(f"[yellow]REPLAN: Generated {len(remediation_tasks)} remediation tasks")
        for new_task in remediation_tasks:
            self.tasks.add_task(new_task)  # Inject into graph
            self._log_event(EventType.REPLAN, {
                "original_task": task.id,
                "new_task": new_task.id,
                "reason": "failure_remediation"
            })

    self._update_docs_and_changelog(task, review_feedback, success=False)
```

3. **Add REPLAN to EventType** in `models.py`:
```python
class EventType(str, Enum):
    # ... existing ...
    REPLAN = "replan"
```

4. **Add `TaskGraph.add_task()` method** in `planning/tasks.py`:
```python
def add_task(self, task: Task) -> None:
    """Add a new task to the graph dynamically."""
    self._tasks[task.id] = task
    self.save()
```

**Files to Create**:
- `src/orchestrator/core/replanner.py`

**Files to Modify**:
- `src/orchestrator/core/orchestrator.py` (lines 168-175)
- `src/orchestrator/models.py` (add REPLAN to EventType)
- `src/orchestrator/planning/tasks.py` (add add_task method)

**Estimated Time**: 2-3 hours

**Risk**: Low. Replanner is isolated, worst case it generates bad tasks that also fail.

**Important**: Add max replan depth (e.g., don't replan more than 2 levels deep) to prevent infinite loops.

---

### 🟡 MEDIUM PRIORITY: Integrate Experiment Logger

**Problem**: Subagent uses single Claude CLI call with 10-min timeout. Long commands (training, builds) risk timeout without resumable logs.

**What's Needed**:

1. **Update `orchestrator.py:_build_task_agent_prompt()`** (currently lines 402-470):

Add stronger guidance about run_script:

```python
## Guidelines
- Work incrementally and keep changes minimal but functional.
- **For commands taking >2 minutes, use the script runner:**
  ```
  python -m orchestrator.tools.run_script --cmd "python train.py" --run-name "experiment-1"
  ```
  This captures logs to `.agentic/history/YYYY-MM-DD--HH-MM-SS/` for later review.

- Long-running commands that MUST use script runner:
  * Model training
  * Large test suites (>100 tests)
  * Database migrations
  * Build/deploy operations
  * Data processing pipelines

- The script runner provides:
  * Resumable execution
  * Metric logging (write metrics.json to run directory)
  * Artifact capture
  * Timeout protection
```

2. **Update `reviewer.py:_build_reviewer_task_description()`** (currently lines 64-97):

Add experiment history section:

```python
## Recent Experiments
{self._get_experiment_history()}

## Task Summary
...
```

And add method:

```python
def _get_experiment_history(self) -> str:
    """Get recent experiment runs from .agentic/history/"""
    history_dir = self.project_root / ".agentic" / "history"

    if not history_dir.exists():
        return "No experiments recorded."

    # Get most recent 5 runs
    runs = sorted(history_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:5]

    lines = []
    for run_dir in runs:
        metrics_file = run_dir / "metrics.json"
        if metrics_file.exists():
            metrics = json.loads(metrics_file.read_text())
            lines.append(f"- {run_dir.name}: {metrics}")

    return "\n".join(lines) if lines else "No experiment metrics found."
```

**Files to Modify**:
- `src/orchestrator/core/orchestrator.py` (lines 402-470)
- `src/orchestrator/core/reviewer.py` (add method, update prompt)

**Estimated Time**: 1 hour

**Risk**: Very low. Just prompt changes and reading existing logs.

---

### 🟢 LOW PRIORITY: Domain-Specific Context

**Problem**: All subagents get generic prompts. Should include DS-specific checks (leakage), backend-specific constraints (perf budgets), etc.

**What's Needed**:

1. **Create `src/orchestrator/core/domain_context.py`**:

```python
"""Domain detection and context generation."""

from pathlib import Path
from typing import Optional

class DomainDetector:
    """Detect project domain from structure and goals."""

    @staticmethod
    def detect(project_root: Path, goals: List[Goal]) -> str:
        """Returns 'data_science', 'backend', 'frontend', or 'tooling'."""

        # Check for DS indicators
        has_notebooks = list(project_root.glob("**/*.ipynb"))
        has_training = list(project_root.glob("**/train*.py"))
        ds_keywords = ["model", "dataset", "accuracy", "precision", "training"]

        if has_notebooks or has_training:
            return "data_science"
        if any(kw in str(goals).lower() for kw in ds_keywords):
            return "data_science"

        # Check for backend
        has_fastapi = (project_root / "main.py").exists()
        has_api = list(project_root.glob("**/api/**/*.py"))

        if has_fastapi or has_api:
            return "backend"

        # Check for frontend
        has_react = (project_root / "package.json").exists()
        if has_react:
            return "frontend"

        return "tooling"

class DomainContext:
    """Build domain-specific context for subagents."""

    @staticmethod
    def build_ds_context(project_root: Path) -> str:
        return """
## Data Science Guidelines (CRITICAL)
- **Data Leakage Check**: Ensure target variable not in features
- **Train/Test Split**: Verify no overlap, use stratification if imbalanced
- **Temporal Leakage**: No future data in training set
- **Bias Check**: Examine protected attributes for disparate impact
- **Metric Selection**: Use appropriate metrics for problem type
- **Reproducibility**: Set random seeds for deterministic results

## Dataset Info
{self._get_dataset_info(project_root)}
"""

    @staticmethod
    def build_backend_context(project_root: Path) -> str:
        return """
## Backend Engineering Guidelines
- **Security**: Validate all inputs, sanitize SQL, no hardcoded secrets
- **Performance**: Response time <200ms for APIs, <1s for complex queries
- **Error Handling**: Return proper HTTP codes, log errors with context
- **Testing**: Unit tests for logic, integration tests for endpoints
- **Dependencies**: Pin versions, check for vulnerabilities
"""

    @staticmethod
    def build_tooling_context(project_root: Path) -> str:
        return """
## Tooling Guidelines
- **CLI Design**: Clear help text, sensible defaults, --version flag
- **Error Messages**: Actionable, include command to fix
- **Testing**: Test edge cases, error conditions, help text
- **Compatibility**: Support Python 3.9+, handle missing dependencies gracefully
"""
```

2. **Use in `orchestrator.py:_gather_context()`** (currently lines 404-435):

```python
def _gather_context(self, task: Task) -> str:
    # ... existing context ...

    # Add domain-specific context
    from .domain_context import DomainDetector, DomainContext

    domain = DomainDetector.detect(self.project_root, list(self.goals.core_goals))

    if domain == "data_science":
        context_lines.append(DomainContext.build_ds_context(self.project_root))
    elif domain == "backend":
        context_lines.append(DomainContext.build_backend_context(self.project_root))
    # etc.

    return "\n".join(context_lines)
```

**Files to Create**:
- `src/orchestrator/core/domain_context.py`

**Files to Modify**:
- `src/orchestrator/core/orchestrator.py` (lines 404-435)

**Estimated Time**: 1-2 hours

**Risk**: Very low. Just appends to context, doesn't change behavior.

---

## Testing Strategy

After implementing each feature:

### Test Parallel Execution:
```bash
cd examples/
mkdir parallel_test
cd parallel_test

# Create GOALS.md with 3 independent tasks
cat > .agentic/current/GOALS.md << EOF
# Goals
- Create file A
- Create file B
- Create file C
EOF

# Create TASKS.md with 3 independent tasks
cat > .agentic/current/TASKS.md << EOF
task-001 | Create file A | BACKLOG | [] | []
task-002 | Create file B | BACKLOG | [] | []
task-003 | Create file C | BACKLOG | [] | []
EOF

# Set max_parallel_tasks=3 in config
cat > .agentic/orchestrator.config.yaml << EOF
max_parallel_tasks: 3
max_steps: 50
EOF

# Run and check logs for concurrent execution
orchestrate run --workspace .agentic

# Verify: Timestamps should show tasks starting ~simultaneously
grep "Selected task:" .agentic/full_history.jsonl
```

### Test Replanning:
```bash
# Create task that will fail
cat > .agentic/current/TASKS.md << EOF
task-001 | Make tests pass | BACKLOG | [] | []
  acceptance:
    - type: command_passes
      target: pytest tests/test_impossible.py
EOF

# Create test file that always fails
mkdir tests
cat > tests/test_impossible.py << EOF
def test_impossible():
    assert False, "This test always fails"
EOF

# Run orchestrator
orchestrate run --workspace .agentic

# Check: Should see REPLAN events and new remediation tasks created
grep "REPLAN" .agentic/full_history.jsonl
grep "Generated.*remediation tasks" logs
```

---

## Important Notes

### What's Working Well (Don't Touch):
1. **Goal Evaluator** - Fully wired, tested, works perfectly
2. **Rich Validators** - All 9 types working in Tester
3. **Feedback System** - USER_NOTES.md parsing and integration complete
4. **Docs/Changelog** - Automatic maintenance working

### Common Pitfalls:

1. **Thread Safety**:
   - TASKS.md writes need locks in parallel mode
   - Event logger writes need ordering

2. **Infinite Replan Loops**:
   - Add max replan depth (2-3 levels)
   - Track replan ancestry in task metadata

3. **Experiment Logger**:
   - Don't force run_script for everything
   - Only recommend for commands >2 min

4. **Domain Detection**:
   - Should be conservative (default to "tooling")
   - Can check .gitignore, package files, etc.

### Code Style:
- Use type hints
- Add docstrings to public methods
- Import validators/helpers inside methods to avoid circular deps
- Console print format: `[color]{_timestamp()} [COMPONENT][/color] Message`
- Log events for major decisions (REPLAN, PARALLEL_START, etc.)

---

## Files Summary

### Created Today (Complete):
- `src/orchestrator/core/feedback.py` ✅
- `src/orchestrator/core/changelog.py` ✅
- `src/orchestrator/core/docs.py` ✅
- `src/orchestrator/core/goal_evaluator.py` ✅
- `src/orchestrator/core/validators.py` ✅
- `src/orchestrator/core/parallel_executor.py` ⚙️ (ready to use)

### Need to Create:
- `src/orchestrator/core/replanner.py` ❌
- `src/orchestrator/core/domain_context.py` ❌ (optional)

### Need to Modify:
- `src/orchestrator/core/orchestrator.py` - Parallel loop, replanning, experiment history
- `src/orchestrator/core/reviewer.py` - Experiment history
- `src/orchestrator/models.py` - Add REPLAN event type
- `src/orchestrator/planning/tasks.py` - Add add_task() method

---

## Documentation to Update After Your Work

1. **README.md** - Add parallel execution and replanning features
2. **IMPLEMENTATION_PLAN.md** - Mark completed phases
3. **STATUS_REPORT.md** - Update completion status
4. **CLAUDE.md** - Add implementation notes for new features

---

## Questions / Clarifications

If you need clarification:
1. Check `STATUS_REPORT.md` for detailed analysis
2. Check `IMPLEMENTATION_PLAN.md` for overall architecture
3. Read `CLAUDE.md` for project philosophy
4. Existing code has good docstrings and comments

---

## Success Criteria

You'll know you're done when:

**Parallel Execution**:
- [ ] Multiple independent tasks execute concurrently
- [ ] Logs show overlapping execution timestamps
- [ ] No race conditions on TASKS.md writes
- [ ] Event log maintains correct order

**Replanning**:
- [ ] Failed tasks trigger replan analysis
- [ ] New remediation tasks appear in TASKS.md
- [ ] REPLAN events logged
- [ ] No infinite replan loops

**Experiment Logger** (bonus):
- [ ] Subagent prompt recommends run_script for long commands
- [ ] Reviewer sees experiment history
- [ ] Long commands log to .agentic/history/

---

## Estimated Total Time

- Parallel execution: 1-2 hours
- Replanning: 2-3 hours
- Experiment logger: 1 hour
- Testing: 1 hour
- Documentation: 30 min

**Total: 5.5-7.5 hours** for complete implementation

---

## Final Notes

The hard work is done - goal evaluation and rich validators are complete and working. What remains is:
1. Wiring parallel execution (infrastructure exists)
2. Implementing replanner (pattern is clear from existing code)
3. Minor prompt updates for experiment logger

All the patterns you need exist in the codebase. The parallel_executor is ready to use. The subagent pattern is well-established (see reviewer.py, docs.py). Just follow the patterns and you'll be fine.

Good luck! 🚀
