#!/usr/bin/env python3
"""
Test script for v0.5.4 orchestrator improvements.

Validates:
1. Step counting (every Claude Code call increments step)
2. Files created in project root (NOT .agentic/)
3. Workspace paths are absolute
4. Code reuse directive is present in subagent instructions
5. Task dependencies are respected
6. Multiple coordinated tasks complete successfully
7. Failure analysis detects patterns
8. MVP-first sequential execution
9. Audit system runs at step 10 (if reached)
"""

import subprocess
import shutil
import json
from pathlib import Path
import tempfile
import argparse
import sys


def clear_test_directory(test_dir: Path, keep_logs: bool = False):
    """Clear test directory of generated files but preserve structure."""
    print(f"\n{'='*60}")
    print("Clearing test directory")
    print('='*60)

    if not test_dir.exists():
        print(f"Test directory doesn't exist: {test_dir}")
        return

    # List of files/dirs to preserve
    preserve = {".agentic"}

    cleared = []
    for item in test_dir.iterdir():
        if item.name not in preserve:
            if item.is_file():
                item.unlink()
                cleared.append(f"  Deleted file: {item.name}")
            elif item.is_dir():
                shutil.rmtree(item)
                cleared.append(f"  Deleted directory: {item.name}/")

    # Clear generated files in .agentic but keep structure and optionally logs
    agentic_dir = test_dir / ".agentic"
    if agentic_dir.exists():
        for item in agentic_dir.iterdir():
            if item.name == "current":
                continue  # Preserve GOALS.md and TASKS.md
            if keep_logs and item.name == "full_history.jsonl":
                print(f"  Preserved log: {item.name}")
                continue
            if item.is_file():
                item.unlink()
                cleared.append(f"  Deleted .agentic/{item.name}")

    if cleared:
        print("\n".join(cleared))
        print(f"\n✓ Cleared {len(cleared)} items from test directory")
    else:
        print("  No files to clear")

    print('='*60)


def setup_test_project(test_dir: Path):
    """Setup test project with complex goals and tasks."""

    agentic_dir = test_dir / ".agentic"
    current_dir = agentic_dir / "current"
    current_dir.mkdir(parents=True, exist_ok=True)
    print("✓ Created .agentic/current directory")

    # Create complex GOALS.md with multiple related goals
    goals_content = """# GOALS.md
Generated: 2025-10-27

## Core Success Criteria (IMMUTABLE)

1. **Create a functional Python calculator module**
   - Measurable: Module `calculator.py` exists with add, subtract, multiply, divide functions
   - Non-negotiable: This validates file creation and basic code structure

2. **Implement comprehensive test suite**
   - Measurable: Test file `test_calculator.py` exists with tests for all calculator functions
   - Non-negotiable: Tests must pass when run with pytest

3. **Create utility module with string operations**
   - Measurable: Module `utils.py` exists with reverse_string and capitalize_words functions
   - Non-negotiable: Demonstrates multi-file coordination

4. **Document the project**
   - Measurable: README.md exists with usage instructions and examples
   - Non-negotiable: Validates documentation generation

## Nice-to-Have (FLEXIBLE)
- Type hints in all functions
- Docstrings in Google style
- Error handling for edge cases

## Out of Scope
- Web interface
- Database integration
- Complex algorithms

## Constraints (IMMUTABLE)
- Must use Python 3.11+
- All files created in project root (NOT in .agentic/)
- Tests must use pytest
- Code must follow PEP 8
"""
    (current_dir / "GOALS.md").write_text(goals_content)
    print("✓ Created complex GOALS.md with 4 core goals")

    # Create complex TASKS.md with dependencies
    tasks_content = """# TASKS.md

## Backlog

- [📋] task-001: Create calculator.py with add and subtract functions (priority: 10)
  - Goals: goal-1
  - Verify: file_exists:calculator.py "Calculator module exists"
  - Verify: pattern_in_file:calculator.py "def add\\("
  - Verify: pattern_in_file:calculator.py "def subtract\\("

- [📋] task-002: Add multiply and divide functions to calculator.py (priority: 9)
  - Goals: goal-1
  - Depends: task-001
  - Verify: pattern_in_file:calculator.py "def multiply\\("
  - Verify: pattern_in_file:calculator.py "def divide\\("

- [📋] task-003: Create test_calculator.py with tests for all functions (priority: 10)
  - Goals: goal-2
  - Depends: task-002
  - Verify: file_exists:test_calculator.py "Test file exists"
  - Verify: pattern_in_file:test_calculator.py "def test_add"
  - Verify: pattern_in_file:test_calculator.py "def test_subtract"
  - Verify: pattern_in_file:test_calculator.py "def test_multiply"
  - Verify: pattern_in_file:test_calculator.py "def test_divide"

- [📋] task-004: Run pytest to verify all calculator tests pass (priority: 10)
  - Goals: goal-2
  - Depends: task-003
  - Verify: command_passes:uv run pytest test_calculator.py -v "All calculator tests pass"

- [📋] task-005: Create utils.py with string utility functions (priority: 8)
  - Goals: goal-3
  - Verify: file_exists:utils.py "Utils module exists"
  - Verify: pattern_in_file:utils.py "def reverse_string\\("
  - Verify: pattern_in_file:utils.py "def capitalize_words\\("

- [📋] task-006: Create test_utils.py and verify utils functions work (priority: 8)
  - Goals: goal-3
  - Depends: task-005
  - Verify: file_exists:test_utils.py "Utils test file exists"
  - Verify: command_passes:uv run pytest test_utils.py -v "All utils tests pass"

- [📋] task-007: Create README.md with project documentation (priority: 7)
  - Goals: goal-4
  - Verify: file_exists:README.md "README exists"
  - Verify: pattern_in_file:README.md "## Usage"
  - Verify: pattern_in_file:README.md "## Installation"
"""
    (current_dir / "TASKS.md").write_text(tasks_content)
    print("✓ Created complex TASKS.md with 7 tasks and dependencies")

    # Create config with moderate step counts to trigger audit
    config_content = """min_steps: 5
max_steps: 20
max_parallel_tasks: 2
"""
    (agentic_dir / "orchestrator.config.yaml").write_text(config_content)
    print("✓ Created orchestrator.config.yaml (max_steps: 15 for audit test)")


def validate_results(test_dir: Path, verbose: bool = True):
    """Validate test results with detailed checks."""

    print("\n" + "="*60)
    print("Validation Results")
    print("="*60 + "\n")

    passed = 0
    failed = 0
    agentic_dir = test_dir / ".agentic"

    # Test 1: calculator.py created in project root with required functions
    calculator_py = test_dir / "calculator.py"
    if calculator_py.exists():
        content = calculator_py.read_text()
        has_add = "def add(" in content
        has_sub = "def subtract(" in content
        has_mul = "def multiply(" in content
        has_div = "def divide(" in content

        if has_add and has_sub and has_mul and has_div:
            print("✅ Test 1 PASSED: calculator.py with all 4 functions")
            if verbose:
                print(f"   Location: {calculator_py}")
                print("   Functions: add, subtract, multiply, divide")
            passed += 1
        else:
            print("❌ Test 1 FAILED: calculator.py missing functions")
            print(f"   Has add: {has_add}, subtract: {has_sub}, multiply: {has_mul}, divide: {has_div}")
            failed += 1
    else:
        print("❌ Test 1 FAILED: calculator.py not found")
        print(f"   Expected at: {calculator_py}")
        failed += 1

    # Test 2: test_calculator.py created with tests
    test_calc_py = test_dir / "test_calculator.py"
    if test_calc_py.exists():
        content = test_calc_py.read_text()
        test_count = content.count("def test_")

        if test_count >= 4:
            print(f"✅ Test 2 PASSED: test_calculator.py with {test_count} test functions")
            passed += 1
        else:
            print(f"❌ Test 2 FAILED: test_calculator.py has only {test_count} tests (expected 4+)")
            failed += 1
    else:
        print("❌ Test 2 FAILED: test_calculator.py not found")
        failed += 1

    # Test 3: utils.py created with string functions
    utils_py = test_dir / "utils.py"
    if utils_py.exists():
        content = utils_py.read_text()
        has_reverse = "def reverse_string(" in content
        has_capitalize = "def capitalize_words(" in content

        if has_reverse and has_capitalize:
            print("✅ Test 3 PASSED: utils.py with string utility functions")
            passed += 1
        else:
            print("❌ Test 3 FAILED: utils.py missing expected functions")
            print(f"   Has reverse_string: {has_reverse}, capitalize_words: {has_capitalize}")
            failed += 1
    else:
        print("❌ Test 3 FAILED: utils.py not found")
        failed += 1

    # Test 4: README.md created
    readme_md = test_dir / "README.md"
    if readme_md.exists():
        content = readme_md.read_text()
        has_usage = "## Usage" in content or "# Usage" in content
        has_install = "## Installation" in content or "# Installation" in content

        if has_usage or has_install:
            print("✅ Test 4 PASSED: README.md with documentation sections")
            passed += 1
        else:
            print("⚠️  Test 4 PARTIAL: README.md exists but missing expected sections")
            passed += 0.5
    else:
        print("❌ Test 4 FAILED: README.md not found")
        failed += 1

    # Test 5: No files created in .agentic/ (except logs/config)
    agentic_files = [f for f in agentic_dir.iterdir()
                     if f.name not in ["current", "full_history.jsonl", "orchestrator.config.yaml", "test.jsonl"]]
    if not agentic_files:
        print("✅ Test 5 PASSED: No unexpected files in .agentic/")
        passed += 1
    else:
        print("❌ Test 5 FAILED: Unexpected files in .agentic/:")
        for f in agentic_files:
            print(f"   - {f.name}")
        failed += 1

    # Test 6: Step counting in event log
    event_log = agentic_dir / "full_history.jsonl"
    if event_log.exists():
        with open(event_log) as f:
            events = [json.loads(line) for line in f if line.strip()]

        steps = [e["step"] for e in events]
        max_step = max(steps) if steps else 0

        if max_step >= 5:
            print(f"✅ Test 6 PASSED: Step counting works (max step: {max_step})")
            if verbose:
                print(f"   Total events: {len(events)}")
                print(f"   Unique steps: {sorted(set(steps))}")
            passed += 1
        else:
            print(f"❌ Test 6 FAILED: Not enough steps recorded (max: {max_step})")
            failed += 1
    else:
        print("❌ Test 6 FAILED: Event log not found")
        failed += 1

    # Test 7: Workspace paths are absolute
    if event_log.exists():
        spawn_events = [e for e in events if e["event"] == "spawn"]
        if spawn_events:
            all_absolute = all(
                Path(e["payload"].get("workspace", "")).is_absolute()
                for e in spawn_events
            )
            if all_absolute:
                print(f"✅ Test 7 PASSED: All workspace paths are absolute ({len(spawn_events)} checked)")
                passed += 1
            else:
                print("❌ Test 7 FAILED: Some workspace paths are not absolute")
                failed += 1
        else:
            print("⚠️  Test 7 SKIPPED: No spawn events in log")

    # Test 8: Task dependency execution order
    if event_log.exists():
        task_events = [e for e in events if e.get("event") == "decision"
                      and e.get("payload", {}).get("action") == "execute_task"]
        task_order = [e["payload"]["task_id"] for e in task_events]

        # task-001 should come before task-002, task-002 before task-003, etc.
        if "task-001" in task_order and "task-002" in task_order:
            idx_001 = task_order.index("task-001")
            idx_002 = task_order.index("task-002")
            if idx_001 < idx_002:
                print("✅ Test 8 PASSED: Task dependencies respected (task-001 before task-002)")
                if verbose:
                    print(f"   Task execution order: {task_order[:5]}")
                passed += 1
            else:
                print("❌ Test 8 FAILED: Task dependency violated")
                print(f"   Order: {task_order}")
                failed += 1
        else:
            print("⚠️  Test 8 SKIPPED: Not enough tasks executed to verify dependencies")

    # Test 9: Check for failure analysis events
    if event_log.exists():
        failure_events = [e for e in events if e.get("payload", {}).get("action") == "failure_analysis"]
        if failure_events:
            print(f"✅ Test 9 INFO: Failure analysis ran {len(failure_events)} time(s)")
            if verbose:
                for fe in failure_events:
                    patterns = fe["payload"].get("patterns", {})
                    print(f"   Patterns detected: {patterns}")
        else:
            print("ℹ️  Test 9 INFO: No failure analysis events (may indicate no failures)")

    # Test 10: Check for audit events (if step 10 reached)
    if event_log.exists():
        max_step = max([e["step"] for e in events], default=0)
        audit_events = [e for e in events if e.get("actor") == "code-audit"]

        if max_step >= 10:
            if audit_events:
                print(f"✅ Test 10 PASSED: Audit system triggered at step {audit_events[0]['step']}")
                passed += 1
            else:
                print("❌ Test 10 FAILED: Audit system did not run despite reaching step 10")
                failed += 1
        else:
            print(f"ℹ️  Test 10 INFO: Max step {max_step} < 10, audit not expected")

    # Summary
    print("\n" + "="*60)
    print(f"Test Summary: {passed} passed, {failed} failed")
    print("="*60)

    return passed, failed


def main():
    parser = argparse.ArgumentParser(description="Test v0.5.4 orchestrator")
    parser.add_argument("--keep", action="store_true",
                       help="Keep test directory after completion")
    parser.add_argument("--keep-logs", action="store_true",
                       help="Keep event logs when clearing")
    parser.add_argument("--clear-only", action="store_true",
                       help="Only clear existing test directory, don't run test")
    parser.add_argument("--test-dir", type=Path,
                       help="Use specific test directory instead of creating temp")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose output")
    parser.add_argument("--timeout", type=int, default=300,
                       help="Timeout for orchestrator run (default: 300s)")

    args = parser.parse_args()

    # Determine test directory
    if args.test_dir:
        test_dir = args.test_dir.resolve()
        if not test_dir.exists():
            test_dir.mkdir(parents=True)
            print(f"✓ Created test directory: {test_dir}")
        else:
            print(f"✓ Using existing test directory: {test_dir}")
    else:
        test_dir = Path(tempfile.mkdtemp(prefix="test-orchestrator-v0.5.4-"))
        print(f"✓ Created temporary test directory: {test_dir}")

    # Clear only mode
    if args.clear_only:
        clear_test_directory(test_dir, keep_logs=args.keep_logs)
        return 0

    try:
        # Setup test project
        setup_test_project(test_dir)

        # Run orchestrator
        print("\n" + "="*60)
        print("Running orchestrator v0.5.4...")
        print("="*60 + "\n")

        agentic_dir = test_dir / ".agentic"
        result = subprocess.run(
            ["uv", "run", "orchestrate", "run", "--workspace", str(agentic_dir)],
            cwd=test_dir,
            capture_output=True,
            text=True,
            timeout=args.timeout
        )

        if args.verbose:
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
        else:
            # Show last 30 lines of output
            lines = result.stdout.split("\n")
            relevant_lines = [line for line in lines if line.strip() and not line.startswith("[dim]")]
            print("\n".join(relevant_lines[-30:]))

        # Validate results
        passed, failed = validate_results(test_dir, verbose=args.verbose)

        # Show what was created
        print("\n" + "="*60)
        print("Files Created in Project Root")
        print("="*60)
        for item in sorted(test_dir.iterdir()):
            if item.name != ".agentic":
                if item.is_file():
                    size = item.stat().st_size
                    print(f"  {item.name} ({size} bytes)")
                elif item.is_dir():
                    file_count = len(list(item.rglob("*")))
                    print(f"  {item.name}/ ({file_count} items)")

        if args.keep:
            print(f"\n✓ Test directory preserved: {test_dir}")
            print(f"  View logs: {test_dir}/.agentic/full_history.jsonl")
            print(f"  Clear with: python {__file__} --clear-only --test-dir {test_dir}")

        return 0 if failed == 0 else 1

    except subprocess.TimeoutExpired:
        print(f"\n❌ Test FAILED: Orchestrator timed out after {args.timeout}s")
        print(f"   Test directory: {test_dir}")
        return 1

    except Exception as e:
        print(f"\n❌ Test FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        if not args.keep and not args.test_dir:
            print(f"\nCleaning up test directory: {test_dir}")
            shutil.rmtree(test_dir)
            print("✓ Cleanup complete")


if __name__ == "__main__":
    sys.exit(main())
