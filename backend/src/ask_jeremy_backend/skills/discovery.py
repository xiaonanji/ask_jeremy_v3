from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import SkillDefinition, SkillScope
from .parser import SkillParser


@dataclass(frozen=True)
class SkillRoot:
    path: Path
    scope: SkillScope
    trusted: bool


class SkillDiscoveryService:
    def __init__(self, parser: SkillParser) -> None:
        self.parser = parser

    def discover(self, roots: list[SkillRoot]) -> list[SkillDefinition]:
        discovered: dict[str, SkillDefinition] = {}

        for root in roots:
            if not root.path.exists():
                continue

            for skill_file in sorted(root.path.glob("*/SKILL.md")):
                try:
                    skill = self.parser.parse(
                        skill_file=skill_file,
                        scope=root.scope,
                        trusted=root.trusted,
                    )
                except OSError:
                    continue

                key = skill.name.strip().lower()
                if key not in discovered or root.scope == "project":
                    discovered[key] = skill

        return sorted(discovered.values(), key=lambda item: (item.name.lower(), item.scope))
