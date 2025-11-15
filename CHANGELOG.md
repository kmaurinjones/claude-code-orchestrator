# Changelog

All notable changes to the Agentic Orchestrator project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.1] - 2025-11-16

### Added
- **Flexible Acceptance Checks**: `pattern_in_file` now honors metadata-driven flags for case-insensitive regex and minimum match counts to avoid brittle false failures.
- **New Verification Types**: Added `pattern_count`, `file_word_count`, `section_word_count`, and `no_placeholder_text` check types so plans can enforce word-count ranges, heading-scoped budgets, and placeholder removal directly from TASKS.md.

### Changed
- **Tester Enhancements**: All new verifiers run inside the existing tester/critic pipeline, producing deterministic results before reviews and ensuring future runs report accurate status for market-prediction, introduction, and roadmap tasks.

## [0.8.0] - 2025-11-16

### Added
- **Planner/Actor/Critic Contracts**: Introduced shared dataclasses (`PlanDecision`, `ActorOutcome`, `CriticVerdict`) plus dedicated context builders so every stage shares consistent metadata and operator guidance.
- **Actor + Planner Components**: New `core/actor.py`, `core/planner.py`, and prompt helpers encapsulate task execution, deterministic testing, docs/changelog updates, and remediation planning.

### Changed
- **Loop Architecture**: The orchestrator now runs an explicit planner → actor → critic loop; reviewer duties moved under the critic, and planner owns feedback ingestion, task state, and doc/changelog updates.
- **Parallel Executor**: Updated to execute planner decisions (not raw tasks) so concurrency works with the new abstractions.

## [0.7.8] - 2025-11-15

### Added
- **History Recording System**: New `HistoryRecorder` persists summarized task events to `.agentic/history/tasks.jsonl`
  - Records task status, attempts, review/critic summaries, and test results
  - Separate from full event log - focuses on task-level outcomes
  - Enables historical analysis and pattern detection across runs
- **User Feedback TTL System**: Active feedback now has time-to-live of 5 steps
  - Prevents stale feedback from affecting unrelated tasks
  - Feedback automatically pruned after 5 steps of inactivity
  - New `_active_user_feedback` tracks (entry, step) tuples
- **Surgical Mode**: New CLI flag `--surgical` for focused, minimal-edit runs
  - `--surgical-path` flag accepts multiple paths to constrain scope
  - Tight scope enforcement prevents scope creep
  - Ideal for targeted bug fixes and small enhancements
- **Experiment Scheduler**: New `orchestrate experiment` command for long-running jobs
  - Schedule commands directly without starting orchestrator run
  - Supports timeout, workdir, run-name, notes, task-id, metrics-file parameters
  - Jobs tracked in experiment history for analysis
- **Interview Fresh Mode**: New `--fresh` flag ignores existing GOALS/TASKS
  - Allows clean restart even when previous plan exists
  - Complements existing `--update` mode for incremental changes
- **Enhanced Completion Summary**: Domain-aware usage guide generation improved
  - Reports completion reason (SUCCESS/MAX_STEPS/NO_TASKS)
  - Shows incomplete goals and task statistics
  - Warns when project not production-ready (goals incomplete/tasks failed)
  - Better fallback instructions when subagent times out
- **Reviewer Auto-Accept Enhancement**: Smarter timeout handling
  - Extracted `_handle_reviewer_timeout_auto_pass()` method for reusability
  - Auto-accepts both pre-review and post-review timeouts when tests pass
  - Reduces false failures from reviewer capacity issues

### Changed
- **User Feedback Architecture**: Replaced immediate consumption with TTL-based lifecycle
  - Feedback persists across multiple tasks (up to 5 steps)
  - General feedback applies to all tasks until TTL expires
  - Task-specific feedback applies only to matching task ID
  - New `_prune_user_feedback()` and `_ingest_user_feedback()` methods
- **Critic Integration**: Now receives domain context for smarter standards enforcement
  - Domain-specific rules (DS projects allow notebooks, backend enforces API standards)
  - Updated `Critic.__init__()` signature requires workspace parameter
- **Reviewer Integration**: Log workspace now required parameter
  - Enables reviewer to write analysis artifacts to `.agentic/` directory
  - Supports future reviewer self-improvement features
- **Replanner Integration**: Log workspace now required parameter
  - Consistent with reviewer changes
  - Enables richer diagnostic output
- **Interview Update Flow**: Auto-detects existing GOALS/TASKS
  - If files exist and `--fresh` not specified, defaults to update mode
  - Clearer user instructions to "continue the plan" vs restart
  - Reduces accidental plan overwriting
- **Subagent Execution**: `log_workspace` parameter now standard
  - All subagents log to `.agentic/logs/subagents/` directory
  - Consistent workspace handling across orchestrator
- **Task Recording**: Now captures full history snapshot on completion/failure
  - `_log_task_history_event()` called after every task outcome
  - Provides audit trail independent of verbose event log
- **ExperimentManager**: New module in `core/experiments.py`
  - Replaces inline experiment logic
  - Supports standalone `orchestrate experiment` command

### Fixed
- **Reviewer Timeout Auto-Pass**: Now checks before retry logic
  - Prevents unnecessary retries when tests already prove success
  - Applies to both initial review and retry review
  - More reliable completion when reviewer capacity exhausted
- **Domain Detection**: Moved from per-task to orchestrator initialization
  - `self.project_domain` computed once at startup
  - Eliminates redundant filesystem scans on every task
  - Domain context now consistent across entire run

## [0.6.2] - 2025-11-13

### Added
- **Completion Summary System**: Orchestrator generates domain-specific usage guide when run completes
  - Spawns Sonnet subagent to analyze completed work and generate contextual instructions
  - Shows quick start commands, key CLI commands, configuration locations, and next steps
  - Domain-aware: DS projects get training/metrics guidance, backend gets server/API docs, frontend gets dev/build commands
  - Displays formatted summary with goals achievement, task statistics, and log file locations
- **Auto-Completion Check**: Tasks with pre-satisfied acceptance criteria + critic standards auto-complete without actor phase
  - Pre-checks acceptance criteria before spawning subagent
  - Runs critic evaluation on existing code
  - Saves Claude calls when work already meets requirements
- **Production-Readiness Critic**: Comprehensive quality validation as final gate before task completion
  - Module docstrings required for all Python files
  - No bare except clauses - must specify exception types
  - No TODO/FIXME/HACK comments - technical debt must be resolved
  - No debug print() statements - must use proper logging
  - No hardcoded credentials - passwords/API keys/secrets must be externalized
  - Function docstrings required for public functions
  - Markdown docs must have headers and valid internal links
  - Config files checked for credentials
  - Ruff linting must pass (non-negotiable)

### Changed
- **User Feedback Template**: Simplified instructions - removed prescriptive formatting, now freeform
- **Changelog Entries**: No longer append task IDs like "(task-008)" to keep entries meaningful long-term
- **Critic Philosophy**: Reframed as production-readiness gate with strict but fair standards
- **Orchestrator Completion Flow**: Now generates usage summary before returning completion status

### Removed
- Obsolete test files and documentation (HANDOFF.md, IMPLEMENTATION_PLAN.md, STATUS_REPORT.md, TEST_README.md)
- Old test workspace directory (test-orchestrator-v0.5.0/)

## [0.6.1] - 2025-11-13

### Added
- **Long-Running Job Queue**: Subagents can enqueue multi-hour commands via `run_script --mode enqueue --task-id <task>`
  - New `LongRunningJobManager` executes queued jobs outside Claude to free up subagent capacity
  - Jobs stream logs to `.agentic/history/logs/` and append experiment metadata to `experiments.jsonl`
  - Orchestrator blocks task review until all task-linked jobs complete
  - Queue management: `process_queue()`, `poll()`, `wait_for_task_jobs(task_id)` APIs
- **Actor/Critic Loop**: Task completion now requires passing both functional review AND coding standards check
  - New `Critic` enforces snake_case file names, no trailing whitespace, and optional Ruff lint checks
  - Critic findings logged per attempt; tasks blocked until violations resolved
  - Integrates into orchestrator workflow: actor runs task → critic evaluates → review only if critic passes
  - Critic feedback surfaces in task summaries and next-action guidance

### Changed
- **Task Model**: Added `critic_feedback` field to track coding standards violations across attempts
- **run_script Tool**: Added `--task-id` and `--mode` (blocking/enqueue) parameters for job queue integration
- **Orchestrator Run Loop**: Now polls job queue and waits for task jobs before running tests/review
- **Reviewer Prompt**: Updated to reflect enqueue workflow (`--mode enqueue`) for commands >2 minutes
- **Task Success Criteria**: Three-way check now required: tests pass AND review passes AND critic passes

### Fixed
- Long commands no longer block Claude CLI during execution - handed off to orchestrator job queue
- Coding standard violations now caught before task completion instead of polluting codebase

## [0.6.0] - 2025-11-13

### Added
- **User Feedback System**: Live feedback during execution via `.agentic/current/USER_NOTES.md` with section-based parsing and automatic archiving
- **Automatic Documentation**: Maintains `docs/` directory with architecture, components, scripts, API, and troubleshooting documentation
- **Automatic Changelog**: Semantic versioning with auto-increment based on change type (Added/Changed/Fixed/Removed/Attempted)
- **Goal Evaluator System**: Data-driven goal completion with pluggable adapters (TestSuiteEvaluator, MetricThresholdEvaluator, APIContractEvaluator)
- **Rich Validators**: Extended verification checks from 3 to 9 types (HTTP endpoints, metric thresholds, JSON schema, security scans, type checks, data quality)
- **Parallel Task Execution**: Concurrent execution of independent tasks via `ParallelExecutor` with thread-safe state management
- **Automated Replanning**: Failed tasks trigger `Replanner` agent that generates remediation tasks instead of blind retries
- **Experiment History Integration**: Reviewer context includes recent experiment runs from `.agentic/history/experiments.jsonl`
- **Domain-Specific Context**: Detects project type (DS/backend/frontend/tooling) and injects tailored guardrails into subagent prompts

### Changed
- **Goal Completion**: Now data-driven via evaluators instead of manual flag checking - goals must pass verification to be considered achieved
- **Task Verification**: Tester delegates to rich validators for HTTP, metrics, schema, security, type-check, and data-quality checks
- **Failure Handling**: Exhausted tasks spawn remediation tasks via replanner instead of marking failed and stopping
- **Reviewer Prompts**: Include user feedback, experiment history, and domain-specific safety checks
- **Run Loop**: Batches ready tasks and executes in parallel waves up to `max_parallel_tasks` limit

### Fixed
- **Goal Achievement**: Goals now properly flip to `achieved=True` when evaluators confirm completion criteria met
- **Verification Gaps**: No longer limited to file_exists/command_passes/pattern_in_file - now supports comprehensive validation

## [0.5.21] - 2025-10-28

### Added
- **Reviewer Retry Loop**: If the first review times out, the orchestrator automatically retries with a condensed prompt and higher turn budget before falling back to auto-pass logic
- **CLI Version Flag**: `orchestrate --version` now prints the installed orchestrator version and exits immediately

### Changed
- **Reviewer Prompting**: Added explicit instructions to prioritise operator notes and respond with JSON-only output when running in condensed mode
- **Task Agent Prompts**: Now reference the new script runner utility so long-running commands get logged and tracked consistently

### Fixed
- **Repeated Reviewer Timeouts**: Detection of timeout markers now drives automatic retries instead of leaving tasks stuck in NEEDS_FOLLOWUP

## [0.5.19] - 2025-10-28

### Added
- **Operator Notes Integration**: `NOTES.md` is now auto-created and surfaced to every subagent and reviewer so human guidance is always front and centre
- **Script Runner Tool**: `python -m orchestrator.tools.run_script` executes long jobs, captures logs, applies timeouts, and records runs in `.agentic/history/experiments.jsonl`
- **Experiment Logger**: Lightweight experiment registry stores command metadata, metrics, and artifact paths for later comparison

### Changed
- **Task & Reviewer Context**: Prompts now include operator notes, script-runner usage guidance, and shorter context to keep agents focused
- **Reviewer Instructions**: Every review highlights operator notes before delivering the PASS/FAIL summary and next steps

### Fixed
- **Escaped JSON Handling**: Reviewer parser now decodes JSON blocks containing escaped newlines/quotes so structured feedback is always captured

## [0.5.18] - 2025-10-28

### Added
- **Resilient Reviewer Parsing**: Reviewer output now tolerates missing JSON blocks by extracting fallback text and flagging max-turn situations with actionable guidance
- **Lean Reviewer Context**: Dedicated reviewer context keeps prompts short by showing only top goals, recent feedback, and the latest task summary

### Changed
- **Reviewer Turn Budget**: Increased allowance (16 turns) so Claude can complete structured responses without repeated retries
- **Task Feedback Loop**: When explicit next steps are missing, the orchestrator now records reviewer summaries as follow-up actions to target rework
- **Test Reporting**: Reviewer prompts summarize pass/fail counts and highlight only failing checks, making reviews quicker to digest
- **Auto-Pass Logic**: If all checks pass and the reviewer still times out, the orchestrator now accepts the task with a warning instead of burning attempts

## [0.5.11] - 2025-10-27

### Added
- **Task Dependency Parsing**: TASKS.md now supports "Depends on" syntax for explicit task dependencies
  - Parses both list syntax `Depends on: ["task-002"]` and comma-separated `Depends on: task-002, task-003`
  - Uses `ast.literal_eval` for safe list parsing with comma-separated fallback
  - Populates `task.depends_on` list and wires dependency edges into task graph
  - Tasks won't execute until all dependencies are complete

- **TaskGraph API Enhancements**: New `create_task()` method for programmatic task creation
  - Supports all task properties: title, description, priority, depends_on, acceptance_criteria
  - Auto-generates task IDs and handles dependency wiring
  - Returns created Task object for immediate use

- **Stock-Picker Test Infrastructure**: Added smoke tests and import configuration
  - `tests/test_smoke.py`: Basic smoke test to keep pytest green during development
  - `tests/conftest.py`: Ensures src/ package is importable without installation
  - Prevents pytest collection failures and VIRTUAL_ENV path mismatches

### Changed
- **TaskGraph Type Hints**: Improved type annotations with `Iterable` for flexible input
- **add_task() Return Value**: Now returns the added Task object for chaining

### Fixed
- **Dependency Scheduling**: Tasks with dependencies no longer execute prematurely
  - task-001 now properly waits for task-002 completion
  - Graph edges correctly represent dependency relationships

- **Test Environment Issues**: Resolved VIRTUAL_ENV path mismatch in stock-picker
  - Added pytest to stock-picker dev dependencies
  - Tests now run in correct local environment instead of falling back to orchestrator's venv

## [0.5.10] - 2025-10-27

### Added
- **Configurable Subagent Turns**: New `subagent_max_turns` setting controls Claude CLI turn budget (defaults to 15)
  - Applied across planner, task execution, and audit subagents
  - Prevents premature `error_max_turns` failures on complex implementation tasks
- **Verification Controls**: `skip_integration_tests` and optional `pytest_addopts` settings in `orchestrator.config.yaml`
  - Integration tests are skipped by default by injecting `-m "not integration"`
  - Environment override `ORCHESTRATOR_RUN_INTEGRATION_TESTS=1` forces integration tests when needed

### Changed
- **CLI Run Output**: Displays new configuration values (subagent turns, integration skip, pytest opts) when orchestrator starts
- **Verification Enhancements**: `Verifier` now sets `PYTEST_ADDOPTS` before running pytest-based checks, respecting config and env overrides

## [0.5.9] - 2025-10-27

### Added
- **Detailed Subagent Execution Logging**: Complete visibility into subagent operations
  - New `.agentic/logs/subagents/{trace_id}.json` files created for each subagent execution
  - Each log contains:
    - Full instruction/prompt sent to Claude Code CLI
    - Complete raw stdout and stderr from execution
    - Parsed structured result
    - Execution duration in seconds
    - Return code and error details
    - Workspace path and model used
    - Task ID, description, and step number
    - Previous attempt feedback (if retry)
  - Logs created for ALL execution paths: success, error, timeout, exceptions, CLI failures
  - Enables deep debugging of subagent behavior and file creation issues

### Technical Details
- **New Method**: `_log_detailed_execution()` in `Subagent` class
- **Log Location**: `.agentic/logs/subagents/` directory (auto-created)
- **Log Format**: Pretty-printed JSON for easy inspection
- **Timing**: Execution duration tracked from start to completion
- **Coverage**: Logs created for:
  - Successful executions (with parsed JSON response)
  - JSON parse failures (fallback mode)
  - CLI errors (non-zero return codes)
  - Timeouts (captures partial stdout/stderr)
  - Python exceptions (captures error details)

### Use Cases
- Debug why files aren't created in expected locations
- See exactly what commands subagents are running
- Understand subagent reasoning and decision-making
- Track down path resolution issues
- Analyze performance bottlenecks (via duration_seconds)
- Review retry attempts and feedback loops

## [0.5.8] - 2025-10-27

### Added
- **Dynamic Task Prioritization System**: Tasks now re-prioritized every selection cycle based on execution context
  - New `_calculate_dynamic_priority()` method analyzes execution state
  - Boosts tasks related to recently completed work (+2.0 priority)
  - Boosts tasks whose dependencies just completed (+1.0 priority)
  - Boosts tasks blocking other work (+1.5 per blocked task)
  - Penalizes tasks similar to in-progress work (-3.0 to avoid duplication)
  - Priorities react dynamically to completed, in-progress, and failed workstreams

- **Task Complexity Analysis**: Automatic classification of tasks for optimal parallelization
  - New `_estimate_task_complexity()` method categorizes tasks as: tiny, small, medium, or large
  - Analyzes description length, keywords, and dependency count
  - 'Tiny' tasks: format, lint, style, comment, import, constant changes
  - 'Small' tasks: fix, update, add function, write test, document
  - 'Medium' tasks: integrate, implement, create class, add feature
  - 'Large' tasks: implement entire system, full architecture, framework, redesign
  - Complexity affects parallelization strategy and priority scoring

- **Enhanced Parallelization for Small Tasks**: Aggressive parallel execution of tiny/small tasks
  - **Strategy 1 (Tiny/Small tasks)**: Up to 6 tasks in parallel (2x normal limit)
  - **Strategy 2 (Medium tasks)**: Conservative parallelization up to 3 tasks
  - **Strategy 3 (Large tasks)**: Never parallelized with other tasks
  - Foundational and failed tasks always run sequentially for safety
  - Console logging shows parallelization decisions with complexity info

- **Task Decomposition Suggestions**: System identifies opportunities to break down large tasks
  - New `_suggest_task_decomposition()` method runs every 5 steps
  - Detects when 3+ large/medium tasks are in backlog
  - Logs suggestions for breaking tasks into smaller parallelizable subtasks
  - Helps maintain focus on "smallest constituent parts" philosophy

### Changed
- **Task Selection Algorithm Completely Rewritten**: Dynamic context-aware prioritization
  - Priority order now includes dynamic boosts: fix > audit > failed > foundational > at-risk > **dynamically boosted** > new
  - Complexity score added to prioritization: tiny (4) > small (3) > medium (2) > large (1)
  - Tasks sorted by 8 factors: fix status, audit status, failures, foundational, at-risk, dynamic boost, complexity, base priority
  - Selection reacts to execution state every time it's called

- **Parallelization Limits Adjusted**: Now adaptive based on task complexity
  - Tiny/small tasks: up to 6 parallel (was 3)
  - Medium tasks: up to 3 parallel (unchanged)
  - Large tasks: 1 sequential (new constraint)
  - Better utilization of subagent capacity for quick tasks

- **Reflection Enhanced**: Added task decomposition check during periodic reflection
  - Runs every 5 steps alongside existing reflection
  - Proactively identifies complex tasks that should be broken down

### Technical Details
- **New Methods**:
  - `_estimate_task_complexity(task)` → 'tiny' | 'small' | 'medium' | 'large'
  - `_calculate_dynamic_priority(task)` → float (boost/penalty)
  - `_tasks_similar(title1, title2)` → bool (3+ shared words)
  - `_suggest_task_decomposition()` → None (logs suggestions)

- **Modified Methods**:
  - `_select_next_tasks()`: Completely rewritten with complexity analysis and dynamic prioritization
  - Main loop: Added decomposition check during reflection cycle

- **Performance Impact**:
  - Complexity analysis: O(n) per task selection (where n = ready tasks)
  - Dynamic priority calculation: O(n*m) where m = recently completed tasks
  - Minimal overhead, significant parallelization gains for small tasks

## [0.5.7] - 2025-10-27

### Fixed
- **CRITICAL: Exact Path Enforcement**: Fixed subagents using similar existing directories instead of creating exact paths
  - Problem: Task specifying `src/stock_picker/engine/file.py` would create file in existing `src/stock_picker/analysis/` instead
  - Solution: Enhanced FILE CREATION RULES with explicit instructions to create EXACT paths as specified
  - Added verification step: "Verify the full path matches the task specification before creating the file"
  - Added negative example: "DO NOT put files in similar existing directories"
  - Subagents now required to create the exact directory structure specified, not choose convenient existing ones

### Changed
- **Subagent Instructions Enhanced**: FILE CREATION RULES section renamed to "FILE CREATION RULES - EXACT PATH REQUIRED"
  - Added explicit example showing correct vs incorrect path creation
  - Added instruction to verify path before file creation
  - Emphasized creating exact directory structure even when similar directories exist

## [0.5.6] - 2025-10-27

### Added
- **Directory Tree Context in Subagent Prompts**: Automatic project structure visibility
  - New `_generate_directory_tree()` function generates concise tree view
  - Integrated into every subagent instruction prompt
  - Shows current project structure up to 3 levels deep
  - Helps subagents understand where to create files in nested paths
  - Ignores common directories: .agentic, .git, .venv, __pycache__, node_modules, etc.
  - Limited to 50 files to prevent token bloat

### Changed
- **Subagent Instructions Enhanced**: Added "Current Project Structure" section to all prompts
  - Shows directory tree before task instructions
  - Provides explicit context about existing file organization
  - Helps prevent files being created in wrong locations

## [0.5.5] - 2025-10-27

### Fixed
- **CRITICAL: Nested Path Creation**: Fixed subagent file creation to respect full paths
  - Changed from "CREATE ALL FILES HERE" (flat structure) to "Create files with their FULL PATHS"
  - Subagents now explicitly instructed to create parent directories first (mkdir -p)
  - Files like `src/module/core/file.py` now created in proper nested directories
  - Added explicit instruction: "All paths are relative to the current working directory"
  - Test verification: test_nested_paths.py confirms nested directory structures work correctly

### Changed
- **Subagent File Creation Rules**: Completely rewritten for clarity
  - Rule 2 changed from generic "CREATE ALL FILES HERE" to specific "FILE CREATION RULES"
  - Explicit instruction to create necessary parent directories first
  - Clear examples of full path creation (e.g., src/module/file.py)
  - Maintains prohibition on creating files in .agentic subdirectories

## [0.5.4] - 2025-10-27

### Added
- **Periodic Code Quality Audits**: Automatic quality audits every 10 steps
  - Analyzes code quality, maintainability, organization, and safety
  - Identifies technical debt and refactoring opportunities
  - Uses Sonnet model for higher quality analysis (vs Haiku for regular tasks)
  - Generates 2-4 specific, actionable audit tasks automatically
- **Audit Task Priority Tier**: New task prioritization level
  - Priority order: fix tasks > audit tasks > failed tasks > foundational > at-risk > new
  - Audit tasks have priority 7 (high but below critical fixes at 8-9)
  - Ensures quality improvements are addressed systematically
- **Configurable Model Selection**: Subagent model is now configurable
  - Regular tasks use Haiku (cost-efficient)
  - Audit tasks use Sonnet (higher quality analysis)
  - Model parameter added to Subagent constructor

### Changed
- **Path Validation**: Added defensive checks throughout
  - Orchestrator validates workspace and project_root are absolute
  - Subagent validates workspace is absolute before execution
  - Verifier validates workspace is absolute on initialization
  - Prevents potential path-related edge cases

### Fixed
- Removed unused variable in `_analyze_failures_and_create_fixes` method
- Path handling made more robust with explicit validation

## [0.5.3] - 2025-10-26

### Added
- **MVP-First Development Model**: Complete architectural shift to incremental development
  - Sequential execution with tight build-test-fix loops
  - Immediate testing after each build
  - No progression until task is verified working
  - Console phases: `[BUILD]`, `[TEST]`, `[SUCCESS]`, `[FIX NEEDED]`
- **Intelligent Task Prioritization**: New priority order with foundational task detection
  - Priority: fix tasks > failed tasks > foundational > at-risk > new
  - Auto-detects foundational tasks by keywords (mvp, init, setup, base, core, etc.)
- **Enhanced Subagent Instructions**: Explicit MVP-first philosophy in all subagent tasks
  - Build ONE thing at a time
  - Test immediately after building (functional, not just assertions)
  - Fix NOW if it doesn't work
  - Include evidence of working code in responses

### Changed
- **Reduced Default Parallelism**: `max_parallel_tasks` changed from 10 to 3
  - Foundational tasks never run in parallel
  - Encourages sequential validation over parallel execution
- **Task Execution Model**: Refactored from async parallel to sequential build-test-fix loops
  - Maximum 3 attempts per task before marking as failed
  - Tasks must be verified working before moving to next
- **Task Generation**: Updated planner to focus on MVP-first incremental tasks
  - Small incremental tasks over large complex ones
  - Bug fixes marked as HIGHEST PRIORITY
  - Clear, immediately verifiable success criteria

### Fixed
- Path resolution issues in task execution
- Workspace directory handling in subagents

## [0.5.2] - 2025-10-26

### Added
- **Intelligent Failure Analysis**: Automatic pattern detection and fix task generation
  - Analyzes failing tasks after each execution batch
  - Categorizes failures: path issues, verification failures, import errors, dependencies
  - Auto-generates high-priority fix tasks when 2+ tasks fail with same pattern
  - Adds fix tasks to TASKS.md under "# Auto-Generated Fix Tasks"
  - Logs all failure analysis events for debugging

### Changed
- Task retry logic enhanced with automatic fix task creation for systemic issues

## [0.5.1] - 2025-10-26

### Added
- **Step Counting System**: Complete migration from "iteration" to "step" terminology
  - Steps count every Claude Code call (orchestrator + subagents)
  - Step numbers in all console output and logs
- **Version Tracking**: Added version field to all JSONL logs
  - Every log event includes orchestrator version for debugging
  - Helps identify version-specific issues
- **Code Reuse Directive**: Explicit instructions to all subagents
  - Search for existing modules before writing new code
  - Inherit from existing base classes
  - Import and use existing utilities
  - Extend existing patterns

### Changed
- Renamed all "iteration" references to "step" throughout codebase
- Updated CLI arguments: `--min-steps`, `--max-steps` (previously `--min-iterations`, `--max-iterations`)
- Updated config schema: `min_steps`, `max_steps` fields

### Fixed
- Workspace path resolution: Files now correctly created in project root, not `.agentic/`
- Path handling uses absolute paths throughout

## [0.4.6] - 2025-10-26

### Initial Release
- Self-orchestrating agentic system using Claude Code CLI
- Task graph management with dependencies
- Goal tracking with confidence scoring
- Automated verification system
- JSONL event logging
- Parallel task execution via ThreadPoolExecutor
- Subagent wrapper for Claude Code CLI
