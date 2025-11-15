"""Critic phase that enforces coding standards and conventions.

The Critic acts as the final production-readiness gate, enforcing strict quality standards
before allowing any task to be marked complete. Think of this as the barrier between
development and production deployment - it must be satisfied that code meets professional
standards before allowing it through.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import List, Optional

from rich.console import Console

console = Console()


@dataclass
class CriticFeedback:
    status: str  # PASS | FAIL
    summary: str
    findings: List[str]


class Critic:
    """
    Production-readiness gatekeeper that enforces strict quality standards.

    The Critic is intentionally strict - it represents the final quality gate before
    code would be deployed to production. It enforces:
    - Naming conventions and code style
    - Structural quality and maintainability
    - Security and safety patterns
    - Documentation standards
    - Error handling completeness

    This is not about being impossible to please, but about ensuring professional-grade
    output that won't cause problems downstream.
    """

    def __init__(self, project_root: Path, workspace: Path):
        self.project_root = Path(project_root).resolve()
        self.workspace = Path(workspace).resolve()

    def evaluate(self, task_id: str, domain: Optional[str] = None) -> CriticFeedback:
        """
        Perform comprehensive quality evaluation.

        Returns FAIL if ANY quality issue is detected - this is intentional.
        Code must meet ALL standards to pass the production-readiness gate.
        """
        findings: List[str] = []

        changed_files = self._collect_changed_files()

        # Mechanical checks (must pass)
        findings.extend(self._check_file_names(changed_files))
        findings.extend(self._check_trailing_whitespace(changed_files))

        # Code quality checks (must pass)
        findings.extend(self._check_code_quality(changed_files))

        # Linting (must pass)
        lint_result = self._run_lint()
        if lint_result:
            findings.append(lint_result)

        findings.extend(self._domain_specific_findings(domain))

        if findings:
            summary = (
                f"BLOCKED: {len(findings)} production-readiness issue(s) detected. "
                "Code must meet ALL quality standards before completion."
            )
            console.print(f"[red]Critic[/red] {summary}")
            return CriticFeedback(status="FAIL", summary=summary, findings=findings)

        summary = f"Production-ready: All quality standards met for {task_id}."
        console.print(f"[green]Critic[/green] {summary}")
        return CriticFeedback(status="PASS", summary=summary, findings=[])

    def _domain_specific_findings(self, domain: Optional[str]) -> List[str]:
        if not domain:
            return []
        findings: List[str] = []
        normalized = domain.lower()
        if normalized == "data_science":
            experiments_file = self.workspace / "history" / "experiments.jsonl"
            if not experiments_file.exists() or not experiments_file.read_text(encoding="utf-8").strip():
                findings.append(
                    "No recorded experiments in .agentic/history/experiments.jsonl. "
                    "Run `orchestrate experiment` or log calibration runs before finalizing."
                )
        return findings

    def _collect_changed_files(self) -> List[str]:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            return []

        files: List[str] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            status, path = line[:2].strip(), line[3:].strip()
            if status in {"M", "A", "??"} and path:
                files.append(path)
        return files

    def _check_file_names(self, files: List[str]) -> List[str]:
        findings: List[str] = []
        snake_case = re.compile(r"^[a-z0-9_./-]+$")
        for path in files:
            if not path.endswith((".py", ".md", ".txt")):
                continue
            filename = Path(path).name
            if " " in filename:
                findings.append(f"{path}: file name contains spaces.")
            if path.endswith(".py") and not snake_case.match(filename.replace(".py", "")):
                findings.append(f"{path}: python files should use snake_case.")
        return findings

    def _check_trailing_whitespace(self, files: List[str]) -> List[str]:
        findings: List[str] = []
        for relative in files:
            file_path = self.project_root / relative
            if not file_path.exists() or file_path.is_dir():
                continue
            if file_path.suffix not in {".py", ".md", ".txt"}:
                continue
            try:
                for idx, line in enumerate(file_path.read_text().splitlines(), start=1):
                    if line.endswith(" ") or "\t" in line:
                        findings.append(f"{relative}: line {idx} has trailing whitespace or tabs.")
                        break
            except UnicodeDecodeError:
                continue
        return findings

    def _check_code_quality(self, files: List[str]) -> List[str]:
        """
        Comprehensive code quality checks.

        These are production-readiness standards that all code must meet.
        This is the final gate - be strict but fair.
        """
        findings: List[str] = []

        for relative in files:
            file_path = self.project_root / relative

            if not file_path.exists() or file_path.is_dir():
                continue

            # Python file quality checks
            if file_path.suffix == ".py":
                findings.extend(self._check_python_quality(relative, file_path))

            # Markdown documentation checks
            elif file_path.suffix == ".md":
                findings.extend(self._check_markdown_quality(relative, file_path))

            # Configuration file checks
            elif file_path.suffix in {".json", ".yaml", ".yml", ".toml"}:
                findings.extend(self._check_config_quality(relative, file_path))

        return findings

    def _check_python_quality(self, relative: str, file_path: Path) -> List[str]:
        """Python-specific quality checks for production readiness."""
        findings: List[str] = []

        try:
            content = file_path.read_text()
            lines = content.splitlines()

            # Check 1: Modules must have docstrings
            if not content.strip().startswith('"""') and not content.strip().startswith("'''"):
                # Allow __init__.py to be minimal
                if file_path.name != "__init__.py" or len(content.strip()) > 50:
                    findings.append(
                        f"{relative}: Missing module-level docstring. "
                        "All Python modules must document their purpose."
                    )

            # Check 2: Look for bare except clauses (production anti-pattern)
            for i, line in enumerate(lines, start=1):
                if re.search(r"except\s*:", line):
                    findings.append(
                        f"{relative}:{i}: Bare 'except:' clause detected. "
                        "Always specify exception types for production code."
                    )

            # Check 3: Look for TODO/FIXME/HACK comments (must be resolved)
            for i, line in enumerate(lines, start=1):
                if re.search(r"#\s*(TODO|FIXME|HACK|XXX)", line, re.IGNORECASE):
                    findings.append(
                        f"{relative}:{i}: Unresolved TODO/FIXME/HACK comment. "
                        "All technical debt markers must be addressed before completion."
                    )

            # Check 4: Look for debug statements (must be removed)
            for i, line in enumerate(lines, start=1):
                if re.search(r"\bprint\s*\(", line) and "# DEBUG" not in line.upper():
                    # Allow logging and intentional output
                    if "logger" not in line and "console" not in line and "log" not in line.lower():
                        findings.append(
                            f"{relative}:{i}: Debug print() statement detected. "
                            "Use logging instead of print() for production code."
                        )

            # Check 5: Look for hardcoded credentials/secrets patterns
            secret_patterns = [
                (r"password\s*=\s*['\"](?!{{)[^'\"]+['\"]", "hardcoded password"),
                (r"api[_-]?key\s*=\s*['\"](?!{{)[^'\"]+['\"]", "hardcoded API key"),
                (r"secret\s*=\s*['\"](?!{{)[^'\"]+['\"]", "hardcoded secret"),
                (r"token\s*=\s*['\"](?!{{)[^'\"]+['\"]", "hardcoded token"),
            ]
            for i, line in enumerate(lines, start=1):
                for pattern, desc in secret_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        findings.append(
                            f"{relative}:{i}: Possible {desc}. "
                            "Credentials must be externalized to environment variables."
                        )

            # Check 6: Functions without docstrings (for non-trivial code)
            if len(lines) > 30:  # Only enforce for substantial files
                func_matches = re.finditer(r"^\s*def\s+(\w+)\s*\(", content, re.MULTILINE)
                for match in func_matches:
                    func_name = match.group(1)
                    if func_name.startswith("_"):  # Allow private functions to skip
                        continue
                    # Check if next non-empty line is a docstring
                    start_pos = match.end()
                    rest = content[start_pos:start_pos + 200]
                    if not re.search(r'^\s*"""', rest) and not re.search(r"^\s*'''", rest):
                        findings.append(
                            f"{relative}: Function '{func_name}' missing docstring. "
                            "Public functions must document parameters and behavior."
                        )
                        break  # Report once per file

        except UnicodeDecodeError:
            pass  # Binary file, skip

        return findings

    def _check_markdown_quality(self, relative: str, file_path: Path) -> List[str]:
        """Markdown documentation quality checks."""
        findings: List[str] = []

        try:
            content = file_path.read_text()

            # Check 1: Documentation files should have headers
            if not content.strip().startswith("#"):
                findings.append(
                    f"{relative}: Documentation missing top-level header. "
                    "All docs should start with a descriptive title."
                )

            # Check 2: Check for broken internal links (basic check)
            link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"
            for match in re.finditer(link_pattern, content):
                link_target = match.group(2)
                # Check local file links
                if not link_target.startswith(("http://", "https://", "#")):
                    target_path = (file_path.parent / link_target).resolve()
                    if not target_path.exists():
                        findings.append(
                            f"{relative}: Broken link to '{link_target}'. "
                            "All documentation links must be valid."
                        )

        except UnicodeDecodeError:
            pass

        return findings

    def _check_config_quality(self, relative: str, file_path: Path) -> List[str]:
        """Configuration file quality checks."""
        findings: List[str] = []

        try:
            content = file_path.read_text()

            # Check for credentials in config files
            if re.search(r"password|api[_-]?key|secret|token", content, re.IGNORECASE):
                # Check if values look like actual secrets (not placeholders)
                if re.search(r"['\"][\w-]{20,}['\"]", content):
                    findings.append(
                        f"{relative}: Possible credentials in config file. "
                        "Use environment variables or secure secret management."
                    )

        except UnicodeDecodeError:
            pass

        return findings

    def _run_lint(self) -> Optional[str]:
        """
        Run linter if available.

        Production code must pass linting - this is non-negotiable.
        """
        cmd = None
        if which("ruff"):
            cmd = ["ruff", "check", "--quiet"]
        elif which("python"):
            cmd = ["python", "-m", "ruff", "check", "--quiet"]

        if not cmd:
            return None

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception:
            return "Ruff linting skipped (failed to execute)."

        if result.returncode != 0:
            output = result.stdout.strip() or result.stderr.strip()
            snippet = output.splitlines()[:5]
            return "LINTING FAILED - production code must pass all lint checks:\n" + "\n".join(snippet)

        return None
