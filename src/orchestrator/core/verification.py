"""Task verification system for proving completion."""

import subprocess
import re
from pathlib import Path
from typing import List, Tuple
from rich.console import Console

from ..models import VerificationCheck, Task

console = Console()


class Verifier:
    def __init__(self, workspace: Path):
        self.workspace = workspace

    def verify_task(self, task: Task) -> Tuple[bool, List[str]]:
        """
        Verify task completion by running all acceptance criteria checks.

        Returns:
            (all_passed, failure_messages)
        """
        if not task.acceptance_criteria:
            # No verification required - trust subagent
            return (True, [])

        failures = []

        for check in task.acceptance_criteria:
            passed, message = self._run_check(check)

            if passed:
                console.print(f"[green]  ✓[/green] {check.description}")
            else:
                console.print(f"[red]  ✗[/red] {check.description}")
                console.print(f"[dim]    {message}[/dim]")
                failures.append(f"{check.description}: {message}")

        return (len(failures) == 0, failures)

    def _run_check(self, check: VerificationCheck) -> Tuple[bool, str]:
        """Run a single verification check."""

        if check.type == "file_exists":
            return self._check_file_exists(check)

        elif check.type == "command_passes":
            return self._check_command_passes(check)

        elif check.type == "pattern_in_file":
            return self._check_pattern_in_file(check)

        else:
            return (False, f"Unknown verification type: {check.type}")

    def _check_file_exists(self, check: VerificationCheck) -> Tuple[bool, str]:
        """Verify that a file exists."""
        file_path = self.workspace / check.target

        if file_path.exists():
            return (True, f"File exists: {check.target}")
        else:
            return (False, f"File not found: {check.target}")

    def _check_command_passes(self, check: VerificationCheck) -> Tuple[bool, str]:
        """Verify that a command exits with code 0."""
        try:
            result = subprocess.run(
                check.target,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.workspace)
            )

            if result.returncode == 0:
                return (True, f"Command passed: {check.target}")
            else:
                stderr = result.stderr[:200] if result.stderr else result.stdout[:200]
                return (False, f"Command failed (exit {result.returncode}): {stderr}")

        except subprocess.TimeoutExpired:
            return (False, f"Command timed out: {check.target}")

        except Exception as e:
            return (False, f"Command error: {str(e)}")

    def _check_pattern_in_file(self, check: VerificationCheck) -> Tuple[bool, str]:
        """Verify that a file contains a specific pattern."""
        file_path = self.workspace / check.target

        if not file_path.exists():
            return (False, f"File not found: {check.target}")

        try:
            content = file_path.read_text()

            if check.expected:
                if re.search(check.expected, content):
                    return (True, f"Pattern found in {check.target}")
                else:
                    return (False, f"Pattern not found: {check.expected}")
            else:
                return (False, "No pattern specified for pattern_in_file check")

        except Exception as e:
            return (False, f"Error reading file: {str(e)}")
