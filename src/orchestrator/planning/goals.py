"""GOALS.md parser and validator."""

import re
from pathlib import Path
from typing import List, Optional, Dict
from ..models import Goal, GoalTier


class GoalsManager:
    def __init__(self, goals_path: Path = Path(".orchestrator/current/GOALS.md")):
        self.goals_path = goals_path
        self._goals: List[Goal] = []
        if self.goals_path.exists():
            self._load()

    def _load(self) -> None:
        """Parse GOALS.md into Goal objects."""
        content = self.goals_path.read_text()

        # Parse core success criteria
        core_section = self._extract_section(content, "Core Success Criteria")
        for item in self._parse_numbered_list(core_section):
            goal = Goal(
                description=item["title"],
                measurable_criteria=item.get("measurable", ""),
                tier=GoalTier.CORE,
                is_negotiable=False
            )
            self._goals.append(goal)

        # Parse nice-to-haves
        nice_section = self._extract_section(content, "Nice-to-Have")
        for item in self._parse_bulleted_list(nice_section):
            goal = Goal(
                description=item,
                measurable_criteria="",
                tier=GoalTier.NICE_TO_HAVE,
                is_negotiable=True
            )
            self._goals.append(goal)

    def _extract_section(self, content: str, header: str) -> str:
        """Extract content between headers."""
        pattern = rf"## {header}.*?\n(.*?)(?=\n## |\Z)"
        match = re.search(pattern, content, re.DOTALL)
        return match.group(1) if match else ""

    def _parse_numbered_list(self, text: str) -> List[Dict[str, str]]:
        """Parse numbered list with sub-bullets."""
        items = []
        lines = text.split("\n")
        current_item = None

        for line in lines:
            line = line.strip()
            if re.match(r"^\d+\.", line):
                if current_item:
                    items.append(current_item)
                # Extract title (removing ** markdown)
                title = re.sub(r"^\d+\.\s+\*\*(.+?)\*\*", r"\1", line)
                title = re.sub(r"^\d+\.\s+", "", line)  # Fallback
                current_item = {"title": title}
            elif line.startswith("- Measurable:") and current_item:
                current_item["measurable"] = line.replace("- Measurable:", "").strip()

        if current_item:
            items.append(current_item)

        return items

    def _parse_bulleted_list(self, text: str) -> List[str]:
        """Parse simple bulleted list."""
        return [
            line.strip("- ").strip()
            for line in text.split("\n")
            if line.strip().startswith("-")
        ]

    @property
    def core_goals(self) -> List[Goal]:
        return [g for g in self._goals if g.tier == GoalTier.CORE]

    @property
    def all_goals(self) -> List[Goal]:
        return self._goals

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        return next((g for g in self._goals if g.id == goal_id), None)
