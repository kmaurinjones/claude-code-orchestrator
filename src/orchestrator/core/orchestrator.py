"""Main orchestrator logic."""

from pathlib import Path
from typing import List
from uuid import uuid4
from datetime import datetime
from rich.console import Console

from .. import __version__
from ..models import EventType, TaskStatus, Task
from ..planning.goals import GoalsManager
from ..planning.tasks import TaskGraph
from .logger import EventLogger
from .subagent import Subagent
from .verification import Verifier

console = Console()


def _timestamp() -> str:
    """Return timestamp in YYYY-MM-DD--HH-MM-SS format."""
    return datetime.now().strftime("%Y-%m-%d--%H-%M-%S")


class Orchestrator:
    def __init__(
        self,
        workspace: Path = Path(".agentic"),
        min_steps: int = 50,
        max_steps: int = 100,
        max_parallel_tasks: int = 3  # Reduced for MVP-first incremental development
    ):
        # Resolve workspace to absolute path immediately
        self.workspace = workspace.resolve()
        self.project_root = self.workspace.parent  # Actual project directory (already absolute)
        self.min_steps = min_steps
        self.max_steps = max_steps
        self.max_parallel_tasks = max_parallel_tasks

        # Initialize components (use self.workspace which is now absolute)
        self.logger = EventLogger(self.workspace / "full_history.jsonl")
        self.goals = GoalsManager(self.workspace / "current" / "GOALS.md")
        self.tasks = TaskGraph(self.workspace / "current" / "TASKS.md")
        self.verifier = Verifier(self.project_root)  # Verify in project root

        # State - step counts EVERY Claude Code call (orchestrator or subagent)
        self.current_step = 0
        self.trace_id = f"orch-{uuid4().hex[:8]}"

    def run(self) -> str:
        """Main orchestration loop."""
        console.print(f"[cyan]{_timestamp()} [ORCHESTRATOR][/cyan] Starting autonomous execution")
        console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Min steps: {self.min_steps}")
        console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Max steps: {self.max_steps}")
        console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Max parallel tasks: {self.max_parallel_tasks}")
        console.print()

        self.current_step += 1  # Orchestrator start counts as step 1
        self.logger.log(
            event_type=EventType.CHECKPOINT,
            actor="orchestrator",
            payload={"action": "start", "max_steps": self.max_steps},
            trace_id=self.trace_id,
            step=self.current_step,
            version=__version__
        )

        while self.current_step < self.max_steps:
            console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Step {self.current_step}/{self.max_steps}")

            # Only check completion after min_steps
            if self.current_step >= self.min_steps:
                if self._check_completion():
                    console.print(f"[green]{_timestamp()} [ORCHESTRATOR][/green] All core goals achieved!")
                    return "SUCCESS"

            next_tasks = self._select_next_tasks()
            if not next_tasks:
                # Check if we should generate more tasks
                if self.current_step < self.min_steps and self._all_tasks_complete():
                    console.print(f"[cyan]{_timestamp()} [ORCHESTRATOR][/cyan] All tasks complete but min_steps not reached")
                    console.print(f"[cyan]{_timestamp()} [ORCHESTRATOR][/cyan] Generating additional tasks...")

                    if self._generate_additional_tasks():
                        continue  # Go to next iteration with new tasks
                    else:
                        console.print(f"[yellow]{_timestamp()} [ORCHESTRATOR][/yellow] Could not generate additional tasks")
                        return "NO_TASKS_AVAILABLE"
                else:
                    console.print(f"[yellow]{_timestamp()} [ORCHESTRATOR][/yellow] No tasks available to execute")
                    return "NO_TASKS_AVAILABLE"

            self._execute_tasks(next_tasks)

            # Analyze failures and create fix tasks after each batch
            self._analyze_failures_and_create_fixes()

            if self.current_step % 5 == 0:
                self._reflect()

        console.print(f"[yellow]{_timestamp()} [ORCHESTRATOR][/yellow] Reached max iterations ({self.max_steps})")
        return "MAX_ITERATIONS_REACHED"

    def _check_completion(self) -> bool:
        """Check if all core goals achieved."""
        core_goals = self.goals.core_goals
        return all(goal.achieved for goal in core_goals)

    def _all_tasks_complete(self) -> bool:
        """Check if all non-failed tasks are complete."""
        from ..models import TaskStatus
        for task in self.tasks._tasks.values():
            if task.status in [TaskStatus.BACKLOG, TaskStatus.IN_PROGRESS]:
                return False
        return True

    def _generate_additional_tasks(self) -> bool:
        """Generate additional tasks to reach min_steps without jeopardizing goals."""
        console.print(f"[magenta]{_timestamp()} [PLANNER][/magenta] Analyzing project for additional work...")

        # Build context for task generation
        context = self._build_task_generation_context()

        # Task description for the planner subagent
        task_description = f"""Analyze the current project state and generate 3-5 additional MVP-focused tasks that build on verified working code.

**MVP-FIRST PHILOSOPHY**:
- Build smallest working piece → Test it → Fix if broken → Only then add more
- Each task should result in working, testable code
- Prefer small incremental tasks over large complex ones
- Tasks should have clear, immediately verifiable success criteria

Focus on:
- **MVP features** that extend what's already working
- **Incremental improvements** to verified code
- **Testing and validation** of existing features
- **Bug fixes** for any broken functionality (HIGHEST PRIORITY)
- **Small refactorings** that maintain working state
- Documentation for what's already built

DO NOT suggest:
- Large features before basics work
- Multiple complex changes in one task
- Tasks without clear verification criteria

Append new tasks to the existing TASKS.md file at {self.workspace / "current" / "TASKS.md"}.

Use this format for each new task:
- [📋] task-XXX: Description (priority: N)
  - Goals: goal-id (if applicable)
  - Verify: file_exists:path/to/file "File description"

Mark foundational/MVP tasks with "mvp" or "foundation" in the description.

Respond with JSON status block when complete:
{{
  "status": "SUCCESS",
  "summary": "Generated N new tasks",
  "tasks_generated": ["task-id1", "task-id2"]
}}
"""

        try:
            # Increment step for this Claude call
            self.current_step += 1

            subagent = Subagent(
                task_id="task-generation",
                task_description=task_description,
                context=context,
                parent_trace_id=self.trace_id,
                logger=self.logger,
                step=self.current_step,
                workspace=self.project_root
            )

            result = subagent.execute()

            if result.get("status") in ["success", "SUCCESS"]:
                # Reload task graph to pick up new tasks
                self.tasks._load()
                console.print(f"[green]{_timestamp()} [PLANNER][/green] Successfully generated additional tasks")
                return True
            else:
                console.print(f"[red]{_timestamp()} [PLANNER][/red] Failed to generate tasks: {result.get('error', 'Unknown')}")
                return False

        except Exception as e:
            console.print(f"[red]{_timestamp()} [PLANNER][/red] Error during task generation: {str(e)}")
            return False

    def _build_task_generation_context(self) -> str:
        """Build context for task generation."""
        lines = []

        # Goals status
        lines.append("## Goals Status")
        for goal in self.goals.core_goals:
            status = "✓" if goal.achieved else "○"
            lines.append(f"{status} {goal.description} (confidence: {goal.confidence:.2f})")
        lines.append("")

        # Completed tasks summary
        completed_tasks = [t for t in self.tasks._tasks.values() if t.status == TaskStatus.COMPLETE]
        lines.append(f"## Completed Tasks ({len(completed_tasks)})")
        for task in completed_tasks[:10]:  # Show up to 10
            lines.append(f"- {task.id}: {task.title}")
        if len(completed_tasks) > 10:
            lines.append(f"... and {len(completed_tasks) - 10} more")
        lines.append("")

        # Current iteration
        lines.append("## Progress")
        lines.append(f"- Current iteration: {self.current_step}/{self.min_steps} (min)")
        lines.append(f"- Need to sustain work until iteration {self.min_steps}")

        return "\n".join(lines)

    def _select_next_tasks(self) -> List[Task]:
        """Select tasks with MVP-first incremental approach - prefer sequential validation."""
        ready_tasks = self.tasks.get_ready_tasks()

        if not ready_tasks:
            return []

        # Prioritize: fix tasks > failed tasks > foundational > at-risk > new tasks
        def get_task_priority_score(task: Task) -> tuple:
            """Return sort key prioritizing fixes and failures."""
            # Fix tasks have HIGHEST priority (generated by failure analysis)
            is_fix_task = task.id.startswith('fix-')

            # Failed/retried tasks have second highest priority
            has_failed_attempts = task.attempt_count > 0

            # Tasks related to at-risk goals get boosted
            at_risk_goals = [
                g for g in self.goals.core_goals
                if not g.achieved and g.confidence < 0.5
            ]
            is_at_risk = any(g.id in task.related_goals for g in at_risk_goals)

            # Check if task looks foundational (MVP, setup, init, config, base)
            is_foundational = any(keyword in task.title.lower() for keyword in [
                'mvp', 'initialize', 'setup', 'init', 'config', 'base', 'foundation',
                'core', 'essential', 'basic', 'directory structure', 'project structure'
            ])

            return (
                not is_fix_task,         # Fix tasks FIRST (False < True)
                not has_failed_attempts,  # Failed tasks second
                not is_foundational,      # Foundational tasks third
                not is_at_risk,          # At-risk goal tasks fourth
                -task.priority           # Then by priority (descending)
            )

        ready_tasks.sort(key=get_task_priority_score)

        # MVP-FIRST STRATEGY: Default to sequential execution (single task)
        # Only parallelize if tasks are EXPLICITLY independent AND low-risk

        # Always start with highest priority task
        selected = [ready_tasks[0]]

        # Only consider parallelization if:
        # 1. We have more than one ready task
        # 2. The first task is NOT foundational or failed
        # 3. Tasks are truly independent
        if len(ready_tasks) > 1 and selected[0].attempt_count == 0:
            highest_priority = selected[0].priority

            # Check if first task is foundational - if so, NEVER parallelize
            is_first_foundational = any(keyword in selected[0].title.lower() for keyword in [
                'mvp', 'initialize', 'setup', 'init', 'config', 'base', 'foundation',
                'core', 'essential', 'basic', 'directory structure', 'project structure'
            ])

            if not is_first_foundational:
                # Only add tasks with same/similar priority that are independent
                for task in ready_tasks[1:]:
                    if len(selected) >= self.max_parallel_tasks:
                        break

                    # Must be within 1 priority level (stricter than before)
                    if abs(task.priority - highest_priority) > 1:
                        continue

                    # Check dependencies
                    has_conflict = False
                    for selected_task in selected:
                        if (task.id in selected_task.depends_on or
                            selected_task.id in task.depends_on):
                            has_conflict = True
                            break

                    if not has_conflict:
                        selected.append(task)

        return selected

    def _execute_tasks(self, tasks: List[Task]) -> None:
        """Execute tasks with build-test-fix loop: build → test → fix → repeat until working."""
        if len(tasks) == 1:
            console.print(f"[cyan]{_timestamp()} [ORCHESTRATOR][/cyan] Selected 1 task: {tasks[0].id}")
        else:
            task_ids = ", ".join(t.id for t in tasks)
            console.print(f"[cyan]{_timestamp()} [ORCHESTRATOR][/cyan] Selected {len(tasks)} tasks: {task_ids}")

        for task in tasks:
            console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] - {task.id}: {task.title[:60]}")

        console.print()

        # MVP APPROACH: Execute tasks with tight build-test-fix loop
        # Build something → Test immediately → If fails, fix immediately → Repeat until working
        for task in tasks:
            self.logger.log(
                event_type=EventType.DECISION,
                actor="orchestrator",
                payload={
                    "action": "execute_task",
                    "task_id": task.id,
                    "task_title": task.title,
                    "batch_size": len(tasks)
                },
                trace_id=self.trace_id,
                step=self.current_step,
                version=__version__
            )

            # Build-Test-Fix Loop: Keep trying until task works or max attempts reached
            while task.attempt_count < task.max_attempts and task.status != TaskStatus.COMPLETE:
                # Increment step for this Claude call
                self.current_step += 1
                current_step = self.current_step
                task.attempt_count += 1

                attempt_msg = f"(attempt {task.attempt_count}/{task.max_attempts})" if task.attempt_count > 1 else ""
                console.print(f"[blue]{_timestamp()} [BUILD][/blue] Starting {task.id} {attempt_msg} (step {current_step})")

                context = self._build_context_for_task(task)

                subagent = Subagent(
                    task_id=task.id,
                    task_description=task.description,
                    context=context,
                    parent_trace_id=self.trace_id,
                    logger=self.logger,
                    step=current_step,
                    workspace=self.project_root,
                    next_action=task.next_action  # Pass feedback from previous attempt
                )

                result = subagent.execute()

                # IMMEDIATE TESTING: Verify right after building
                if result["status"] in ["success", "SUCCESS"]:
                    if task.acceptance_criteria:
                        console.print(f"[cyan]{_timestamp()} [TEST][/cyan] Verifying {task.id} immediately...")
                        verified, failures = self.verifier.verify_task(task)

                        if verified:
                            # SUCCESS: Task works, move to next
                            task.status = TaskStatus.COMPLETE
                            task.summary.append(result.get("summary", "Completed")[:200])
                            console.print(f"[green]{_timestamp()} [SUCCESS][/green] ✓ {task.id} verified working")
                            summary = result.get("summary", "")[:60]
                            if summary:
                                console.print(f"[dim]{_timestamp()} [SUCCESS][/dim] {summary}")
                            break  # Exit loop, task is done
                        else:
                            # FIX: Verification failed, loop back to build with feedback
                            task.next_action = f"Previous attempt failed verification. Errors: {'; '.join(failures[:3])}. Fix these issues and try again."
                            console.print(f"[yellow]{_timestamp()} [FIX NEEDED][/yellow] ⚠ {task.id} verification failed - retrying with feedback")
                            for failure in failures[:3]:
                                console.print(f"[dim]{_timestamp()} [FIX NEEDED][/dim]   - {failure}")
                            task.summary.append(f"Attempt {task.attempt_count}: Verification failed - {failures[0] if failures else 'Unknown'}")
                            # Loop continues to retry
                    else:
                        # No verification needed
                        task.status = TaskStatus.COMPLETE
                        task.summary.append(result.get("summary", "Completed")[:200])
                        console.print(f"[green]{_timestamp()} [SUCCESS][/green] ✓ {task.id} completed")
                        break  # Exit loop
                elif result["status"] in ["BLOCKED", "blocked"]:
                    # Blocked: Provide feedback and retry
                    blockers = result.get("blockers", "Unknown blocker")
                    task.next_action = f"Previous attempt blocked. Blocker: {blockers}. Find a workaround or resolve the blocker."
                    console.print(f"[yellow]{_timestamp()} [FIX NEEDED][/yellow] ⚠ {task.id} blocked - retrying")
                    task.summary.append(f"Attempt {task.attempt_count}: Blocked - {blockers}")
                    # Loop continues to retry
                else:
                    # Failed: Provide feedback and retry
                    error = result.get("error", "Unknown error")
                    task.next_action = f"Previous attempt failed. Error: {error}. Fix the issue and try again."
                    console.print(f"[yellow]{_timestamp()} [FIX NEEDED][/yellow] ⚠ {task.id} failed - retrying")
                    task.summary.append(f"Attempt {task.attempt_count}: {error}")
                    # Loop continues to retry

            # After loop: Check if task failed due to max attempts
            if task.status != TaskStatus.COMPLETE:
                task.status = TaskStatus.FAILED
                console.print(f"[red]{_timestamp()} [FAILED][/red] ✗ {task.id} failed after {task.max_attempts} attempts")
                console.print(f"[red]{_timestamp()} [FAILED][/red] Cannot proceed with MVP - foundational task failed")

            console.print()

        self.tasks.save()

    def _build_context_for_task(self, task: Task) -> str:
        """Build relevant context for a task."""
        context_parts = []

        for goal_id in task.related_goals:
            goal = self.goals.get_goal(goal_id)
            if goal:
                context_parts.append(f"GOAL: {goal.description}")
                context_parts.append(f"Success criteria: {goal.measurable_criteria}\n")

        for dep_id in task.depends_on:
            dep_task = self.tasks._tasks.get(dep_id)
            if dep_task and dep_task.status == TaskStatus.COMPLETE:
                context_parts.append(f"Previous task ({dep_id}): {dep_task.title}")
                if dep_task.summary:
                    context_parts.append(f"Result: {dep_task.summary[-1]}\n")

        return "\n".join(context_parts)

    def _reflect(self) -> None:
        """Periodic reflection on progress."""
        console.print(f"[magenta]{_timestamp()} [ORCHESTRATOR][/magenta] Reflecting on progress...")

        status_counts = {}
        for task in self.tasks._tasks.values():
            status_counts[task.status] = status_counts.get(task.status, 0) + 1

        goal_status = []
        for goal in self.goals.core_goals:
            goal_status.append({
                "id": goal.id,
                "achieved": goal.achieved,
                "confidence": goal.confidence
            })

        # Print summary
        completed = status_counts.get(TaskStatus.COMPLETE, 0)
        total = len(self.tasks._tasks)
        console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Tasks: {completed}/{total} completed")

        goals_done = sum(1 for g in self.goals.core_goals if g.achieved)
        goals_total = len(self.goals.core_goals)
        console.print(f"[dim]{_timestamp()} [ORCHESTRATOR][/dim] Goals: {goals_done}/{goals_total} achieved")
        console.print()

        self.logger.log(
            event_type=EventType.REFLECTION,
            actor="orchestrator",
            payload={
                "step": self.current_step,
                "task_counts": status_counts,
                "goal_status": goal_status
            },
            trace_id=self.trace_id,
            step=self.current_step,
            version=__version__
        )

    def _analyze_failures_and_create_fixes(self) -> None:
        """Analyze task failures and generate fix tasks for systemic issues."""
        # Get all tasks that are failing or have failed attempts
        failing_tasks = [
            t for t in self.tasks._tasks.values()
            if t.attempt_count > 0 and t.status != TaskStatus.COMPLETE
        ]

        if not failing_tasks:
            return

        console.print(f"[magenta]{_timestamp()} [ORCHESTRATOR][/magenta] Analyzing {len(failing_tasks)} failing task(s)...")

        # Analyze patterns in failures
        patterns = {
            "file_not_found": [],
            "verification_failed": [],
            "path_issues": [],
            "missing_dependencies": [],
            "import_errors": [],
            "other": []
        }

        for task in failing_tasks:
            feedback = task.next_action or ""
            summary_text = " ".join(task.summary)

            combined_text = f"{feedback} {summary_text}".lower()

            # Categorize failures
            if "file not found" in combined_text or "no such file" in combined_text:
                patterns["file_not_found"].append(task)
            elif "verification failed" in combined_text:
                patterns["verification_failed"].append(task)
            elif ".agentic" in combined_text or "path" in combined_text:
                patterns["path_issues"].append(task)
            elif "dependency" in combined_text or "missing" in combined_text:
                patterns["missing_dependencies"].append(task)
            elif "import" in combined_text or "module" in combined_text:
                patterns["import_errors"].append(task)
            else:
                patterns["other"].append(task)

        # Create fix tasks for patterns with multiple occurrences
        fixes_created = 0
        tasks_to_add = []

        # Path issues fix
        if len(patterns["path_issues"]) >= 2:
            fix_task_id = f"fix-path-{uuid4().hex[:4]}"
            fix_description = f"""Fix workspace path issues affecting {len(patterns["path_issues"])} tasks.

Common issue: Files being created in wrong directory (likely .agentic/ instead of project root).

Affected tasks: {', '.join(t.id for t in patterns["path_issues"][:3])}

Fix approach:
1. Verify current working directory
2. Check if files exist in .agentic/ subdirectory
3. Move files to correct location if needed
4. Update any path references
"""
            tasks_to_add.append({
                "id": fix_task_id,
                "title": f"Fix path issues affecting {len(patterns['path_issues'])} tasks",
                "description": fix_description,
                "priority": 9
            })
            fixes_created += 1

        # Verification failures fix
        if len(patterns["verification_failed"]) >= 2:
            fix_task_id = f"fix-verify-{uuid4().hex[:4]}"
            fix_description = f"""Fix verification failures affecting {len(patterns["verification_failed"])} tasks.

Affected tasks: {', '.join(t.id for t in patterns["verification_failed"][:3])}

Analysis needed:
1. Review verification criteria for failed tasks
2. Check if files/conditions exist but verification logic is wrong
3. Determine if this is a path issue or actual missing implementation
4. Fix the root cause

Failed tasks details:
{chr(10).join(f"- {t.id}: {t.next_action[:100]}" for t in patterns["verification_failed"][:3])}
"""
            tasks_to_add.append({
                "id": fix_task_id,
                "title": "Debug and fix verification failures",
                "description": fix_description,
                "priority": 8
            })
            fixes_created += 1

        # Import/dependency errors fix
        if len(patterns["import_errors"]) >= 2 or len(patterns["missing_dependencies"]) >= 2:
            affected = patterns["import_errors"] + patterns["missing_dependencies"]
            fix_task_id = f"fix-deps-{uuid4().hex[:4]}"
            fix_description = f"""Fix dependency/import issues affecting {len(affected)} tasks.

Affected tasks: {', '.join(t.id for t in affected[:3])}

Fix approach:
1. Review all import errors
2. Check if modules exist but paths are wrong
3. Install missing dependencies if needed
4. Update import statements to use correct paths
"""
            tasks_to_add.append({
                "id": fix_task_id,
                "title": "Fix dependency and import errors",
                "description": fix_description,
                "priority": 8
            })
            fixes_created += 1

        # Add fix tasks to TASKS.md
        if tasks_to_add:
            tasks_file = self.workspace / "current" / "TASKS.md"

            # Read current content
            with open(tasks_file, 'r') as f:
                content = f.read()

            # Append new fix tasks
            new_tasks_section = "\n\n# Auto-Generated Fix Tasks\n"
            for task_data in tasks_to_add:
                new_tasks_section += f"- [📋] {task_data['id']}: {task_data['title']} (priority: {task_data['priority']})\n"

            # Write back
            with open(tasks_file, 'a') as f:
                f.write(new_tasks_section)

            # Reload task graph
            self.tasks._load()

            console.print(f"[green]{_timestamp()} [ORCHESTRATOR][/green] Created {fixes_created} fix task(s) for systemic issues")

            # Log the analysis
            self.logger.log(
                event_type=EventType.CHECKPOINT,
                actor="orchestrator",
                payload={
                    "action": "failure_analysis",
                    "failing_tasks": len(failing_tasks),
                    "patterns": {k: len(v) for k, v in patterns.items()},
                    "fixes_created": fixes_created,
                    "fix_task_ids": [t["id"] for t in tasks_to_add]
                },
                trace_id=self.trace_id,
                step=self.current_step,
                version=__version__
            )
