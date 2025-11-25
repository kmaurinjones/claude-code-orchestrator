"""Goal-task alignment tracking for progress visibility and orphan detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from rich.console import Console
from rich.table import Table

from ..models import Goal, Task, TaskStatus
from ..planning.goals import GoalsManager
from ..planning.tasks import TaskGraph

console = Console()


@dataclass
class GoalProgress:
    """Progress tracking for a single goal."""

    goal: Goal
    total_tasks: int = 0
    completed_tasks: int = 0
    in_progress_tasks: int = 0
    failed_tasks: int = 0
    task_ids: List[str] = field(default_factory=list)

    @property
    def progress_percent(self) -> float:
        """Calculate completion percentage."""
        if self.total_tasks == 0:
            return 0.0
        return (self.completed_tasks / self.total_tasks) * 100

    @property
    def is_achieved(self) -> bool:
        """Goal is achieved when all linked tasks complete."""
        return self.total_tasks > 0 and self.completed_tasks == self.total_tasks


@dataclass
class AlignmentReport:
    """Full alignment analysis report."""

    goal_progress: Dict[str, GoalProgress]  # goal_id -> progress
    orphan_tasks: List[Task]  # Tasks not linked to any goal
    multi_goal_tasks: List[Task]  # Tasks linked to multiple goals (high value)
    blocking_tasks: List[Task]  # Tasks blocking multiple goals

    @property
    def orphan_count(self) -> int:
        return len(self.orphan_tasks)

    @property
    def total_goals(self) -> int:
        return len(self.goal_progress)

    @property
    def achieved_goals(self) -> int:
        return sum(1 for p in self.goal_progress.values() if p.is_achieved)


class GoalAlignmentTracker:
    """Tracks alignment between tasks and goals for progress visibility."""

    def __init__(self, goals: GoalsManager, tasks: TaskGraph):
        self.goals = goals
        self.tasks = tasks
        self._goal_lookup: Dict[str, Goal] = {}
        self._build_goal_lookup()

    def _build_goal_lookup(self) -> None:
        """Build lookup table for goals by ID."""
        for goal in self.goals.all_goals:
            self._goal_lookup[goal.id] = goal

    def analyze(self) -> AlignmentReport:
        """Perform full alignment analysis."""
        goal_progress: Dict[str, GoalProgress] = {}
        orphan_tasks: List[Task] = []
        multi_goal_tasks: List[Task] = []
        task_goal_counts: Dict[str, int] = {}  # task_id -> goal count

        # Initialize progress for all goals
        for goal in self.goals.all_goals:
            goal_progress[goal.id] = GoalProgress(goal=goal)

        # Analyze each task
        for task_id, task in self.tasks._tasks.items():
            linked_goals = task.related_goals

            if not linked_goals:
                orphan_tasks.append(task)
                continue

            # Track multi-goal tasks
            if len(linked_goals) > 1:
                multi_goal_tasks.append(task)

            task_goal_counts[task_id] = len(linked_goals)

            # Update progress for each linked goal
            for goal_id in linked_goals:
                if goal_id not in goal_progress:
                    # Create placeholder for unknown goal references
                    placeholder_goal = Goal(
                        id=goal_id,
                        description=f"Unknown goal: {goal_id}",
                        measurable_criteria="",
                        tier="core",
                    )
                    goal_progress[goal_id] = GoalProgress(goal=placeholder_goal)

                progress = goal_progress[goal_id]
                progress.total_tasks += 1
                progress.task_ids.append(task_id)

                if task.status == TaskStatus.COMPLETE:
                    progress.completed_tasks += 1
                elif task.status == TaskStatus.IN_PROGRESS:
                    progress.in_progress_tasks += 1
                elif task.status == TaskStatus.FAILED:
                    progress.failed_tasks += 1

        # Identify blocking tasks (tasks that appear in multiple goal paths)
        blocking_tasks = [t for t in multi_goal_tasks if t.status != TaskStatus.COMPLETE]

        return AlignmentReport(
            goal_progress=goal_progress,
            orphan_tasks=orphan_tasks,
            multi_goal_tasks=multi_goal_tasks,
            blocking_tasks=blocking_tasks,
        )

    def get_goal_tasks(self, goal_id: str) -> List[Task]:
        """Get all tasks linked to a specific goal."""
        return [
            task
            for task in self.tasks._tasks.values()
            if goal_id in task.related_goals
        ]

    def get_unblocking_tasks(self) -> List[Task]:
        """Get tasks that would unblock the most goals when completed."""
        task_scores: Dict[str, int] = {}

        for task_id, task in self.tasks._tasks.items():
            if task.status == TaskStatus.COMPLETE:
                continue

            # Score based on number of goals this task contributes to
            score = len(task.related_goals)

            # Bonus for tasks that are blocking other tasks
            dependents = self.tasks.get_dependents(task_id)
            for dep_id in dependents:
                dep_task = self.tasks._tasks.get(dep_id)
                if dep_task:
                    score += len(dep_task.related_goals) * 0.5

            task_scores[task_id] = score

        # Sort by score descending
        sorted_tasks = sorted(
            task_scores.items(), key=lambda x: x[1], reverse=True
        )

        return [
            self.tasks._tasks[task_id]
            for task_id, _ in sorted_tasks[:10]
            if task_id in self.tasks._tasks
        ]

    def display_progress(self) -> None:
        """Display goal progress to console."""
        report = self.analyze()

        table = Table(title="Goal Progress")
        table.add_column("Goal", style="cyan", no_wrap=False, width=50)
        table.add_column("Progress", justify="right")
        table.add_column("Tasks", justify="right")
        table.add_column("Status", justify="center")

        for goal_id, progress in report.goal_progress.items():
            desc = progress.goal.description
            pct = f"{progress.progress_percent:.0f}%"
            tasks_str = f"{progress.completed_tasks}/{progress.total_tasks}"

            if progress.is_achieved:
                status = "[green]✓ Achieved[/green]"
            elif progress.failed_tasks > 0:
                status = f"[yellow]⚠ {progress.failed_tasks} failed[/yellow]"
            elif progress.in_progress_tasks > 0:
                status = "[blue]→ In progress[/blue]"
            else:
                status = "[dim]Pending[/dim]"

            table.add_row(desc, pct, tasks_str, status)

        console.print(table)

        if report.orphan_tasks:
            console.print(f"\n[yellow]⚠ {len(report.orphan_tasks)} orphan task(s) not linked to any goal[/yellow]")
            for task in report.orphan_tasks[:5]:
                console.print(f"  - {task.id}: {task.title[:60]}")

        if report.blocking_tasks:
            console.print(f"\n[cyan]ℹ {len(report.blocking_tasks)} task(s) blocking multiple goals[/cyan]")
            for task in report.blocking_tasks[:3]:
                goals_str = ", ".join(task.related_goals[:3])
                console.print(f"  - {task.id}: {task.title[:40]} (goals: {goals_str})")

    def suggest_goal_links(self, task: Task, goals: List[Goal]) -> List[str]:
        """Suggest goal IDs that a task might relate to based on text matching."""
        suggestions: List[str] = []
        task_text = f"{task.title} {task.description}".lower()

        for goal in goals:
            goal_text = f"{goal.description} {goal.measurable_criteria}".lower()

            # Simple keyword matching
            goal_words = set(goal_text.split())
            task_words = set(task_text.split())

            common = goal_words & task_words
            # Exclude common words
            common -= {"the", "a", "an", "is", "are", "and", "or", "to", "for", "in", "of", "with"}

            if len(common) >= 2:
                suggestions.append(goal.id)

        return suggestions[:3]
