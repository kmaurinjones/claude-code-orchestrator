"""Parallel task execution for orchestrator.

Enables concurrent execution of independent tasks up to max_parallel_tasks limit.
"""

import concurrent.futures
from typing import List, Dict, Any
from datetime import datetime

from rich.console import Console

from ..models import Task, TaskStatus

console = Console()


def _timestamp() -> str:
    """Return timestamp in YYYY-MM-DD--HH-MM-SS format."""
    return datetime.now().strftime("%Y-%m-%d--%H-%M-%S")


class ParallelExecutor:
    """Executes multiple tasks concurrently."""

    def __init__(self, max_parallel: int = 3):
        self.max_parallel = max_parallel

    def execute_tasks_parallel(
        self,
        tasks: List[Task],
        process_func: callable,
    ) -> Dict[str, Any]:
        """
        Execute multiple tasks in parallel.

        Args:
            tasks: List of tasks to execute
            process_func: Function that processes a single task (task) -> None

        Returns:
            Dict with execution summary
        """
        if not tasks:
            return {"completed": 0, "failed": 0, "tasks": []}

        # Limit to max_parallel
        tasks_to_run = tasks[:self.max_parallel]

        console.print(
            f"[cyan]{_timestamp()} [PARALLEL][/cyan] "
            f"Executing {len(tasks_to_run)} tasks concurrently"
        )

        completed = []
        failed = []

        # Use ThreadPoolExecutor for I/O-bound subagent calls
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_parallel) as executor:
            # Submit all tasks
            future_to_task = {
                executor.submit(process_func, task): task
                for task in tasks_to_run
            }

            # Wait for completion
            for future in concurrent.futures.as_completed(future_to_task):
                task = future_to_task[future]

                try:
                    future.result()  # Will raise if process_func raised

                    if task.status == TaskStatus.COMPLETE:
                        completed.append(task.id)
                        console.print(
                            f"[green]{_timestamp()} [PARALLEL][/green] "
                            f"✓ {task.id} completed"
                        )
                    else:
                        failed.append(task.id)
                        console.print(
                            f"[red]{_timestamp()} [PARALLEL][/red] "
                            f"✗ {task.id} failed"
                        )

                except Exception as e:
                    failed.append(task.id)
                    console.print(
                        f"[red]{_timestamp()} [PARALLEL][/red] "
                        f"✗ {task.id} raised exception: {str(e)[:100]}"
                    )

        return {
            "completed": len(completed),
            "failed": len(failed),
            "tasks": {"completed": completed, "failed": failed},
        }


def get_ready_tasks_batch(
    task_graph,
    max_count: int,
    exclude_ids: set = None,
) -> List[Task]:
    """
    Get batch of ready tasks for parallel execution.

    Args:
        task_graph: TaskGraph instance
        max_count: Maximum tasks to return
        exclude_ids: Task IDs to exclude (already running)

    Returns:
        List of ready tasks (dependencies met, not blocked)
    """
    exclude_ids = exclude_ids or set()
    ready = task_graph.get_ready_tasks()

    # Filter out excluded tasks
    ready = [t for t in ready if t.id not in exclude_ids]

    # Return up to max_count
    return ready[:max_count]
