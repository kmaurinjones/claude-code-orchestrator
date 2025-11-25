"""TASKS.md graph manager with dependency tracking."""

import ast
import re
import networkx as nx
from pathlib import Path
from typing import Iterable, List, Dict
from ..models import Task, TaskStatus, VerificationCheck


class TaskGraph:
    def __init__(self, tasks_path: Path = Path(".orchestrator/current/TASKS.md")):
        self.tasks_path = tasks_path
        self.graph = nx.DiGraph()
        self._tasks: Dict[str, Task] = {}

        # Load existing tasks if file exists
        if self.tasks_path.exists():
            self._load()

    def _load(self) -> None:
        """Load tasks from existing TASKS.md file."""
        content = self.tasks_path.read_text()

        # Parse format: - [📋] task-001: Description (priority: 10) or - [📋] task-001: Description
        # Make priority optional
        task_pattern = r'-\s*\[(.+?)\]\s*(task-\S+):\s*(.+?)(?:\s*\(priority:\s*(\d+)\))?$'

        # Verification check pattern: - Verify: type:target "description or pattern"
        # For pattern_in_file, the quoted part is the pattern, not just description
        verify_pattern = r'-\s*Verify:\s*(\w+):(.+?)\s+"(.+?)"'
        depends_pattern = r'-\s*Depends on:\s*(.+)'

        current_task = None

        for line in content.split('\n'):
            # Check for task line
            match = re.search(task_pattern, line)
            if match:
                emoji, task_id, description, priority = match.groups()

                # Map emoji to status
                status = TaskStatus.BACKLOG
                for ts in TaskStatus:
                    if ts.value == emoji:
                        status = ts
                        break

                task = Task(
                    id=task_id,
                    title=description.strip(),
                    description=description.strip(),
                    status=status,
                    priority=int(priority) if priority else 5  # Default priority 5
                )

                self.add_task(task)
                current_task = task
                continue

            # Check for depends on line
            depends_match = re.search(depends_pattern, line)
            if depends_match and current_task:
                deps_raw = depends_match.group(1).strip()
                dependencies: List[str] = []

                if deps_raw.startswith('[') and deps_raw.endswith(']'):
                    try:
                        parsed = ast.literal_eval(deps_raw)
                        if isinstance(parsed, (list, tuple)):
                            dependencies = [str(item).strip() for item in parsed if str(item).strip()]
                    except (SyntaxError, ValueError):
                        # Fallback to comma split below
                        pass

                if not dependencies:
                    dependencies = [dep.strip().strip('"').strip("'") for dep in deps_raw.split(",") if dep.strip()]

                current_task.depends_on = dependencies

                for dep_id in dependencies:
                    if dep_id:
                        self.graph.add_edge(dep_id, current_task.id)

                continue

            # Check for verification line
            verify_match = re.search(verify_pattern, line)
            if verify_match and current_task:
                verify_type, target, desc = verify_match.groups()

                # For pattern_in_file, the description is also the pattern to search for
                expected_val = desc.strip() if verify_type.strip() == "pattern_in_file" else None

                check = VerificationCheck(
                    type=verify_type.strip(),
                    target=target.strip(),
                    expected=expected_val,
                    description=desc.strip()
                )

                current_task.acceptance_criteria.append(check)

    def add_task(self, task: Task) -> Task:
        """Add task to graph."""
        self._tasks[task.id] = task
        self.graph.add_node(task.id)

        for dep_id in task.depends_on:
            self.graph.add_edge(dep_id, task.id)

        return task

    def create_task(
        self,
        *,
        title: str,
        description: str,
        priority: int = 5,
        depends_on: Iterable[str] | None = None,
        acceptance_criteria: Iterable[VerificationCheck] | None = None,
        prefix: str = "task",
    ) -> Task:
        """Create a new backlog task with a unique identifier."""
        task_id = self.generate_task_id(prefix=prefix)
        task = Task(
            id=task_id,
            title=title,
            description=description,
            status=TaskStatus.BACKLOG,
            priority=priority,
            depends_on=list(depends_on or []),
            acceptance_criteria=list(acceptance_criteria or []),
        )
        self.add_task(task)
        return task

    def update_task_dependencies(self, task_id: str, dependencies: Iterable[str]) -> None:
        """Replace dependencies for a task and update the graph edges."""
        task = self._tasks.get(task_id)
        if not task:
            return

        cleaned = [dep for dep in dependencies if dep and dep != task_id]
        task.depends_on = cleaned

        if self.graph.has_node(task_id):
            incoming = list(self.graph.predecessors(task_id))
            for node in incoming:
                self.graph.remove_edge(node, task_id)

        for dep in cleaned:
            self.graph.add_edge(dep, task_id)

    def generate_task_id(self, prefix: str = "task") -> str:
        """Generate a new task identifier with incremental numbering."""
        prefix_with_dash = f"{prefix}-"
        numbers = [
            int(task_id[len(prefix_with_dash):])
            for task_id in self._tasks.keys()
            if task_id.startswith(prefix_with_dash) and task_id[len(prefix_with_dash):].isdigit()
        ]
        next_number = (max(numbers) if numbers else 0) + 1
        return f"{prefix}-{next_number:03d}"

    def get_ready_tasks(self) -> List[Task]:
        """Get tasks whose dependencies are all complete."""
        ready = []

        for task_id, task in self._tasks.items():
            if task.status != TaskStatus.BACKLOG:
                continue

            deps_complete = all(
                self._tasks[dep_id].status == TaskStatus.COMPLETE
                for dep_id in task.depends_on
                if dep_id in self._tasks
            )

            if deps_complete:
                ready.append(task)

        return sorted(ready, key=lambda t: t.priority, reverse=True)

    def get_dependency_chain(self, task_id: str) -> List[str]:
        """Return the dependency chain for a task (dependencies first, task last)."""
        visited = set()
        chain: List[str] = []

        def visit(current: str) -> None:
            if current in visited or current not in self._tasks:
                return
            visited.add(current)
            for dep in self._tasks[current].depends_on:
                visit(dep)
            chain.append(current)

        visit(task_id)
        return chain

    @property
    def tasks(self) -> Dict[str, Task]:
        """Expose tasks dictionary for read-only consumers."""
        return self._tasks

    def get_dependents(self, task_id: str) -> List[str]:
        """Return tasks that depend on the given task."""
        if not self.graph.has_node(task_id):
            return []
        return sorted(self.graph.successors(task_id))

    def reload(self) -> None:
        """Reload tasks from disk preserving current path."""
        self.graph.clear()
        self._tasks.clear()
        if self.tasks_path.exists():
            self._load()

    def has_cycles(self) -> bool:
        """Check for circular dependencies."""
        try:
            nx.find_cycle(self.graph)
            return True
        except nx.NetworkXNoCycle:
            return False

    def save(self) -> None:
        """Write current task state to TASKS.md."""
        lines = ["# TASKS.md\n\n"]

        for status in TaskStatus:
            tasks_in_status = [t for t in self._tasks.values() if t.status == status]
            if not tasks_in_status:
                continue

            lines.append(f"## {status.name.title()}\n")
            for task in tasks_in_status:
                lines.append(f"- [{status.value}] {task.id}: {task.title} (priority: {task.priority})")
                if task.depends_on:
                    lines.append(f"  - Depends on: {', '.join(task.depends_on)}")
                if task.related_goals:
                    lines.append(f"  - Goals: {', '.join(task.related_goals)}")
                if task.acceptance_criteria:
                    for check in task.acceptance_criteria:
                        lines.append(f'  - Verify: {check.type}:{check.target} "{check.description}"')
                if task.summary:
                    lines.append(f"  - Summary: {task.summary[-1]}")
                lines.append("\n")

        self.tasks_path.parent.mkdir(parents=True, exist_ok=True)
        self.tasks_path.write_text("\n".join(lines))
