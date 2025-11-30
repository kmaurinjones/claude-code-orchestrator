"""Goal evaluator system for data-driven completion detection.

Maps high-level goals to concrete verification mechanisms across domains:
- Software engineering: CI results, API contracts, test coverage
- Data science: Metric thresholds, data quality checks, bias detection
- Tooling: Performance benchmarks, security scans
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from ..models import Goal


@dataclass
class EvaluationResult:
    """Result of evaluating a goal."""

    goal_id: str
    achieved: bool
    confidence: float  # 0.0 to 1.0
    evidence: List[str]  # Supporting evidence for the determination
    blockers: List[str]  # What's preventing achievement if not achieved
    recommendations: List[str]  # Next steps if not achieved


class GoalEvaluator(ABC):
    """Base class for goal evaluation adapters."""

    @abstractmethod
    def can_evaluate(self, goal: Goal) -> bool:
        """Check if this evaluator can handle this goal type."""
        pass

    @abstractmethod
    def evaluate(self, goal: Goal, project_root: Path) -> EvaluationResult:
        """Evaluate whether the goal is achieved."""
        pass


class TestSuiteEvaluator(GoalEvaluator):
    """Evaluates goals based on test suite results."""

    def can_evaluate(self, goal: Goal) -> bool:
        """Check if goal mentions tests, CI, or validation."""
        keywords = ["test", "ci", "validation", "coverage", "pass"]
        text = (goal.description + " " + goal.measurable_criteria).lower()
        return any(kw in text for kw in keywords)

    def evaluate(self, goal: Goal, project_root: Path) -> EvaluationResult:
        """Run tests and check results."""

        evidence = []
        blockers = []

        # Try pytest
        pytest_result = self._run_pytest(project_root)
        if pytest_result["ran"]:
            evidence.append(
                f"Pytest: {pytest_result['passed']}/{pytest_result['total']} passed"
            )
            if pytest_result["passed"] == pytest_result["total"]:
                return EvaluationResult(
                    goal_id=goal.id,
                    achieved=True,
                    confidence=0.95,
                    evidence=evidence,
                    blockers=[],
                    recommendations=[],
                )
            else:
                blockers.append(f"{pytest_result['failed']} tests failing")

        # Try npm test if package.json exists
        if (project_root / "package.json").exists():
            npm_result = self._run_npm_test(project_root)
            if npm_result["ran"]:
                evidence.append(f"npm test: {npm_result['status']}")
                if npm_result["status"] == "passed":
                    return EvaluationResult(
                        goal_id=goal.id,
                        achieved=True,
                        confidence=0.95,
                        evidence=evidence,
                        blockers=[],
                        recommendations=[],
                    )
                else:
                    blockers.append("npm test failures")

        if blockers:
            return EvaluationResult(
                goal_id=goal.id,
                achieved=False,
                confidence=0.8,
                evidence=evidence,
                blockers=blockers,
                recommendations=["Fix failing tests", "Review test output logs"],
            )

        # No tests found
        return EvaluationResult(
            goal_id=goal.id,
            achieved=False,
            confidence=0.3,
            evidence=["No automated tests found"],
            blockers=["Cannot verify goal without tests"],
            recommendations=["Add automated tests to verify goal"],
        )

    def _run_pytest(self, project_root: Path) -> Dict[str, Any]:
        """Run pytest and parse results."""
        import subprocess
        import re

        try:
            result = subprocess.run(
                ["pytest", "--tb=no", "-q"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=300,
            )

            output = result.stdout + result.stderr

            # Parse "X passed, Y failed"
            match = re.search(r"(\d+) passed", output)
            passed = int(match.group(1)) if match else 0

            match = re.search(r"(\d+) failed", output)
            failed = int(match.group(1)) if match else 0

            return {
                "ran": True,
                "passed": passed,
                "failed": failed,
                "total": passed + failed,
            }

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {"ran": False}

    def _run_npm_test(self, project_root: Path) -> Dict[str, Any]:
        """Run npm test and parse results."""
        import subprocess

        try:
            result = subprocess.run(
                ["npm", "test"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=300,
            )

            return {
                "ran": True,
                "status": "passed" if result.returncode == 0 else "failed",
            }

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {"ran": False}


class MetricThresholdEvaluator(GoalEvaluator):
    """Evaluates data science goals based on metric thresholds."""

    def can_evaluate(self, goal: Goal) -> bool:
        """Check if goal specifies metric thresholds."""
        keywords = [
            "accuracy",
            "precision",
            "recall",
            "f1",
            "auc",
            "rmse",
            "mae",
            "r2",
            "metric",
        ]
        text = (goal.description + " " + goal.measurable_criteria).lower()
        return any(kw in text for kw in keywords)

    def evaluate(self, goal: Goal, project_root: Path) -> EvaluationResult:
        """Check if metrics meet threshold."""
        # Look for metrics files
        metrics_files = list(project_root.rglob("*metrics*.json")) + list(
            project_root.rglob("*results*.json")
        )

        if not metrics_files:
            return EvaluationResult(
                goal_id=goal.id,
                achieved=False,
                confidence=0.2,
                evidence=["No metrics files found"],
                blockers=["Cannot evaluate without metrics"],
                recommendations=["Run evaluation script to generate metrics"],
            )

        # Parse threshold from measurable_criteria
        threshold = self._extract_threshold(goal.measurable_criteria)

        # Check most recent metrics
        latest_metrics = self._load_latest_metrics(metrics_files)

        if not latest_metrics:
            return EvaluationResult(
                goal_id=goal.id,
                achieved=False,
                confidence=0.2,
                evidence=["Metrics files exist but are empty/invalid"],
                blockers=["Cannot parse metrics"],
                recommendations=["Verify metrics file format"],
            )

        # Compare against threshold
        evidence = [f"{k}: {v}" for k, v in latest_metrics.items()]

        if threshold:
            metric_name, target_value = threshold
            actual_value = latest_metrics.get(metric_name)

            if actual_value is not None and actual_value >= target_value:
                return EvaluationResult(
                    goal_id=goal.id,
                    achieved=True,
                    confidence=0.9,
                    evidence=evidence
                    + [f"{metric_name} {actual_value} >= {target_value}"],
                    blockers=[],
                    recommendations=[],
                )
            elif actual_value is not None:
                return EvaluationResult(
                    goal_id=goal.id,
                    achieved=False,
                    confidence=0.85,
                    evidence=evidence,
                    blockers=[f"{metric_name} {actual_value} < {target_value}"],
                    recommendations=[
                        "Improve model performance",
                        "Review training approach",
                    ],
                )

        # No threshold specified, use heuristics
        return EvaluationResult(
            goal_id=goal.id,
            achieved=False,
            confidence=0.4,
            evidence=evidence,
            blockers=["No threshold specified in goal criteria"],
            recommendations=["Add specific metric threshold to goal"],
        )

    def _extract_threshold(self, criteria: str) -> Optional[tuple[str, float]]:
        """Extract metric threshold from criteria text."""
        import re

        # Pattern: "accuracy >= 0.95" or "RMSE < 0.1"
        pattern = r"(\w+)\s*([><=]+)\s*([0-9.]+)"
        match = re.search(pattern, criteria, re.IGNORECASE)

        if match:
            metric_name = match.group(1).lower()
            operator = match.group(2)
            value = float(match.group(3))

            # Convert operators to threshold
            if ">=" in operator or ">" in operator:
                return (metric_name, value)
            elif "<=" in operator or "<" in operator:
                # For "less than" metrics, we'd need inverse logic
                # For now, just flag it
                return (metric_name, value)

        return None

    def _load_latest_metrics(self, metrics_files: List[Path]) -> Dict[str, float]:
        """Load the most recent metrics file."""
        import json

        # Sort by modification time
        metrics_files_sorted = sorted(
            metrics_files, key=lambda p: p.stat().st_mtime, reverse=True
        )

        for metrics_file in metrics_files_sorted:
            try:
                with open(metrics_file) as f:
                    data = json.load(f)

                # Extract numeric metrics
                metrics = {}
                for k, v in data.items():
                    if isinstance(v, (int, float)):
                        metrics[k.lower()] = float(v)

                if metrics:
                    return metrics

            except (json.JSONDecodeError, IOError):
                continue

        return {}


class APIContractEvaluator(GoalEvaluator):
    """Evaluates goals based on API contract compliance."""

    def can_evaluate(self, goal: Goal) -> bool:
        """Check if goal mentions API, endpoints, or contracts."""
        keywords = ["api", "endpoint", "contract", "openapi", "swagger", "rest"]
        text = (goal.description + " " + goal.measurable_criteria).lower()
        return any(kw in text for kw in keywords)

    def evaluate(self, goal: Goal, project_root: Path) -> EvaluationResult:
        """Check API contracts."""
        # Look for OpenAPI spec
        spec_files = (
            list(project_root.rglob("*openapi*.json"))
            + list(project_root.rglob("*openapi*.yaml"))
            + list(project_root.rglob("*swagger*.json"))
        )

        if spec_files:
            return EvaluationResult(
                goal_id=goal.id,
                achieved=True,
                confidence=0.7,
                evidence=[f"Found API spec: {spec_files[0].name}"],
                blockers=[],
                recommendations=["Validate spec against running service"],
            )

        return EvaluationResult(
            goal_id=goal.id,
            achieved=False,
            confidence=0.5,
            evidence=["No API specification found"],
            blockers=["Cannot verify API contract"],
            recommendations=["Generate OpenAPI specification", "Add API tests"],
        )


class GoalEvaluatorRegistry:
    """Registry of goal evaluators."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.evaluators: List[GoalEvaluator] = [
            TestSuiteEvaluator(),
            MetricThresholdEvaluator(),
            APIContractEvaluator(),
        ]

    def evaluate_goal(self, goal: Goal) -> EvaluationResult:
        """Evaluate a goal using appropriate evaluator."""
        # Find evaluators that can handle this goal
        capable_evaluators = [e for e in self.evaluators if e.can_evaluate(goal)]

        if not capable_evaluators:
            # Fallback: assume not achieved if no evaluator matches
            return EvaluationResult(
                goal_id=goal.id,
                achieved=False,
                confidence=0.1,
                evidence=["No evaluator matched this goal type"],
                blockers=["Goal criteria not machine-verifiable"],
                recommendations=["Add specific verification criteria to goal"],
            )

        # Use first matching evaluator (could combine multiple in future)
        evaluator = capable_evaluators[0]
        return evaluator.evaluate(goal, self.project_root)

    def evaluate_all_goals(self, goals: List[Goal]) -> Dict[str, EvaluationResult]:
        """Evaluate all goals and return results."""
        results = {}
        for goal in goals:
            results[goal.id] = self.evaluate_goal(goal)
        return results
