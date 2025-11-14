"""Critic phase that enforces coding standards and conventions."""

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
    """Runs convention checks after reviewer feedback."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()

    def evaluate(self, task_id: str) -> CriticFeedback:
        findings: List[str] = []

        changed_files = self._collect_changed_files()
        findings.extend(self._check_file_names(changed_files))
        findings.extend(self._check_trailing_whitespace(changed_files))
        lint_result = self._run_lint()
        if lint_result:
            findings.append(lint_result)

        if findings:
            summary = (
                f"Critic detected {len(findings)} convention issue(s) after {task_id}."
            )
            console.print(f"[red]Critic[/red] {summary}")
            return CriticFeedback(status="FAIL", summary=summary, findings=findings)

        summary = f"Critic approved changes for {task_id}."
        console.print(f"[green]Critic[/green] {summary}")
        return CriticFeedback(status="PASS", summary=summary, findings=[])

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

    def _run_lint(self) -> Optional[str]:
        """Attempt to run ruff (if available)."""
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
            return "Ruff reported issues:\n" + "\n".join(snippet)

        return None
