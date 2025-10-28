#!/usr/bin/env python3
"""Test nested path creation - verifies v0.5.5 fix."""

import subprocess
import shutil
from pathlib import Path
import tempfile

def main():
    test_dir = Path(tempfile.mkdtemp(prefix="test-nested-paths-"))
    print(f"Test directory: {test_dir}")

    try:
        # Setup
        agentic_dir = test_dir / ".agentic"
        current_dir = agentic_dir / "current"
        current_dir.mkdir(parents=True)

        # GOALS with nested path requirement
        goals = """# GOALS.md
Generated: 2025-10-27

## Core Success Criteria (IMMUTABLE)
1. **Create module in nested directory structure**
   - Measurable: File `src/myproject/core/module.py` exists with working function
   - Non-negotiable: Must respect full nested path

## Constraints (IMMUTABLE)
- Files must be in nested directories as specified
"""
        (current_dir / "GOALS.md").write_text(goals)

        # TASKS with nested path verification
        tasks = """# TASKS.md

## Backlog
- [📋] task-001: Create src/myproject/core/module.py with hello() function (priority: 10)
  - Verify: file_exists:src/myproject/core/module.py "Module in nested path"
  - Verify: pattern_in_file:src/myproject/core/module.py "def hello\\(\\)"
"""
        (current_dir / "TASKS.md").write_text(tasks)

        # Config
        config = """min_steps: 2
max_steps: 5
max_parallel_tasks: 1
"""
        (agentic_dir / "orchestrator.config.yaml").write_text(config)

        print("\n" + "="*60)
        print("Running nested path test...")
        print("="*60)

        # Run orchestrator
        result = subprocess.run(
            ["uv", "run", "orchestrate", "run", "--workspace", str(agentic_dir)],
            cwd=test_dir,
            capture_output=True,
            text=True,
            timeout=120
        )

        print(result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout)

        # Validate
        nested_file = test_dir / "src" / "myproject" / "core" / "module.py"

        if nested_file.exists():
            print("\n✅ SUCCESS: File created in nested path!")
            print(f"   Path: {nested_file}")
            content = nested_file.read_text()
            if "def hello(" in content:
                print("✅ SUCCESS: Function found in file!")
                return 0
            else:
                print("❌ FAILED: Function not found in file")
                return 1
        else:
            print(f"\n❌ FAILED: File not found at {nested_file}")

            # Check if created in wrong location
            wrong_locations = [
                test_dir / "module.py",
                test_dir / "core" / "module.py",
                agentic_dir / "src" / "myproject" / "core" / "module.py"
            ]
            for loc in wrong_locations:
                if loc.exists():
                    print(f"   ⚠️  File found at WRONG location: {loc}")
            return 1

    finally:
        shutil.rmtree(test_dir)
        print(f"\nCleaned up: {test_dir}")

if __name__ == "__main__":
    exit(main())
