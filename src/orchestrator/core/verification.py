"""Task verification system for proving completion."""

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple
from rich.console import Console

from ..models import VerificationCheck, Task

console = Console()


class Verifier:
    def __init__(
        self,
        workspace: Path,
        *,
        skip_integration_tests: bool = True,
        pytest_addopts: Optional[str] = None
    ):
        # Ensure workspace is absolute
        if isinstance(workspace, Path):
            self.workspace = workspace.resolve()
        else:
            self.workspace = Path(workspace).resolve()

        # Validate workspace is absolute (defensive check)
        if not self.workspace.is_absolute():
            raise ValueError(f"Verifier workspace must be absolute: {self.workspace}")

        self.skip_integration_tests = skip_integration_tests
        self.pytest_addopts = pytest_addopts.strip() if pytest_addopts else None

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
        env = os.environ.copy()
        command = check.target

        # Allow env override to force integration tests to run
        run_integration_override = env.get("ORCHESTRATOR_RUN_INTEGRATION_TESTS")
        skip_integration = self.skip_integration_tests
        if run_integration_override:
            skip_integration = run_integration_override.strip().lower() not in {"1", "true", "yes", "on"}

        if "pytest" in command:
            try:
                tokens = shlex.split(command)
            except ValueError:
                tokens = []

            is_pytest_command = any(
                token == "pytest"
                or token.endswith("pytest")
                or token.endswith("pytest.exe")
                for token in tokens
            )

            if not tokens:
                is_pytest_command = True  # Fallback for complex shell commands

            if is_pytest_command:
                marker_flag_present = any(
                    token == "-m" or token.startswith("-m")
                    for token in tokens
                )

                extras: List[str] = []

                if self.pytest_addopts:
                    extras.append(self.pytest_addopts)

                if skip_integration and not marker_flag_present:
                    extras.append('-m "not integration"')

                if extras:
                    existing = env.get("PYTEST_ADDOPTS", "").strip()
                    combined_parts = [existing] if existing else []
                    combined_parts.extend(extras)
                    env["PYTEST_ADDOPTS"] = " ".join(combined_parts).strip()

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.workspace),
                env=env
            )

            if result.returncode == 0:
                return (True, f"Command passed: {command}")
            else:
                stderr = result.stderr[:200] if result.stderr else result.stdout[:200]
                return (False, f"Command failed (exit {result.returncode}): {stderr}")

        except subprocess.TimeoutExpired:
            return (False, f"Command timed out: {command}")

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
