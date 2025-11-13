"""Domain detection helpers for richer subagent context."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..models import Goal


class DomainDetector:
    """Detect the most likely domain for the current project."""

    DATA_KEYWORDS = {"dataset", "model", "training", "accuracy", "precision"}
    BACKEND_KEYWORDS = {"api", "endpoint", "service", "backend"}
    FRONTEND_INDICATORS = {"package.json", "vite.config.ts", "next.config.js"}

    @staticmethod
    def detect(project_root: Path, goals: Iterable[Goal]) -> str:
        root = Path(project_root)
        goals_text = " ".join(goal.description for goal in goals).lower()

        if DomainDetector._looks_like_data_science(root, goals_text):
            return "data_science"
        if DomainDetector._looks_like_backend(root, goals_text):
            return "backend"
        if DomainDetector._looks_like_frontend(root):
            return "frontend"
        return "tooling"

    @staticmethod
    def _looks_like_data_science(project_root: Path, goals_text: str) -> bool:
        notebook = list(project_root.glob("**/*.ipynb"))
        training_scripts = list(project_root.glob("**/train*.py"))
        if notebook or training_scripts:
            return True
        return any(keyword in goals_text for keyword in DomainDetector.DATA_KEYWORDS)

    @staticmethod
    def _looks_like_backend(project_root: Path, goals_text: str) -> bool:
        api_dirs = list(project_root.glob("**/api"))
        backend_files = [
            "manage.py",
            "app.py",
            "main.py",
            "server.js",
        ]
        if any((project_root / file_name).exists() for file_name in backend_files):
            return True
        if api_dirs:
            return True
        return any(keyword in goals_text for keyword in DomainDetector.BACKEND_KEYWORDS)

    @staticmethod
    def _looks_like_frontend(project_root: Path) -> bool:
        return any((project_root / indicator).exists() for indicator in DomainDetector.FRONTEND_INDICATORS)


class DomainContext:
    """Construct domain-specific reminders and guardrails."""

    @staticmethod
    def build(domain: str, project_root: Path) -> str:
        if domain == "data_science":
            return DomainContext._build_ds_context(project_root)
        if domain == "backend":
            return DomainContext._build_backend_context()
        if domain == "frontend":
            return DomainContext._build_frontend_context()
        return DomainContext._build_tooling_context()

    @staticmethod
    def _build_ds_context(project_root: Path) -> str:
        dataset_info = DomainContext._get_dataset_info(project_root)
        return f"""
## Data Science Guardrails
- Check for ***data leakage***: target columns must not appear in features.
- Keep train/test splits deterministic (set seeds) and stratified when imbalanced.
- For temporal problems, ensure no future data leaks into training.
- Track evaluation metrics and confidence intervals before promoting models.
- Capture experiment metadata with `run_script` + metrics.json.

## Dataset Snapshot
{dataset_info}
""".strip()

    @staticmethod
    def _build_backend_context() -> str:
        return """
## Backend Engineering Guardrails
- Enforce input validation and sanitize any SQL/command usage.
- Maintain latency budgets (<200ms for core APIs) and include performance tests when possible.
- Return precise HTTP status codes and structured error payloads.
- Capture migrations, seed scripts, and operational runbooks in docs.
""".strip()

    @staticmethod
    def _build_frontend_context() -> str:
        return """
## Frontend / Client Guardrails
- Keep bundles small; note performance budgets and lazy-load heavy routes.
- Provide accessible components (ARIA labels, focus management).
- Ensure `npm test` / `npm run lint` stay green before shipping.
- Document user flows and edge cases in docs/components/.
""".strip()

    @staticmethod
    def _build_tooling_context() -> str:
        return """
## Tooling Guardrails
- Ship CLIs with helpful `--help`, `--version`, and sensible defaults.
- Provide actionable error messages that include the remediation steps.
- Cross-platform paths and shell commands must be guarded (Windows/macOS/Linux).
- Add unit tests for edge cases and failure modes.
""".strip()

    @staticmethod
    def _get_dataset_info(project_root: Path) -> str:
        data_dir = project_root / "data"
        if not data_dir.exists():
            return "No data/ directory detected. Document dataset sources explicitly."

        rows = []
        for file_path in sorted(data_dir.glob("**/*")):
            if not file_path.is_file() or file_path.suffix.lower() not in {".csv", ".parquet", ".json"}:
                continue
            size_kb = round(file_path.stat().st_size / 1024, 1)
            rows.append(f"- {file_path.relative_to(project_root)} ({size_kb} KB)")
            if len(rows) >= 5:
                break

        if not rows:
            return "Data directory present but no CSV/Parquet/JSON files detected."
        return "\n".join(rows)
