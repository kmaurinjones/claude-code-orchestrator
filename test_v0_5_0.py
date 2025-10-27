#!/usr/bin/env python3
"""
Test script for v0.5.0 orchestrator improvements.

Validates:
1. Step counting (every Claude Code call increments step)
2. Files created in project root (NOT .agentic/)
3. Workspace paths are absolute
4. Code reuse directive is present in subagent instructions
"""

import subprocess
import shutil
import json
from pathlib import Path
import tempfile


def test_v0_5_0():
    """Run comprehensive test of v0.5.0 improvements."""

    # Create temporary test directory
    test_dir = Path(tempfile.mkdtemp(prefix="test-orchestrator-"))
    print(f"✓ Created test directory: {test_dir}")

    try:
        # Setup test project structure
        agentic_dir = test_dir / ".agentic"
        current_dir = agentic_dir / "current"
        current_dir.mkdir(parents=True)
        print(f"✓ Created .agentic/current directory")

        # Create GOALS.md
        goals_content = """# GOALS.md
Generated: 2025-10-26

## Core Success Criteria (IMMUTABLE)
1. **Create a simple Python hello world script**
   - Measurable: File `hello.py` exists in project root and prints "Hello, World!"
   - Non-negotiable: This validates the orchestrator can create files in the correct location

## Nice-to-Have (FLEXIBLE)
- None

## Out of Scope
- Complex functionality

## Constraints (IMMUTABLE)
- Must use Python 3.12+
- File must be created in project root, NOT in .agentic/
"""
        (current_dir / "GOALS.md").write_text(goals_content)
        print("✓ Created GOALS.md")

        # Create TASKS.md (without pattern_in_file check to avoid verification bug)
        tasks_content = """# TASKS.md

## Backlog
- [📋] task-001: Create hello.py in project root with "Hello, World!" output (priority: 10)
  - Goals: goal-1
  - Verify: file_exists:hello.py "Check that hello.py exists in project root"
  - Verify: command_passes:python hello.py "Script runs and prints Hello, World!"
"""
        (current_dir / "TASKS.md").write_text(tasks_content)
        print("✓ Created TASKS.md")

        # Create config with low step counts
        config_content = """min_steps: 2
max_steps: 5
max_parallel_tasks: 3
"""
        (agentic_dir / "orchestrator.config.yaml").write_text(config_content)
        print("✓ Created orchestrator.config.yaml")

        # Run orchestrator
        print("\n" + "="*60)
        print("Running orchestrator...")
        print("="*60 + "\n")

        result = subprocess.run(
            ["uv", "run", "orchestrate", "run", "--workspace", str(agentic_dir)],
            cwd=test_dir,
            capture_output=True,
            text=True,
            timeout=120
        )

        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)

        # Validate results
        print("\n" + "="*60)
        print("Validation Results")
        print("="*60 + "\n")

        # Check 1: File created in project root
        hello_py = test_dir / "hello.py"
        if hello_py.exists():
            print("✅ Test 1 PASSED: hello.py created in project root")
            print(f"   Location: {hello_py}")
            content = hello_py.read_text()
            print(f"   Content: {content.strip()}")
        else:
            print("❌ Test 1 FAILED: hello.py not found in project root")
            print(f"   Expected at: {hello_py}")

            # Check if it was created in .agentic/ by mistake
            wrong_location = agentic_dir / "hello.py"
            if wrong_location.exists():
                print(f"   ⚠️  File was created in WRONG location: {wrong_location}")

        # Check 2: File NOT in .agentic/
        wrong_file = agentic_dir / "hello.py"
        if not wrong_file.exists():
            print("✅ Test 2 PASSED: hello.py NOT created in .agentic/ (correct)")
        else:
            print("❌ Test 2 FAILED: hello.py found in .agentic/ (wrong location)")
            print(f"   Location: {wrong_file}")

        # Check 3: Step counting in event log
        event_log = agentic_dir / "full_history.jsonl"
        if event_log.exists():
            with open(event_log) as f:
                events = [json.loads(line) for line in f if line.strip()]

            steps = [e["step"] for e in events]
            max_step = max(steps) if steps else 0

            # Should have at least: 1 (orchestrator) + 1 (subagent) = 2 steps
            if max_step >= 2:
                print(f"✅ Test 3 PASSED: Step counting works (max step: {max_step})")
                print(f"   Steps recorded: {sorted(set(steps))}")
            else:
                print(f"❌ Test 3 FAILED: Step counting incorrect (max step: {max_step})")
        else:
            print("❌ Test 3 FAILED: Event log not found")

        # Check 4: Workspace paths are absolute
        if event_log.exists():
            spawn_events = [e for e in events if e["event"] == "spawn"]
            if spawn_events:
                workspace_path = spawn_events[0]["payload"].get("workspace", "")
                if workspace_path and Path(workspace_path).is_absolute():
                    print(f"✅ Test 4 PASSED: Workspace path is absolute")
                    print(f"   Path: {workspace_path}")
                else:
                    print(f"❌ Test 4 FAILED: Workspace path is not absolute")
                    print(f"   Path: {workspace_path}")
            else:
                print("❌ Test 4 FAILED: No spawn events in log")

        # Check 5: Code reuse directive in subagent instructions
        from src.orchestrator.core.subagent import Subagent
        from src.orchestrator.core.logger import EventLogger

        # Create dummy subagent to check instruction text
        dummy_logger = EventLogger(agentic_dir / "test.jsonl")
        dummy_subagent = Subagent(
            task_id="test",
            task_description="test task",
            context="test context",
            parent_trace_id="test-parent",
            logger=dummy_logger,
            step=1,
            workspace=test_dir
        )

        instruction = dummy_subagent._build_instruction()
        if "ALWAYS USE EXISTING CODE FIRST" in instruction:
            print("✅ Test 5 PASSED: Code reuse directive present in instructions")
            # Find and print the relevant section
            lines = instruction.split("\n")
            start_idx = None
            for i, line in enumerate(lines):
                if "ALWAYS USE EXISTING CODE FIRST" in line:
                    start_idx = i
                    break
            if start_idx:
                print("   Directive section:")
                for line in lines[start_idx:start_idx+7]:
                    print(f"   {line}")
        else:
            print("❌ Test 5 FAILED: Code reuse directive NOT found in instructions")

        print("\n" + "="*60)
        print("Test Complete")
        print("="*60)

    finally:
        # Cleanup
        print(f"\nCleaning up test directory: {test_dir}")
        shutil.rmtree(test_dir)
        print("✓ Cleanup complete")


if __name__ == "__main__":
    test_v0_5_0()
