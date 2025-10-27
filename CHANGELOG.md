# Changelog

All notable changes to the Agentic Orchestrator project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

## [0.4.6] - 2025-10-25

### Initial Release
- Self-orchestrating agentic system using Claude Code CLI
- Task graph management with dependencies
- Goal tracking with confidence scoring
- Automated verification system
- JSONL event logging
- Parallel task execution via ThreadPoolExecutor
- Subagent wrapper for Claude Code CLI
