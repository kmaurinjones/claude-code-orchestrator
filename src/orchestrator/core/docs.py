"""Documentation manager for maintaining project docs/ directory."""

from pathlib import Path
from typing import Dict, Any, Optional
from uuid import uuid4

from .subagent import Subagent
from .logger import EventLogger
from ..models import Task


class DocsManager:
    """Manages automatic documentation generation and updates."""

    def __init__(self, project_root: Path, logger: EventLogger):
        self.project_root = project_root
        self.docs_dir = project_root / "docs"
        self.logger = logger

    def initialize(self) -> None:
        """Create initial docs/ directory structure if it doesn't exist."""
        if not self.docs_dir.exists():
            self.docs_dir.mkdir(parents=True, exist_ok=True)

        # Create initial docs README
        docs_readme = self.docs_dir / "README.md"
        if not docs_readme.exists():
            docs_readme.write_text("""# Project Documentation

## Overview

This directory contains comprehensive documentation for the project.

## Documentation Structure

- **README.md** (this file) - Documentation overview and getting started
- **architecture.md** - System architecture and design decisions
- **components/** - Individual component documentation
- **scripts.md** - How to run scripts and what they do
- **api.md** - API documentation (if applicable)
- **troubleshooting.md** - Common issues and solutions

## Quick Start

[To be populated]

## Contributing

[To be populated]
""")

        # Ensure top-level project README exists
        project_readme = self.project_root / "README.md"
        if not project_readme.exists():
            project_readme.write_text("""# Project Overview

## Quick Start

Explain how to run the project here.

## Features

- Bullet point summaries

## Configuration

Document environment variables or config files here.
""")

        (self.docs_dir / "components").mkdir(exist_ok=True)

    def update_after_task(
        self,
        task: Task,
        success: bool,
        changes_summary: str,
        workspace: Path,
        step: int,
        parent_trace_id: str,
        log_workspace: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Update documentation after a task completes.

        Args:
            task: The completed task
            success: Whether task succeeded
            changes_summary: Summary of what changed
            workspace: Workspace path
            step: Current orchestrator step
            parent_trace_id: Parent trace ID for logging

        Returns:
            Dict with update results
        """
        self.initialize()

        # Build context about the task and changes
        context = self._build_task_context(task, success, changes_summary)

        # Determine what documentation needs updating
        docs_to_update = self._identify_docs_to_update(task, changes_summary)

        instruction = f"""You are the documentation maintainer. Update project documentation based on the completed task.

## Task Information
- **Task ID**: {task.id}
- **Title**: {task.title}
- **Status**: {'SUCCESS' if success else 'FAILED'}
- **Description**: {task.description}

## Changes Made
{changes_summary}

## Your Responsibilities

1. **Update existing documentation** in `docs/` directory to reflect changes
2. **Create new documentation** if new components/features were added
3. **Document failures** in troubleshooting.md if task failed
4. **Maintain accuracy** - ensure all docs match current state

## Documentation to Update
{self._format_docs_list(docs_to_update)}

## Guidelines

- Keep documentation clear, concise, and up-to-date
- Include code examples where helpful
- Document "why" decisions were made, not just "what"
- For failed tasks, document what was attempted and why it failed
- Update component relationships if architecture changed
- Ensure scripts.md accurately describes how to run everything

## Output

Update the relevant documentation files. Be thorough but concise.
Focus on making the documentation useful for someone new to the project.
"""

        # Spawn documentation subagent
        agent = Subagent(
            task_id=f"docs-{task.id}",
            task_description=instruction,
            context=context,
            parent_trace_id=parent_trace_id,
            logger=self.logger,
            step=step,
            workspace=workspace,
            max_turns=20,  # Docs updates may need more turns
            model="haiku",
            log_workspace=log_workspace or workspace,
        )

        result = agent.execute()

        return {
            "success": result.get("success", False),
            "updated_files": result.get("files_modified", []),
            "output": result.get("output", ""),
        }

    def _build_task_context(
        self,
        task: Task,
        success: bool,
        changes_summary: str
    ) -> str:
        """Build context string about the task for the docs agent."""
        lines = [
            "## Current Project State",
            "",
            f"Task {task.id} ({'succeeded' if success else 'failed'})",
            "",
            "## Recent Changes",
            changes_summary,
            "",
        ]

        if task.review_feedback:
            lines.extend([
                "## Review Feedback",
                *[f"- {feedback}" for feedback in task.review_feedback[-3:]],
                "",
            ])

        # List existing documentation
        if self.docs_dir.exists():
            lines.append("## Existing Documentation Files")
            for doc_file in sorted(self.docs_dir.rglob("*.md")):
                rel_path = doc_file.relative_to(self.project_root)
                lines.append(f"- {rel_path}")

        return "\n".join(lines)

    def _identify_docs_to_update(
        self,
        task: Task,
        changes_summary: str
    ) -> list[str]:
        """
        Identify which documentation files likely need updates.
        Returns list of file paths relative to project root.
        """
        docs_to_update = []

        # Always consider main docs
        docs_to_update.append("docs/README.md")

        # Check if architectural changes were made
        arch_keywords = ["architecture", "design", "structure", "component", "module"]
        if any(kw in task.description.lower() or kw in changes_summary.lower() for kw in arch_keywords):
            docs_to_update.append("docs/architecture.md")

        # Check if scripts were added/modified
        script_keywords = ["script", "run", "execute", "command", ".py", ".sh"]
        if any(kw in task.description.lower() or kw in changes_summary.lower() for kw in script_keywords):
            docs_to_update.append("docs/scripts.md")

        # Check if API changes were made
        api_keywords = ["api", "endpoint", "route", "request", "response"]
        if any(kw in task.description.lower() or kw in changes_summary.lower() for kw in api_keywords):
            docs_to_update.append("docs/api.md")

        # Check if troubleshooting needed (for failures)
        if "error" in changes_summary.lower() or "failed" in changes_summary.lower():
            docs_to_update.append("docs/troubleshooting.md")

        return docs_to_update

    def _format_docs_list(self, docs_list: list[str]) -> str:
        """Format list of docs to update as markdown."""
        if not docs_list:
            return "- All documentation in `docs/` directory"

        return "\n".join(f"- `{doc}`" for doc in docs_list)

    def ensure_readme_alignment(
        self,
        project_readme: Path,
        docs_directory: Path,
        recent_task: Task,
        success: bool,
        logger: EventLogger,
        step: int,
    ) -> None:
        """Ensure top-level README exists and stays aligned with docs state."""
        project_readme = Path(project_readme)
        docs_directory = Path(docs_directory)

        if not project_readme.exists():
            self.initialize()

        instructions = f"""You are the README maintainer. Update the top-level README to reflect the current state of the project.

## Current Task
- ID: {recent_task.id}
- Title: {recent_task.title}
- Status: {'SUCCESS' if success else 'FAILED'}
- Description: {recent_task.description}

## Requirements
1. Ensure the README includes:
   - Concise overview of what the project does
   - Prerequisites (language/runtime, packages)
   - Quick start instructions (how to run the main functionality)
   - Optional commands or features that exist (only mention real functionality)
2. Keep it concise (not thousands of words) but accurate and actionable.
3. Align sections with docs/README.md when applicable.
"""

        agent = Subagent(
            task_id=f"readme-{recent_task.id}",
            task_description=instructions,
            context=self._build_readme_context(project_readme, docs_directory),
            parent_trace_id=f"docs-{recent_task.id}",
            logger=logger,
            step=step,
            workspace=self.project_root,
            max_turns=12,
            model="haiku",
            log_workspace=self.project_root / ".agentic" if (self.project_root / ".agentic").exists() else self.project_root,
        )

        agent.execute()

    def _build_readme_context(self, project_readme: Path, docs_directory: Path) -> str:
        sections = []

        if project_readme.exists():
            sections.append("## Existing README")
            sections.append(project_readme.read_text()[:2000])

        docs_readme = docs_directory / "README.md"
        if docs_readme.exists():
            sections.append("## docs/README.md")
            sections.append(docs_readme.read_text()[:2000])

        return "\n".join(sections)

    def generate_comprehensive_docs(
        self,
        workspace: Path,
        step: int,
        parent_trace_id: str,
        log_workspace: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Generate comprehensive documentation for the entire project.
        Useful at project completion or major milestones.
        """
        self.initialize()

        instruction = """You are the documentation writer. Generate comprehensive documentation for this project.

## Your Task

Create/update complete documentation in the `docs/` directory:

1. **docs/README.md** - Overview, quick start, project structure
2. **docs/architecture.md** - System design, component relationships, key decisions
3. **docs/scripts.md** - All scripts, how to run them, what they do, expected output
4. **docs/api.md** - API endpoints, request/response formats (if applicable)
5. **docs/troubleshooting.md** - Common issues, error messages, solutions
6. **docs/components/** - Individual files for major components

## Guidelines

- Survey the entire codebase to understand what exists
- Write for someone new to the project
- Include practical examples and usage
- Document both successes and known limitations
- Keep it maintainable (not too verbose)

## Output

Create comprehensive, accurate, and useful documentation.
"""

        context = self._build_comprehensive_context()

        agent = Subagent(
            task_id=f"docs-comprehensive-{uuid4().hex[:6]}",
            task_description=instruction,
            context=context,
            parent_trace_id=parent_trace_id,
            logger=self.logger,
            step=step,
            workspace=workspace,
            max_turns=30,  # Comprehensive docs need more turns
            model="sonnet",
            log_workspace=log_workspace or workspace,
        )

        result = agent.execute()

        return {
            "success": result.get("success", False),
            "output": result.get("output", ""),
        }

    def _build_comprehensive_context(self) -> str:
        """Build context for comprehensive documentation generation."""
        lines = [
            "## Project Structure",
            "",
            "Analyze the codebase to understand:",
            "- Main entry points and how to run the project",
            "- Key components and their relationships",
            "- External dependencies and requirements",
            "- Configuration files and environment variables",
            "- Testing strategy and how to run tests",
            "",
        ]

        # Add existing docs info
        if self.docs_dir.exists():
            lines.append("## Existing Documentation")
            for doc_file in sorted(self.docs_dir.rglob("*.md")):
                lines.append(f"- {doc_file.relative_to(self.project_root)}")

        return "\n".join(lines)
