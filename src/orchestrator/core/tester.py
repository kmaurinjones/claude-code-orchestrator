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
            # Original check types
            if check.type == "command_passes":
                results.append(self._run_command(check))
            elif check.type == "file_exists":
                results.append(self._check_file_exists(check))
            elif check.type == "pattern_in_file":
                results.append(self._check_pattern_in_file(check))
            # Rich validator check types
            elif check.type == "http_endpoint":
                results.append(self._check_http_endpoint(check))
            elif check.type == "metric_threshold":
                results.append(self._check_metric_threshold(check))
            elif check.type == "schema_valid":
                results.append(self._check_schema(check))
            elif check.type == "security_scan":
                results.append(self._check_security_scan(check))
            elif check.type == "type_check":
                results.append(self._check_type_check(check))
            elif check.type == "data_quality":
                results.append(self._check_data_quality(check))
            else:
                # Unknown check type
                results.append(TestResult(
                    check=check,
                    passed=False,
                    message=f"Unknown check type: {check.type}",
                ))

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

    def _check_http_endpoint(self, check: VerificationCheck) -> TestResult:
        """Check HTTP endpoint using validator."""
        from .validators import HTTPEndpointValidator

        timeout = check.timeout or 30
        result = HTTPEndpointValidator.validate(check.target, check.expected, timeout)

        return TestResult(
            check=check,
            passed=result.passed,
            message=result.message,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _check_metric_threshold(self, check: VerificationCheck) -> TestResult:
        """Check metric threshold using validator."""
        from .validators import MetricThresholdValidator

        result = MetricThresholdValidator.validate(
            check.target,
            check.expected or "",
            self.workspace,
        )

        return TestResult(
            check=check,
            passed=result.passed,
            message=result.message,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _check_schema(self, check: VerificationCheck) -> TestResult:
        """Validate schema using validator."""
        from .validators import SchemaValidator

        result = SchemaValidator.validate(
            check.target,
            check.expected or "",
            self.workspace,
        )

        return TestResult(
            check=check,
            passed=result.passed,
            message=result.message,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _check_security_scan(self, check: VerificationCheck) -> TestResult:
        """Run security scan using validator."""
        from .validators import SecurityScanValidator

        timeout = check.timeout or 300
        result = SecurityScanValidator.validate(
            check.target,
            check.expected,
            self.workspace,
            timeout,
        )

        return TestResult(
            check=check,
            passed=result.passed,
            message=result.message,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _check_type_check(self, check: VerificationCheck) -> TestResult:
        """Run type checker using validator."""
        from .validators import TypeCheckValidator

        timeout = check.timeout or 300
        result = TypeCheckValidator.validate(
            check.target,
            check.expected,
            self.workspace,
            timeout,
        )

        return TestResult(
            check=check,
            passed=result.passed,
            message=result.message,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _check_data_quality(self, check: VerificationCheck) -> TestResult:
        """Check data quality using validator."""
        from .validators import DataQualityValidator

        result = DataQualityValidator.validate(
            check.target,
            check.expected or "",
            self.workspace,
        )

        return TestResult(
            check=check,
            passed=result.passed,
            message=result.message,
            stdout=result.stdout,
            stderr=result.stderr,
        )
