"""Failure diagnosis system for intelligent root cause analysis and remediation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

from ..models import Task
from .tester import TestResult

console = Console()


class FailureCategory(str, Enum):
    """Classification of failure root causes."""

    WRONG_APPROACH = "wrong_approach"  # Implementation strategy flawed
    MISSING_CONTEXT = "missing_context"  # Need more info to proceed
    EXTERNAL_DEPENDENCY = "external_dependency"  # External service/API issue
    SCOPE_TOO_LARGE = "scope_too_large"  # Task needs decomposition
    ENVIRONMENT_ISSUE = "environment_issue"  # Setup/tooling problem
    TEST_FLAKY = "test_flaky"  # Non-deterministic test failure
    SYNTAX_ERROR = "syntax_error"  # Code syntax problems
    TYPE_ERROR = "type_error"  # Type checking failures
    IMPORT_ERROR = "import_error"  # Missing dependencies or imports
    UNKNOWN = "unknown"  # Could not classify


@dataclass
class FailureDiagnosis:
    """Structured diagnosis of a task failure."""

    category: FailureCategory
    confidence: float  # 0.0-1.0
    summary: str
    evidence: List[str] = field(default_factory=list)
    suggested_actions: List[str] = field(default_factory=list)
    context_enrichment: Optional[Dict[str, Any]] = None
    should_auto_enrich: bool = False  # True for simple context gaps
    needs_task_split: bool = False  # True if scope too large


class FailureDiagnoser:
    """Analyzes task failures to determine root cause and suggest remediation."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()

    def diagnose(
        self,
        task: Task,
        error_output: str,
        test_results: List[TestResult],
        attempt_count: int,
    ) -> FailureDiagnosis:
        """Analyze failure and classify root cause."""
        # Collect all error text
        error_text = self._collect_error_text(error_output, test_results, task)

        # Run classification
        category, confidence, evidence = self._classify_failure(error_text, task, attempt_count)

        # Generate diagnosis
        summary = self._generate_summary(category, evidence, task)
        actions = self._suggest_actions(category, evidence, task)
        context_enrichment, should_auto_enrich = self._determine_context_enrichment(
            category, evidence, task
        )

        return FailureDiagnosis(
            category=category,
            confidence=confidence,
            summary=summary,
            evidence=evidence,
            suggested_actions=actions,
            context_enrichment=context_enrichment,
            should_auto_enrich=should_auto_enrich,
            needs_task_split=category == FailureCategory.SCOPE_TOO_LARGE,
        )

    def _collect_error_text(
        self, error_output: str, test_results: List[TestResult], task: Task
    ) -> str:
        """Aggregate all error information into searchable text."""
        parts = [error_output]

        for result in test_results:
            if not result.passed:
                parts.append(f"Test failed: {result.check.description}")
                parts.append(f"Message: {result.message}")
                if result.stdout:
                    parts.append(f"Stdout: {result.stdout}")
                if result.stderr:
                    parts.append(f"Stderr: {result.stderr}")

        for summary in task.summary[-5:]:
            parts.append(summary)

        if task.review_feedback:
            parts.extend(task.review_feedback[-3:])

        if task.critic_feedback:
            parts.extend(task.critic_feedback[-3:])

        return "\n".join(parts).lower()

    def _classify_failure(
        self, error_text: str, task: Task, attempt_count: int
    ) -> tuple[FailureCategory, float, List[str]]:
        """Classify failure into category with confidence and evidence."""

        # Pattern-based classification with confidence scores
        patterns = {
            FailureCategory.SYNTAX_ERROR: [
                (r"syntaxerror", 0.95),
                (r"invalid syntax", 0.95),
                (r"unexpected token", 0.90),
                (r"parsing error", 0.85),
            ],
            FailureCategory.TYPE_ERROR: [
                (r"typeerror", 0.95),
                (r"type.*mismatch", 0.85),
                (r"expected.*got", 0.80),
                (r"mypy.*error", 0.90),
                (r"type checking failed", 0.90),
            ],
            FailureCategory.IMPORT_ERROR: [
                (r"importerror", 0.95),
                (r"modulenotfounderror", 0.95),
                (r"no module named", 0.95),
                (r"cannot import name", 0.90),
            ],
            FailureCategory.EXTERNAL_DEPENDENCY: [
                (r"connection.*refused", 0.90),
                (r"timeout.*connect", 0.85),
                (r"api.*error", 0.75),
                (r"network.*unreachable", 0.90),
                (r"service.*unavailable", 0.85),
                (r"rate.*limit", 0.85),
                (r"authentication.*failed", 0.80),
            ],
            FailureCategory.ENVIRONMENT_ISSUE: [
                (r"permission denied", 0.90),
                (r"not found.*command", 0.85),
                (r"command not found", 0.90),
                (r"environment variable", 0.80),
                (r"missing.*dependency", 0.85),
                (r"version.*incompatible", 0.80),
            ],
            FailureCategory.MISSING_CONTEXT: [
                (r"file not found", 0.80),
                (r"no such file", 0.80),
                (r"undefined.*reference", 0.75),
                (r"not defined", 0.70),
                (r"unknown.*identifier", 0.75),
                (r"missing.*required", 0.75),
            ],
            FailureCategory.TEST_FLAKY: [
                (r"flaky", 0.90),
                (r"intermittent", 0.85),
                (r"race condition", 0.80),
                (r"timing.*issue", 0.75),
            ],
            FailureCategory.SCOPE_TOO_LARGE: [
                (r"max.?turns", 0.95),
                (r"exceeded.*limit", 0.80),
                (r"too complex", 0.85),
                (r"timeout.*expired", 0.70),
            ],
        }

        best_category = FailureCategory.UNKNOWN
        best_confidence = 0.0
        evidence: List[str] = []

        for category, category_patterns in patterns.items():
            for pattern, base_confidence in category_patterns:
                matches = re.findall(pattern, error_text, re.IGNORECASE)
                if matches:
                    # Adjust confidence based on match count
                    adjusted_confidence = min(1.0, base_confidence + 0.05 * (len(matches) - 1))
                    if adjusted_confidence > best_confidence:
                        best_confidence = adjusted_confidence
                        best_category = category
                        evidence = [f"Pattern '{pattern}' matched {len(matches)} time(s)"]

        # Check for repeated failures suggesting wrong approach
        if attempt_count >= 3 and best_category == FailureCategory.UNKNOWN:
            best_category = FailureCategory.WRONG_APPROACH
            best_confidence = 0.70
            evidence = [f"Task failed {attempt_count} times with similar issues"]

        # Check for scope issues based on task description length
        if len(task.description) > 1000 and best_confidence < 0.5:
            best_category = FailureCategory.SCOPE_TOO_LARGE
            best_confidence = 0.60
            evidence = ["Task description very long, may need decomposition"]

        return best_category, best_confidence, evidence

    def _generate_summary(
        self, category: FailureCategory, evidence: List[str], task: Task
    ) -> str:
        """Generate human-readable summary of diagnosis."""
        summaries = {
            FailureCategory.WRONG_APPROACH: (
                "The current implementation approach is not working. "
                "Consider trying a different strategy or pattern."
            ),
            FailureCategory.MISSING_CONTEXT: (
                "Missing required context or information. "
                "Need to gather more details before proceeding."
            ),
            FailureCategory.EXTERNAL_DEPENDENCY: (
                "External service or API dependency issue. "
                "This may be transient or require configuration changes."
            ),
            FailureCategory.SCOPE_TOO_LARGE: (
                "Task scope is too large for single execution. "
                "Break down into smaller, focused subtasks."
            ),
            FailureCategory.ENVIRONMENT_ISSUE: (
                "Environment or tooling problem detected. "
                "May need setup or configuration changes."
            ),
            FailureCategory.TEST_FLAKY: (
                "Test failure appears non-deterministic. "
                "Consider adding retry logic or fixing timing issues."
            ),
            FailureCategory.SYNTAX_ERROR: (
                "Code syntax error detected. "
                "Fix the syntax issues before proceeding."
            ),
            FailureCategory.TYPE_ERROR: (
                "Type mismatch or type checking failure. "
                "Review and fix type annotations and usage."
            ),
            FailureCategory.IMPORT_ERROR: (
                "Import or module resolution error. "
                "Check dependencies and import paths."
            ),
            FailureCategory.UNKNOWN: (
                "Could not determine specific failure cause. "
                "Review error output and try alternative approaches."
            ),
        }

        base_summary = summaries.get(category, summaries[FailureCategory.UNKNOWN])
        if evidence:
            base_summary += f" Evidence: {'; '.join(evidence[:2])}"

        return base_summary

    def _suggest_actions(
        self, category: FailureCategory, evidence: List[str], task: Task
    ) -> List[str]:
        """Suggest remediation actions based on diagnosis."""
        actions = {
            FailureCategory.WRONG_APPROACH: [
                "Review existing implementation and identify flaws",
                "Research alternative patterns or libraries",
                "Simplify the approach before adding complexity",
            ],
            FailureCategory.MISSING_CONTEXT: [
                "Identify what specific information is needed",
                "Search codebase for relevant context",
                "Read related files or documentation",
            ],
            FailureCategory.EXTERNAL_DEPENDENCY: [
                "Verify external service is accessible",
                "Check authentication credentials",
                "Add retry logic with exponential backoff",
                "Consider mock/stub for testing",
            ],
            FailureCategory.SCOPE_TOO_LARGE: [
                "Break task into 3-5 smaller subtasks",
                "Separate research from implementation",
                "Create incremental milestones",
            ],
            FailureCategory.ENVIRONMENT_ISSUE: [
                "Verify required tools are installed",
                "Check environment variables",
                "Review permissions and access",
            ],
            FailureCategory.TEST_FLAKY: [
                "Add explicit waits or synchronization",
                "Isolate test from shared state",
                "Consider marking as flaky with retry",
            ],
            FailureCategory.SYNTAX_ERROR: [
                "Run linter to identify syntax issues",
                "Check for unclosed brackets or quotes",
                "Verify indentation is consistent",
            ],
            FailureCategory.TYPE_ERROR: [
                "Review function signatures and return types",
                "Check for None/null handling",
                "Run type checker with verbose output",
            ],
            FailureCategory.IMPORT_ERROR: [
                "Verify dependency is installed",
                "Check import path spelling",
                "Review __init__.py files for exports",
            ],
            FailureCategory.UNKNOWN: [
                "Review full error output carefully",
                "Search for similar issues online",
                "Try a minimal reproduction",
            ],
        }

        return actions.get(category, actions[FailureCategory.UNKNOWN])

    def _determine_context_enrichment(
        self, category: FailureCategory, evidence: List[str], task: Task
    ) -> tuple[Optional[Dict[str, Any]], bool]:
        """Determine if/how to automatically enrich context before retry."""

        # Simple context gaps that can be auto-enriched
        auto_enrichable = {
            FailureCategory.MISSING_CONTEXT,
            FailureCategory.IMPORT_ERROR,
        }

        if category not in auto_enrichable:
            return None, False

        enrichment: Dict[str, Any] = {"type": category.value}

        if category == FailureCategory.MISSING_CONTEXT:
            # Suggest searching for related files
            enrichment["actions"] = [
                "search_codebase_for_references",
                "read_related_files",
            ]
            enrichment["search_terms"] = self._extract_search_terms(task)
            return enrichment, True

        if category == FailureCategory.IMPORT_ERROR:
            # Suggest checking dependencies
            enrichment["actions"] = [
                "check_pyproject_toml",
                "verify_package_installed",
            ]
            return enrichment, True

        return None, False

    def _extract_search_terms(self, task: Task) -> List[str]:
        """Extract likely search terms from task for context enrichment."""
        terms = []

        # Extract quoted strings from description
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', task.description)
        for match in quoted:
            term = match[0] or match[1]
            if len(term) > 2:
                terms.append(term)

        # Extract CamelCase or snake_case identifiers
        identifiers = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+|[a-z]+_[a-z_]+)\b', task.description)
        terms.extend(identifiers[:5])

        return terms[:10]
