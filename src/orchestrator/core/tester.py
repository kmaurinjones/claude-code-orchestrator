"""Lightweight testing harness for orchestrator workflow."""

from __future__ import annotations

import subprocess
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from ..models import VerificationCheck, Task


@dataclass
class TestResult:
    """Structured output for a single acceptance check."""

    check: VerificationCheck
    passed: bool
    message: str
    stdout: Optional[str] = None
    stderr: Optional[str] = None


class Tester:
    """Execute acceptance criteria and record results for reviewer feedback."""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()

    def run(self, task: Task) -> List[TestResult]:
        """Run all acceptance criteria for a task."""
        results: List[TestResult] = []

        for check in task.acceptance_criteria:
            if check.type == "command_passes":
                results.append(self._run_command(check))
            elif check.type == "file_exists":
                results.append(self._check_file_exists(check))
            elif check.type == "pattern_in_file":
                results.append(self._check_pattern_in_file(check))

        return results

    def _run_command(self, check: VerificationCheck) -> TestResult:
        """Execute a shell command and capture its output."""
        try:
            proc = subprocess.run(
                check.target,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self.workspace),
            )
            passed = proc.returncode == 0
            message = (
                f"Command succeeded: {check.target}"
                if passed
                else f"Command failed (exit {proc.returncode})"
            )
            return TestResult(
                check=check,
                passed=passed,
                message=message,
                stdout=(proc.stdout or "").strip() or None,
                stderr=(proc.stderr or "").strip() or None,
            )
        except subprocess.TimeoutExpired as exc:
            return TestResult(
                check=check,
                passed=False,
                message=f"Command timed out after {exc.timeout}s: {check.target}",
                stdout=(exc.stdout or b"").decode(errors="ignore") or None,
                stderr=(exc.stderr or b"").decode(errors="ignore") or None,
            )
        except Exception as exc:  # pylint: disable=broad-except
            return TestResult(
                check=check,
                passed=False,
                message=f"Command error: {exc}",
            )

    def _check_file_exists(self, check: VerificationCheck) -> TestResult:
        """Verify that a file exists on disk."""
        file_path = self.workspace / check.target
        if file_path.exists():
            return TestResult(
                check=check,
                passed=True,
                message=f"File exists: {check.target}",
            )

        return TestResult(
            check=check,
            passed=False,
            message=f"File not found: {check.target}",
        )

    def _check_pattern_in_file(self, check: VerificationCheck) -> TestResult:
        """Search for a regex pattern within a file."""
        file_path = self.workspace / check.target
        if not file_path.exists():
            return TestResult(
                check=check,
                passed=False,
                message=f"File not found: {check.target}",
            )

        try:
            content = file_path.read_text()
            pattern = check.expected or check.description
            if pattern and re.search(pattern, content):
                return TestResult(
                    check=check,
                    passed=True,
                    message=f"Pattern found in {check.target}",
                )

            return TestResult(
                check=check,
                passed=False,
                message=f"Pattern not found in {check.target}: {pattern!r}",
            )
        except Exception as exc:  # pylint: disable=broad-except
            return TestResult(
                check=check,
                passed=False,
                message=f"Error reading file {check.target}: {exc}",
            )
