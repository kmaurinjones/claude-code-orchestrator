# Orchestrator Enhancement Plan (Updated 2025-11-13)

## Status Overview
- **Phase 1 – Goal Evaluator & Validators:** ✅
- **Phase 2 – Parallel Task Execution:** ✅
- **Phase 3 – Replan / Adaptive Tasks:** ✅
- **Phase 4 – Experiment Logger Integration & Job Queue:** ✅
- **Phase 5 – Domain Context & Safety Prompts:** ✅
- **Phase 6 – Goal Evaluator Persistence:** ⏳ (next milestone)

The core architectural upgrades required for autonomous delivery (parallelism, replanning, experiment tracking, domain awareness) are implemented. Remaining work focuses on persisting evaluator results back to GOALS.md and broader QA.

---

## Completed Phases

### Phase 1: Goal Evaluator & Rich Validators ✅
- Files: `core/goal_evaluator.py`, `core/validators.py`, `models.py`, `core/tester.py`.
- Result: Goals can be checked against pytest/npm results, DS metrics, and API specs. Acceptance criteria can reference HTTP, schema, security, type, and data-quality validators.

### Phase 2: Parallel Task Execution ✅
- Files: `core/orchestrator.py`, `core/parallel_executor.py`.
- Result: Run loop batches ready tasks via `get_ready_tasks_batch()` and executes them concurrently with `ParallelExecutor`. TASKS.md writes and step counting are guarded by locks to avoid race conditions.

### Phase 3: Replan Event Generation ✅
- Files: `core/replanner.py`, `core/orchestrator.py`, `models.py`.
- Result: Failed tasks trigger a Replanner agent that proposes 1–3 remediation tasks. New work is added to the task graph, REPLAN/REPLAN_REJECTED events are logged, and depth limits prevent infinite loops.

### Phase 4: Experiment Logger Integration & Job Queue ✅
- Files: `core/orchestrator.py`, `core/reviewer.py`, `core/long_jobs.py`, `tools/run_script.py`.
- Result: Long-running commands are enqueued via `run_script --mode enqueue --task-id ...`. The orchestrator executes them outside Claude, waits for completion, captures logs/metrics under `.agentic/history/`, and reviewer context lists recent experiment runs.

### Phase 5: Domain-Specific Context ✅
- Files: `core/domain_context.py`, `core/orchestrator.py`.
- Result: The orchestrator detects whether the workspace is DS/backend/frontend/tooling and injects tailored guardrails into every task prompt.

---

## Remaining Phase

### Phase 6: Persist Goal Evaluations (In Progress)

**Objective:** Ensure evaluator results update GOALS.md so completion status survives orchestrator restarts.

**Tasks:**
1. Extend `GoalsManager` with a method to persist `Goal.achieved` + `confidence` back to disk.
2. Enhance `_check_completion()` to:
   - Skip evaluation until all tasks are complete.
   - Call `GoalEvaluatorRegistry`.
   - Update `Goal` objects and call new persistence method.
   - Emit detailed `GOAL_CHECK` events (evidence, blockers).
3. Add tests covering:
   - Passing all goals (should mark complete).
   - Metrics below threshold (should remain pending with blockers recorded).
4. Document workflow in README (how evaluators drive completion and where evidence is stored).

**Risks:** Low. Main concerns are GOALS.md merge conflicts if multiple runs edit simultaneously. Mitigate by writing only when evaluations change.

---

## Post-Phase-6 Hardening Ideas
- Run orchestrator against a real multi-goal workspace to baseline throughput improvements from parallelism.
- Capture telemetry on REPLAN frequency to tune prompts (e.g., if too many redundant tasks appear).
- Surface experiment summaries in CLI output (not just reviewer context) for faster human auditing.
- Optional: expose `max_parallel_tasks`, `max_replan_depth`, job-polling intervals, and domain detection overrides in `orchestrator.config.yaml`.
