"""Lightweight testing harness for orchestrator workflow."""

from __future__ import annotations

import subprocess
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
            elif check.type == "pattern_count":
                results.append(self._check_pattern_count(check))
            elif check.type == "file_word_count":
                results.append(self._check_file_word_count(check))
            elif check.type == "section_word_count":
                results.append(self._check_section_word_count(check))
            elif check.type == "no_placeholder_text":
                results.append(self._check_no_placeholder(check))
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
            if not pattern:
                return TestResult(
                    check=check,
                    passed=False,
                    message=f"No pattern defined for {check.description}",
                )

            matches = self._find_pattern_matches(pattern, content, check.metadata)
            min_matches = check.metadata.get("min_matches", 1) if check.metadata else 1
            if matches >= min_matches:
                return TestResult(
                    check=check,
                    passed=True,
                    message=f"Pattern found ({matches} match{'es' if matches != 1 else ''}) in {check.target}",
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

    def _check_pattern_count(self, check: VerificationCheck) -> TestResult:
        """Ensure a pattern appears a specified number of times."""
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
            if not pattern:
                return TestResult(
                    check=check,
                    passed=False,
                    message=f"No pattern defined for {check.description}",
                )

            matches = self._find_pattern_matches(pattern, content, check.metadata)
            metadata = check.metadata or {}
            min_count = metadata.get("min_count", 1)
            max_count = metadata.get("max_count")

            if matches < min_count:
                return TestResult(
                    check=check,
                    passed=False,
                    message=f"Pattern found {matches} time(s); expected at least {min_count}.",
                )
            if max_count is not None and matches > max_count:
                return TestResult(
                    check=check,
                    passed=False,
                    message=f"Pattern found {matches} time(s); expected no more than {max_count}.",
                )

            return TestResult(
                check=check,
                passed=True,
                message=f"Pattern count within bounds ({matches}).",
            )
        except Exception as exc:
            return TestResult(
                check=check,
                passed=False,
                message=f"Error reading file {check.target}: {exc}",
            )

    def _check_file_word_count(self, check: VerificationCheck) -> TestResult:
        """Verify entire file word count."""
        file_path = self.workspace / check.target
        if not file_path.exists():
            return TestResult(
                check=check,
                passed=False,
                message=f"File not found: {check.target}",
            )

        metadata = check.metadata or {}
        min_words = metadata.get("min_words")
        max_words = metadata.get("max_words")

        if min_words is None and max_words is None:
            return TestResult(
                check=check,
                passed=False,
                message="file_word_count requires min_words and/or max_words metadata.",
            )

        try:
            content = file_path.read_text()
            count = self._count_words(content)
        except Exception as exc:
            return TestResult(check=check, passed=False, message=f"Error reading file {check.target}: {exc}")

        if min_words is not None and count < int(min_words):
            return TestResult(
                check=check,
                passed=False,
                message=f"Word count {count} < minimum {min_words}",
            )
        if max_words is not None and count > int(max_words):
            return TestResult(
                check=check,
                passed=False,
                message=f"Word count {count} > maximum {max_words}",
            )

        return TestResult(
            check=check,
            passed=True,
            message=f"Word count {count} within expected range.",
        )

    def _check_section_word_count(self, check: VerificationCheck) -> TestResult:
        """Verify the word count of a specific markdown section."""
        file_path = self.workspace / check.target
        if not file_path.exists():
            return TestResult(
                check=check,
                passed=False,
                message=f"File not found: {check.target}",
            )

        metadata = check.metadata or {}
        heading = metadata.get("section_heading")
        if not heading:
            return TestResult(
                check=check,
                passed=False,
                message="section_word_count requires 'section_heading' metadata.",
            )

        min_words = metadata.get("min_words")
        max_words = metadata.get("max_words")
        if min_words is None and max_words is None:
            return TestResult(
                check=check,
                passed=False,
                message="section_word_count requires min_words and/or max_words metadata.",
            )

        try:
            content = file_path.read_text()
        except Exception as exc:
            return TestResult(check=check, passed=False, message=f"Error reading file {check.target}: {exc}")

        section_text = self._extract_section(content, heading, metadata.get("next_heading_pattern"))
        if section_text is None:
            return TestResult(
                check=check,
                passed=False,
                message=f"Section heading '{heading}' not found in {check.target}",
            )

        count = self._count_words(section_text)
        if min_words is not None and count < int(min_words):
            return TestResult(
                check=check,
                passed=False,
                message=f"Section '{heading}' word count {count} < minimum {min_words}",
            )
        if max_words is not None and count > int(max_words):
            return TestResult(
                check=check,
                passed=False,
                message=f"Section '{heading}' word count {count} > maximum {max_words}",
            )

        return TestResult(
            check=check,
            passed=True,
            message=f"Section '{heading}' word count {count} within range.",
        )

    def _check_no_placeholder(self, check: VerificationCheck) -> TestResult:
        """Ensure placeholder text has been removed."""
        file_path = self.workspace / check.target
        if not file_path.exists():
            return TestResult(
                check=check,
                passed=False,
                message=f"File not found: {check.target}",
            )

        metadata = check.metadata or {}
        phrases = metadata.get("phrases")
        if not phrases:
            return TestResult(
                check=check,
                passed=False,
                message="no_placeholder_text requires 'phrases' metadata.",
            )

        case_insensitive = metadata.get("case_insensitive", True)

        try:
            content = file_path.read_text()
        except Exception as exc:
            return TestResult(check=check, passed=False, message=f"Error reading file {check.target}: {exc}")

        offending = []
        for phrase in phrases:
            if case_insensitive:
                if phrase.lower() in content.lower():
                    offending.append(phrase)
            else:
                if phrase in content:
                    offending.append(phrase)

        if offending:
            return TestResult(
                check=check,
                passed=False,
                message=f"Placeholder text present: {', '.join(offending)}",
            )

        return TestResult(
            check=check,
            passed=True,
            message="No placeholder text detected.",
        )

    def _find_pattern_matches(self, pattern: str, content: str, metadata: Optional[Dict[str, Any]]) -> int:
        """Return number of regex matches honoring optional flags."""
        flags = re.MULTILINE
        if metadata and metadata.get("case_insensitive"):
            flags |= re.IGNORECASE
        regex = re.compile(pattern, flags)
        return len(list(regex.finditer(content)))

    @staticmethod
    def _count_words(text: str) -> int:
        return len(text.split())

    @staticmethod
    def _extract_section(content: str, heading: str, next_heading_pattern: Optional[str]) -> Optional[str]:
        """Return markdown section text following heading until the next peer heading."""
        pattern = re.compile(rf"^{re.escape(heading)}\s*$", re.MULTILINE)
        match = pattern.search(content)
        if not match:
            return None

        start = match.end()
        remainder = content[start:]
        next_pattern = re.compile(next_heading_pattern, re.MULTILINE) if next_heading_pattern else re.compile(r"^##\s", re.MULTILINE)
        next_match = next_pattern.search(remainder)
        if next_match:
            return remainder[: next_match.start()].strip()
        return remainder.strip()

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
