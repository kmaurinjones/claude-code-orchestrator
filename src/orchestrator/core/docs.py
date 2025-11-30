"""Documentation manager for maintaining project docs/ directory."""

from pathlib import Path
from typing import Dict, Any, List, Optional
from uuid import uuid4

from .subagent import Subagent
from .logger import EventLogger
from ..models import Task


# Domains that have software components worth documenting individually
COMPONENT_DOMAINS = {"backend", "frontend", "web_app", "tooling"}

# Domains that are research/data focused (no traditional software components)
RESEARCH_DOMAINS = {"data_science", "research"}


class DocsManager:
    """Manages automatic documentation generation and updates."""

    def __init__(
        self,
        project_root: Path,
        logger: EventLogger,
        domain: Optional[str] = None,
    ):
        self.project_root = project_root
        self.docs_dir = project_root / "docs"
        self.logger = logger
        self.domain = domain
        self._has_components = self._should_have_components()

    def _should_have_components(self) -> bool:
        """Determine if this project should have a docs/components/ directory."""
        if self.domain in COMPONENT_DOMAINS:
            return True
        if self.domain in RESEARCH_DOMAINS:
            return False

        # Heuristic: check for code files that suggest components
        code_indicators = [
            list(self.project_root.glob("**/*.py")),
            list(self.project_root.glob("**/*.js")),
            list(self.project_root.glob("**/*.ts")),
            list(self.project_root.glob("**/*.go")),
            list(self.project_root.glob("**/*.rs")),
        ]

        # If we have substantial code files, likely has components
        total_code_files = sum(len(files) for files in code_indicators)
        return total_code_files > 5

    def initialize(self) -> None:
        """Create initial docs/ directory structure based on domain."""
        if not self.docs_dir.exists():
            self.docs_dir.mkdir(parents=True, exist_ok=True)

        # Build domain-appropriate docs README
        docs_readme = self.docs_dir / "README.md"
        if not docs_readme.exists():
            docs_readme.write_text(self._generate_docs_readme())

        # Ensure top-level project README exists
        project_readme = self.project_root / "README.md"
        if not project_readme.exists():
            project_readme.write_text(self._generate_project_readme())

        # Only create components/ for domains that need it
        if self._has_components:
            (self.docs_dir / "components").mkdir(exist_ok=True)

    def _generate_docs_readme(self) -> str:
        """Generate domain-appropriate docs/README.md content."""
        base_structure = """# Project Documentation

## Overview

This directory contains comprehensive documentation for the project.

## Documentation Structure

- **README.md** (this file) - Documentation overview and getting started
"""

        if self._has_components:
            base_structure += """- **architecture.md** - System architecture and design decisions
- **components/** - Individual component documentation
- **api.md** - API documentation (if applicable)
"""
        else:
            # Research/data science projects
            base_structure += """- **research.md** - Research methodology and findings
- **data.md** - Dataset documentation and sources
"""

        base_structure += """- **scripts.md** - How to run scripts and what they do
- **troubleshooting.md** - Common issues and solutions

## Quick Start

[To be populated]

## Contributing

[To be populated]
"""
        return base_structure

    def _generate_project_readme(self) -> str:
        """Generate domain-appropriate top-level README."""
        return """# Project Overview

## Quick Start

Explain how to run the project here.

## Features

- Bullet point summaries

## Configuration

Document environment variables or config files here.
"""

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
        """Update documentation after a task completes."""
        self.initialize()

        context = self._build_task_context(task, success, changes_summary)
        docs_to_update = self._identify_docs_to_update(task, changes_summary)

        instruction = f"""You are the documentation maintainer. Update project documentation based on the completed task.

## Task Information
- **Task ID**: {task.id}
- **Title**: {task.title}
- **Status**: {"SUCCESS" if success else "FAILED"}
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
{self._get_domain_guidelines()}

## Output

Update the relevant documentation files. Be thorough but concise.
Focus on making the documentation useful for someone new to the project.
"""

        agent = Subagent(
            task_id=f"docs-{task.id}",
            task_description=instruction,
            context=context,
            parent_trace_id=parent_trace_id,
            logger=self.logger,
            step=step,
            workspace=workspace,
            max_turns=20,
            model="sonnet",
            log_workspace=log_workspace or workspace,
        )

        result = agent.execute()

        return {
            "success": result.get("success", False),
            "updated_files": result.get("files_modified", []),
            "output": result.get("output", ""),
        }

    def _get_domain_guidelines(self) -> str:
        """Get domain-specific documentation guidelines."""
        if self._has_components:
            return """- Update component relationships if architecture changed
- Create individual component docs in docs/components/ for new modules
- Ensure scripts.md accurately describes how to run everything"""
        else:
            return """- Update research methodology if approach changed
- Document data sources and transformations
- Keep findings and conclusions up to date"""

    def _build_task_context(
        self, task: Task, success: bool, changes_summary: str
    ) -> str:
        """Build context string about the task for the docs agent."""
        lines = [
            "## Current Project State",
            "",
            f"Task {task.id} ({'succeeded' if success else 'failed'})",
            f"Domain: {self.domain or 'general'}",
            f"Has components: {self._has_components}",
            "",
            "## Recent Changes",
            changes_summary,
            "",
        ]

        if task.review_feedback:
            lines.extend(
                [
                    "## Review Feedback",
                    *[f"- {feedback}" for feedback in task.review_feedback[-3:]],
                    "",
                ]
            )

        if self.docs_dir.exists():
            lines.append("## Existing Documentation Files")
            for doc_file in sorted(self.docs_dir.rglob("*.md")):
                rel_path = doc_file.relative_to(self.project_root)
                lines.append(f"- {rel_path}")

        return "\n".join(lines)

    def _identify_docs_to_update(self, task: Task, changes_summary: str) -> List[str]:
        """Identify which documentation files likely need updates."""
        docs_to_update = []
        combined_text = f"{task.description.lower()} {changes_summary.lower()}"

        # Always consider main docs
        docs_to_update.append("docs/README.md")

        # Architecture/design changes (only for component-based projects)
        if self._has_components:
            arch_keywords = ["architecture", "design", "structure", "refactor"]
            if any(kw in combined_text for kw in arch_keywords):
                docs_to_update.append("docs/architecture.md")

            # Component changes - route to docs/components/
            component_keywords = [
                "component",
                "module",
                "class",
                "service",
                "handler",
                "controller",
                "model",
            ]
            if any(kw in combined_text for kw in component_keywords):
                docs_to_update.append("docs/components/")

            # API changes
            api_keywords = ["api", "endpoint", "route", "request", "response"]
            if any(kw in combined_text for kw in api_keywords):
                docs_to_update.append("docs/api.md")

        # Research/data changes (for non-component projects)
        if not self._has_components:
            research_keywords = [
                "research",
                "analysis",
                "finding",
                "conclusion",
                "hypothesis",
            ]
            if any(kw in combined_text for kw in research_keywords):
                docs_to_update.append("docs/research.md")

            data_keywords = ["data", "dataset", "source", "collection", "preprocessing"]
            if any(kw in combined_text for kw in data_keywords):
                docs_to_update.append("docs/data.md")

        # Scripts (universal)
        script_keywords = ["script", "run", "execute", "command", ".py", ".sh"]
        if any(kw in combined_text for kw in script_keywords):
            docs_to_update.append("docs/scripts.md")

        # Troubleshooting (for failures)
        if (
            "error" in combined_text
            or "failed" in combined_text
            or not task.acceptance_criteria
        ):
            docs_to_update.append("docs/troubleshooting.md")

        return docs_to_update

    def _format_docs_list(self, docs_list: List[str]) -> str:
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
- Status: {"SUCCESS" if success else "FAILED"}
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
            model="sonnet",
            log_workspace=self.project_root / ".orchestrator"
            if (self.project_root / ".orchestrator").exists()
            else self.project_root,
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
        """Generate comprehensive documentation for the entire project."""
        self.initialize()

        if self._has_components:
            docs_structure = """1. **docs/README.md** - Overview, quick start, project structure
2. **docs/architecture.md** - System design, component relationships, key decisions
3. **docs/scripts.md** - All scripts, how to run them, what they do, expected output
4. **docs/api.md** - API endpoints, request/response formats (if applicable)
5. **docs/troubleshooting.md** - Common issues, error messages, solutions
6. **docs/components/** - Individual files for major components"""
        else:
            docs_structure = """1. **docs/README.md** - Overview, quick start, project structure
2. **docs/research.md** - Research methodology, approach, key findings
3. **docs/data.md** - Data sources, preprocessing, analysis
4. **docs/scripts.md** - All scripts, how to run them, what they do
5. **docs/troubleshooting.md** - Common issues, error messages, solutions"""

        instruction = f"""You are the documentation writer. Generate comprehensive documentation for this project.

## Project Domain
{self.domain or "general"} (has_components: {self._has_components})

## Your Task

Create/update complete documentation in the `docs/` directory:

{docs_structure}

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
            max_turns=30,
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
            f"Domain: {self.domain or 'general'}",
            f"Has components: {self._has_components}",
            "",
            "Analyze the codebase to understand:",
            "- Main entry points and how to run the project",
        ]

        if self._has_components:
            lines.append("- Key components and their relationships")
        else:
            lines.append("- Research methodology and data analysis approach")

        lines.extend(
            [
                "- External dependencies and requirements",
                "- Configuration files and environment variables",
                "- Testing strategy and how to run tests",
                "",
            ]
        )

        if self.docs_dir.exists():
            lines.append("## Existing Documentation")
            for doc_file in sorted(self.docs_dir.rglob("*.md")):
                lines.append(f"- {doc_file.relative_to(self.project_root)}")

        return "\n".join(lines)
