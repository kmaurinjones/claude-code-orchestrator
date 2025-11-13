"""Changelog manager with semantic versioning."""

import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from enum import Enum


class ChangeType(str, Enum):
    """Types of changes that can be logged."""
    ADDED = "Added"
    CHANGED = "Changed"
    FIXED = "Fixed"
    REMOVED = "Removed"
    ATTEMPTED = "Attempted"  # For failed attempts
    DEPRECATED = "Deprecated"
    SECURITY = "Security"


class VersionBump(str, Enum):
    """Semantic version bump types."""
    MAJOR = "major"  # Breaking changes
    MINOR = "minor"  # New features, backward compatible
    PATCH = "patch"  # Bug fixes, minor changes


class ChangelogManager:
    """Manages CHANGELOG.md with semantic versioning."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.changelog_file = project_root / "CHANGELOG.md"

    def initialize(self) -> None:
        """Create initial CHANGELOG.md if it doesn't exist."""
        if self.changelog_file.exists():
            return

        template = """# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - {}

### Added
- Initial project setup

""".format(datetime.now().strftime("%Y-%m-%d"))

        self.changelog_file.write_text(template)

    def get_current_version(self) -> Tuple[int, int, int]:
        """
        Extract current version from CHANGELOG.md.
        Returns (major, minor, patch) tuple.
        """
        if not self.changelog_file.exists():
            return (0, 1, 0)

        content = self.changelog_file.read_text()

        # Find first version header like ## [1.2.3]
        match = re.search(r'##\s+\[(\d+)\.(\d+)\.(\d+)\]', content)

        if match:
            return (int(match.group(1)), int(match.group(2)), int(match.group(3)))

        return (0, 1, 0)

    def bump_version(self, bump_type: VersionBump) -> Tuple[int, int, int]:
        """
        Bump version according to semantic versioning.
        Returns new (major, minor, patch) tuple.
        """
        major, minor, patch = self.get_current_version()

        if bump_type == VersionBump.MAJOR:
            return (major + 1, 0, 0)
        elif bump_type == VersionBump.MINOR:
            return (major, minor + 1, 0)
        else:  # PATCH
            return (major, minor, patch + 1)

    def add_entry(
        self,
        change_type: ChangeType,
        description: str,
        bump_type: Optional[VersionBump] = None,
        task_id: Optional[str] = None,
    ) -> str:
        """
        Add a changelog entry.

        Args:
            change_type: Type of change (Added, Changed, etc.)
            description: Description of the change
            bump_type: How to bump version (if None, uses smart default)
            task_id: Optional task ID reference

        Returns:
            New version string
        """
        if not self.changelog_file.exists():
            self.initialize()

        # Auto-determine bump type if not provided
        if bump_type is None:
            bump_type = self._infer_bump_type(change_type)

        # Get new version
        major, minor, patch = self.bump_version(bump_type)
        new_version = f"{major}.{minor}.{patch}"
        today = datetime.now().strftime("%Y-%m-%d")

        # Format description with task reference
        formatted_desc = description
        if task_id:
            formatted_desc = f"{description} ({task_id})"

        # Read current changelog
        content = self.changelog_file.read_text()

        # Create new version section
        new_section = f"""## [{new_version}] - {today}

### {change_type.value}
- {formatted_desc}

"""

        # Insert after "## [Unreleased]" section
        unreleased_pattern = r'(## \[Unreleased\]\s*\n)'

        if re.search(unreleased_pattern, content):
            # Insert after Unreleased section
            updated_content = re.sub(
                unreleased_pattern,
                f"\\1\n{new_section}",
                content,
                count=1
            )
        else:
            # Fallback: insert at top after header
            lines = content.split('\n')
            # Find where to insert (after main header and format description)
            insert_idx = 0
            for i, line in enumerate(lines):
                if line.startswith('## ['):
                    insert_idx = i
                    break

            if insert_idx > 0:
                lines.insert(insert_idx, new_section.rstrip())
                updated_content = '\n'.join(lines)
            else:
                # Just append to end
                updated_content = content + "\n" + new_section

        self.changelog_file.write_text(updated_content)
        return new_version

    def add_to_existing_version(
        self,
        change_type: ChangeType,
        description: str,
        task_id: Optional[str] = None,
    ) -> None:
        """
        Add entry to most recent version without bumping version.
        Useful for accumulating changes before releasing.
        """
        if not self.changelog_file.exists():
            self.initialize()

        content = self.changelog_file.read_text()

        # Format description
        formatted_desc = description
        if task_id:
            formatted_desc = f"{description} ({task_id})"

        # Find the most recent version section
        version_pattern = r'(## \[\d+\.\d+\.\d+\][^\n]*\n)'
        match = re.search(version_pattern, content)

        if not match:
            # No version yet, add one
            self.add_entry(change_type, description, task_id=task_id)
            return

        # Find or create the change type section
        section_header = f"### {change_type.value}"

        # Extract content after version header
        version_start = match.end()
        next_version = re.search(r'## \[', content[version_start:])
        version_end = version_start + next_version.start() if next_version else len(content)

        version_content = content[version_start:version_end]

        # Check if section exists
        if section_header in version_content:
            # Add to existing section
            section_pattern = f"({re.escape(section_header)}\n)"
            updated_section = f"\\1- {formatted_desc}\n"
            version_content = re.sub(section_pattern, updated_section, version_content, count=1)
        else:
            # Add new section at beginning of version
            version_content = f"\n{section_header}\n- {formatted_desc}\n" + version_content

        # Reconstruct content
        updated_content = content[:version_start] + version_content + content[version_end:]
        self.changelog_file.write_text(updated_content)

    def _infer_bump_type(self, change_type: ChangeType) -> VersionBump:
        """Infer semantic version bump from change type."""
        if change_type in (ChangeType.REMOVED, ChangeType.DEPRECATED):
            return VersionBump.MAJOR
        elif change_type in (ChangeType.ADDED, ChangeType.CHANGED):
            return VersionBump.MINOR
        else:  # FIXED, SECURITY, ATTEMPTED
            return VersionBump.PATCH

    def get_unreleased_changes(self) -> List[str]:
        """Get list of changes in Unreleased section."""
        if not self.changelog_file.exists():
            return []

        content = self.changelog_file.read_text()

        # Extract Unreleased section
        unreleased_match = re.search(
            r'## \[Unreleased\](.*?)(?=## \[|\Z)',
            content,
            re.DOTALL
        )

        if not unreleased_match:
            return []

        unreleased_content = unreleased_match.group(1)

        # Extract bullet points
        changes = re.findall(r'^- (.+)$', unreleased_content, re.MULTILINE)
        return changes
