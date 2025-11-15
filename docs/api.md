# Orchestrator API Reference

## Overview

This document describes the main programmatic API for Orchestrator. While Orchestrator is primarily a CLI tool, it can be imported and used as a library.

---

## Core Classes

### Orchestrator

Main orchestration engine.

```python
from orchestrator.core.orchestrator import Orchestrator
from orchestrator.models import Goal

# Initialize orchestrator
orch = Orchestrator(workspace_path=".orchestrator")

# Run orchestration
result = orch.run(max_iterations=100, goals=[
    Goal(title="Complete codebase analysis", description="...")
])
```

**Methods**:
- `run(max_iterations: int, goals: List[Goal]) -> OrchestrationResult`
- `load_workspace()` - Load state from `.orchestrator/` directory
- `save_workspace()` - Persist state to disk

---

### Actor

Executes individual tasks via subagents.

```python
from orchestrator.core.actor import ActorPhase
from orchestrator.models import Task

actor = ActorPhase(workspace_path=".orchestrator")
result = actor.execute(task)
```

**Methods**:
- `execute(task: Task) -> ExecutionResult` - Run a single task
- `spawn_subagent(task: Task) -> SubagentResult` - Dispatch to Claude Code

---

### Critic

Reviews and validates work.

```python
from orchestrator.core.critic import CriticPhase

critic = CriticPhase()
review = critic.review(execution_result, task)
```

**Methods**:
- `review(result: ExecutionResult, task: Task) -> ReviewResult`
- `check_standards(code: str) -> List[Issue]` - Check code quality

---

### Planner

Decomposes goals into tasks.

```python
from orchestrator.core.planner import Planner
from orchestrator.models import Goal

planner = Planner(workspace_path=".orchestrator")
tasks = planner.plan(goals=[Goal(...)])
```

**Methods**:
- `plan(goals: List[Goal]) -> List[Task]` - Decompose goals
- `rank_by_dependency(tasks: List[Task]) -> List[Task]` - Order tasks

---

## Models

All data models in `orchestrator.models`:

### Goal

```python
from orchestrator.models import Goal

goal = Goal(
    title="Refactor authentication system",
    description="Move from session-based to JWT auth",
    acceptance_criteria=[
        "API endpoints accept JWT tokens",
        "Session-based code removed",
        "Tests pass",
    ]
)
```

**Fields**:
- `title: str` - Goal name
- `description: str` - Detailed description
- `acceptance_criteria: List[str]` - Success conditions
- `priority: float` - Priority score (0-10)

### Task

```python
from orchestrator.models import Task, TestCase

task = Task(
    task_id="task-001",
    title="Implement JWT middleware",
    description="...",
    test_cases=[
        TestCase(
            name="JWT tokens accepted",
            check_type="command_passes",
            check_value="curl -H 'Authorization: Bearer ...' http://localhost:8000/api"
        )
    ],
    dependencies=["task-000"],
    priority=10
)
```

**Fields**:
- `task_id: str` - Unique identifier
- `title: str` - Task name
- `description: str` - Detailed description
- `test_cases: List[TestCase]` - Acceptance criteria
- `dependencies: List[str]` - Task IDs this depends on
- `priority: float` - Priority (0-10)

### TestCase

```python
from orchestrator.models import TestCase

test = TestCase(
    name="API returns 200",
    check_type="command_passes",  # or "pattern_in_file", "file_exists"
    check_value="curl http://localhost:8000/health"
)
```

**Check Types**:
- `command_passes` - Command exits with code 0
- `pattern_in_file` - Pattern exists in file
- `file_exists` - File path exists
- `pattern_not_in_file` - Pattern NOT in file

### ExecutionResult

```python
from orchestrator.models import ExecutionResult, TaskStatus

result = ExecutionResult(
    task_id="task-001",
    status=TaskStatus.COMPLETED,
    output="Task completed successfully",
    duration_seconds=120.5,
    files_created=["src/auth/jwt.py"],
    files_modified=["src/auth/__init__.py"],
    commands_run=["pytest", "ruff check"]
)
```

---

## Utility Classes

### EventLogger

Log events in JSONL format.

```python
from orchestrator.core.logger import EventLogger

logger = EventLogger(workspace_path=".orchestrator")
logger.log_event("task_started", task_id="task-001")
logger.log_event("task_completed", task_id="task-001", duration=120.5)
```

### FeedbackTracker

Track user feedback during execution.

```python
from orchestrator.core.feedback import FeedbackTracker

tracker = FeedbackTracker(workspace_path=".orchestrator")
feedback = tracker.get_new_feedback()
# Returns: [Feedback(task_id="task-001", content="Use POST instead")]
```

### ChangelogManager

Manage semantic versioning and changelogs.

```python
from orchestrator.core.changelog import ChangelogManager

manager = ChangelogManager()
manager.add_entry(
    change_type="Added",
    description="JWT authentication support",
    version_bump="minor"
)
manager.save()
```

### Tester

Validate acceptance criteria.

```python
from orchestrator.core.tester import Tester

tester = Tester()
results = tester.test(task.test_cases)
# Returns: {test_name: passed_bool, ...}
```

---

## Integration Example

```python
from orchestrator.core.orchestrator import Orchestrator
from orchestrator.models import Goal, Task, TestCase
from pathlib import Path

# Initialize
workspace = Path(".orchestrator")
orch = Orchestrator(workspace_path=str(workspace))

# Define goals
goals = [
    Goal(
        title="Add authentication",
        description="Implement JWT-based auth",
        acceptance_criteria=["Tests pass", "API secured"]
    )
]

# Run orchestration
result = orch.run(max_iterations=100, goals=goals)

# Check results
print(f"Status: {result.status}")
print(f"Completed tasks: {result.completed_count}")
print(f"Total cost: ${result.cost_usd:.2f}")
```

---

## Error Handling

```python
from orchestrator.core.subagent import SubagentError
from orchestrator.models import TaskStatus

try:
    result = actor.execute(task)
    if result.status == TaskStatus.FAILED:
        print(f"Task failed: {result.error_message}")
except SubagentError as e:
    print(f"Subagent crashed: {e}")
```

---

## Configuration

Via environment variables or direct instantiation:

```python
import os

os.environ["ORCHESTRATOR_WORKSPACE"] = "/path/to/workspace"
os.environ["MAX_ITERATIONS"] = "150"
os.environ["DEBUG"] = "1"

orch = Orchestrator()  # Uses env vars
```

Or pass directly:

```python
orch = Orchestrator(
    workspace_path=".orchestrator",
    max_iterations=100,
    debug=True
)
```

---

## Extending Orchestrator

### Custom Validators

```python
from orchestrator.core.validators import BaseValidator

class CustomValidator(BaseValidator):
    def validate(self, test_case) -> bool:
        # Custom validation logic
        return True
```

### Custom Domain Context

```python
from orchestrator.core.domain_context import DomainContext

class DataScienceDomain(DomainContext):
    domain = "data_science"

    def get_guardrails(self) -> str:
        return "No default values, use hard failures..."
```

---

## Performance Considerations

- **Subagent spawning**: ~15-20 seconds per subagent startup
- **Event logging**: ~1ms per log entry
- **Large codebases**: Consider parallelizing independent analysis tasks
- **Caching**: Reuse analysis results across invocations via `.orchestrator/history/`

