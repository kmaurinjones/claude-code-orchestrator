"""Unified validator modules for rich verification check types."""

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of running a validation check."""

    passed: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class HTTPEndpointValidator:
    """Validate HTTP endpoints."""

    @staticmethod
    def validate(
        target: str, expected: Optional[str], timeout: int = 30
    ) -> ValidationResult:
        """
        Check HTTP endpoint.

        Args:
            target: URL to check
            expected: Expected status code (e.g., "200", "2xx", "200-299")
            timeout: Request timeout in seconds
        """
        try:
            import requests

            response = requests.get(target, timeout=timeout)

            # Parse expected status
            if expected:
                if "-" in expected:
                    # Range: "200-299"
                    low, high = map(int, expected.split("-"))
                    passed = low <= response.status_code <= high
                elif "x" in expected.lower():
                    # Pattern: "2xx"
                    expected_prefix = expected.replace("x", "").replace("X", "")
                    passed = str(response.status_code).startswith(expected_prefix)
                else:
                    # Exact: "200"
                    passed = response.status_code == int(expected)
            else:
                # Default: any 2xx is success
                passed = 200 <= response.status_code < 300

            return ValidationResult(
                passed=passed,
                message=f"HTTP {response.status_code}"
                + (f" (expected {expected})" if expected else ""),
                metadata={"status_code": response.status_code, "url": target},
            )

        except requests.exceptions.Timeout:
            return ValidationResult(
                passed=False,
                message=f"Request timed out after {timeout}s",
            )
        except requests.exceptions.ConnectionError as e:
            return ValidationResult(
                passed=False,
                message=f"Connection failed: {str(e)}",
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                message=f"HTTP check failed: {str(e)}",
            )


class MetricThresholdValidator:
    """Validate metrics meet thresholds."""

    @staticmethod
    def validate(target: str, expected: str, project_root: Path) -> ValidationResult:
        """
        Check metric threshold.

        Args:
            target: Metric name or path to metrics file
            expected: Threshold expression (e.g., ">= 0.95", "< 0.1")
            project_root: Project root directory
        """
        # Check if target is a file path
        if "/" in target or target.endswith(".json"):
            metrics_file = project_root / target
        else:
            # Search for metrics files
            metrics_files = list(project_root.rglob("*metrics*.json")) + list(
                project_root.rglob("*results*.json")
            )

            if not metrics_files:
                return ValidationResult(
                    passed=False,
                    message="No metrics files found",
                )

            metrics_file = sorted(metrics_files, key=lambda p: p.stat().st_mtime)[-1]

        # Load metrics
        try:
            with open(metrics_file) as f:
                metrics_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            return ValidationResult(
                passed=False,
                message=f"Failed to load metrics: {e}",
            )

        # Extract metric value
        metric_name = (
            target.split("/")[-1].replace(".json", "") if "/" in target else target
        )
        metric_value = metrics_data.get(metric_name)

        if metric_value is None:
            return ValidationResult(
                passed=False,
                message=f"Metric '{metric_name}' not found in {metrics_file.name}",
            )

        # Parse threshold
        match = re.match(r"([><=]+)\s*([0-9.]+)", expected.strip())
        if not match:
            return ValidationResult(
                passed=False,
                message=f"Invalid threshold format: {expected}",
            )

        operator = match.group(1)
        threshold = float(match.group(2))

        # Evaluate
        if operator == ">=":
            passed = metric_value >= threshold
        elif operator == ">":
            passed = metric_value > threshold
        elif operator == "<=":
            passed = metric_value <= threshold
        elif operator == "<":
            passed = metric_value < threshold
        elif operator == "==":
            passed = abs(metric_value - threshold) < 1e-6
        else:
            return ValidationResult(
                passed=False,
                message=f"Unknown operator: {operator}",
            )

        return ValidationResult(
            passed=passed,
            message=f"{metric_name} = {metric_value} (expected {expected})",
            metadata={
                "metric": metric_name,
                "value": metric_value,
                "threshold": threshold,
            },
        )


class SchemaValidator:
    """Validate JSON/YAML against schemas."""

    @staticmethod
    def validate(target: str, expected: str, project_root: Path) -> ValidationResult:
        """
        Validate file against schema.

        Args:
            target: Path to file to validate
            expected: Path to schema file or inline schema
            project_root: Project root
        """
        target_path = project_root / target

        if not target_path.exists():
            return ValidationResult(
                passed=False,
                message=f"File not found: {target}",
            )

        # Load target file
        try:
            with open(target_path) as f:
                if target_path.suffix in (".json", ".jsonl"):
                    data = json.load(f)
                elif target_path.suffix in (".yaml", ".yml"):
                    import yaml

                    data = yaml.safe_load(f)
                else:
                    return ValidationResult(
                        passed=False,
                        message=f"Unsupported file type: {target_path.suffix}",
                    )
        except Exception as e:
            return ValidationResult(
                passed=False,
                message=f"Failed to parse {target}: {e}",
            )

        # Load schema
        try:
            schema_path = project_root / expected
            if schema_path.exists():
                with open(schema_path) as f:
                    schema = json.load(f)
            else:
                # Try parsing as inline JSON
                schema = json.loads(expected)
        except Exception as e:
            return ValidationResult(
                passed=False,
                message=f"Failed to load schema: {e}",
            )

        # Validate
        try:
            import jsonschema

            jsonschema.validate(instance=data, schema=schema)
            return ValidationResult(
                passed=True,
                message=f"Schema validation passed for {target}",
            )
        except jsonschema.ValidationError as e:
            return ValidationResult(
                passed=False,
                message=f"Schema validation failed: {e.message}",
            )
        except ImportError:
            return ValidationResult(
                passed=False,
                message="jsonschema package not installed (pip install jsonschema)",
            )


class SecurityScanValidator:
    """Run security scans."""

    @staticmethod
    def validate(
        target: str, expected: Optional[str], project_root: Path, timeout: int = 300
    ) -> ValidationResult:
        """
        Run security scanner.

        Args:
            target: Scanner to use ("bandit", "eslint", "safety", etc.) or path to scan
            expected: Expected result ("no-issues" or severity threshold)
            project_root: Project root
            timeout: Command timeout
        """
        # Determine scanner
        if target in ("bandit", "safety", "eslint", "npm audit"):
            scanner = target
            scan_path = str(project_root)
        else:
            # Try to infer from file extension
            target_path = project_root / target
            if target_path.suffix == ".py":
                scanner = "bandit"
            elif target_path.suffix in (".js", ".ts", ".jsx", ".tsx"):
                scanner = "eslint"
            else:
                return ValidationResult(
                    passed=False,
                    message=f"Cannot infer scanner for {target}",
                )
            scan_path = str(target_path)

        # Build command
        if scanner == "bandit":
            cmd = ["bandit", "-r", scan_path, "-f", "json"]
        elif scanner == "eslint":
            cmd = ["eslint", scan_path, "--format", "json"]
        elif scanner == "safety":
            cmd = ["safety", "check", "--json"]
        elif scanner == "npm audit":
            cmd = ["npm", "audit", "--json"]
        else:
            return ValidationResult(
                passed=False,
                message=f"Unknown scanner: {scanner}",
            )

        # Run scanner
        try:
            result = subprocess.run(
                cmd,
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            # Parse results
            try:
                output_data = json.loads(result.stdout)
            except json.JSONDecodeError:
                # Some tools don't output valid JSON on error
                output_data = {}

            # Check for issues
            issues_count = 0
            if scanner == "bandit":
                issues_count = len(output_data.get("results", []))
            elif scanner == "eslint":
                issues_count = sum(len(f.get("messages", [])) for f in output_data)
            elif scanner in ("safety", "npm audit"):
                issues_count = len(output_data.get("vulnerabilities", []))

            passed = issues_count == 0

            return ValidationResult(
                passed=passed,
                message=f"{scanner}: {issues_count} issues found",
                stdout=result.stdout[:1000],
                stderr=result.stderr[:1000],
                metadata={"scanner": scanner, "issues": issues_count},
            )

        except subprocess.TimeoutExpired:
            return ValidationResult(
                passed=False,
                message=f"{scanner} timed out after {timeout}s",
            )
        except FileNotFoundError:
            return ValidationResult(
                passed=False,
                message=f"{scanner} not installed",
            )


class TypeCheckValidator:
    """Run type checkers."""

    @staticmethod
    def validate(
        target: str, expected: Optional[str], project_root: Path, timeout: int = 300
    ) -> ValidationResult:
        """
        Run type checker.

        Args:
            target: Type checker ("mypy", "tsc", "pyright") or path to check
            expected: Expected result (typically "pass")
            project_root: Project root
            timeout: Command timeout
        """
        # Determine type checker
        if target in ("mypy", "pyright", "tsc"):
            checker = target
            check_path = str(project_root)
        else:
            # Infer from extension
            target_path = project_root / target
            if target_path.suffix == ".py":
                checker = "mypy"
            elif target_path.suffix in (".ts", ".tsx"):
                checker = "tsc"
            else:
                return ValidationResult(
                    passed=False,
                    message=f"Cannot infer type checker for {target}",
                )
            check_path = str(target_path)

        # Build command
        if checker == "mypy":
            cmd = ["mypy", check_path, "--no-error-summary"]
        elif checker == "pyright":
            cmd = ["pyright", check_path]
        elif checker == "tsc":
            cmd = ["tsc", "--noEmit"]
        else:
            return ValidationResult(
                passed=False,
                message=f"Unknown type checker: {checker}",
            )

        # Run
        try:
            result = subprocess.run(
                cmd,
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            passed = result.returncode == 0

            return ValidationResult(
                passed=passed,
                message=f"{checker}: {'passed' if passed else 'failed'}",
                stdout=result.stdout[:1000],
                stderr=result.stderr[:1000],
            )

        except subprocess.TimeoutExpired:
            return ValidationResult(
                passed=False,
                message=f"{checker} timed out after {timeout}s",
            )
        except FileNotFoundError:
            return ValidationResult(
                passed=False,
                message=f"{checker} not installed",
            )


class DataQualityValidator:
    """Validate dataset quality."""

    @staticmethod
    def validate(target: str, expected: str, project_root: Path) -> ValidationResult:
        """
        Check dataset quality.

        Args:
            target: Path to dataset (CSV, JSON, parquet)
            expected: Quality check (e.g., "no-nulls", "no-duplicates", "range:0-1")
            project_root: Project root
        """
        target_path = project_root / target

        if not target_path.exists():
            return ValidationResult(
                passed=False,
                message=f"Dataset not found: {target}",
            )

        # Load dataset
        try:
            import pandas as pd

            if target_path.suffix == ".csv":
                df = pd.read_csv(target_path)
            elif target_path.suffix == ".json":
                df = pd.read_json(target_path)
            elif target_path.suffix == ".parquet":
                df = pd.read_parquet(target_path)
            else:
                return ValidationResult(
                    passed=False,
                    message=f"Unsupported dataset format: {target_path.suffix}",
                )
        except ImportError:
            return ValidationResult(
                passed=False,
                message="pandas not installed (pip install pandas)",
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                message=f"Failed to load dataset: {e}",
            )

        # Run quality check
        if expected == "no-nulls":
            null_count = df.isnull().sum().sum()
            passed = null_count == 0
            message = f"{'No' if passed else null_count} null values found"

        elif expected == "no-duplicates":
            dup_count = df.duplicated().sum()
            passed = dup_count == 0
            message = f"{'No' if passed else dup_count} duplicate rows found"

        elif expected.startswith("range:"):
            # Check numeric columns are in range
            range_spec = expected.replace("range:", "")
            low, high = map(float, range_spec.split("-"))

            numeric_cols = df.select_dtypes(include=["number"]).columns
            out_of_range = 0

            for col in numeric_cols:
                out_of_range += ((df[col] < low) | (df[col] > high)).sum()

            passed = out_of_range == 0
            message = f"{'No' if passed else out_of_range} values outside range [{low}, {high}]"

        else:
            return ValidationResult(
                passed=False,
                message=f"Unknown quality check: {expected}",
            )

        return ValidationResult(
            passed=passed,
            message=message,
            metadata={"rows": len(df), "columns": len(df.columns)},
        )
