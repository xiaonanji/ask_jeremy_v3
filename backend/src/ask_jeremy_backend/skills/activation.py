from __future__ import annotations

from .catalog import SkillCatalog
from .models import ActivatedSkill, SkillDefinition


class SkillActivationManager:
    def __init__(self, catalog: SkillCatalog, max_auto_activated_skills: int) -> None:
        self.catalog = catalog
        self.max_auto_activated_skills = max_auto_activated_skills

    def activate_by_ids(self, skill_ids: list[str]) -> list[ActivatedSkill]:
        selected_ids: list[str] = []
        seen: set[str] = set()
        for skill_id in skill_ids:
            normalized = skill_id.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            selected_ids.append(normalized)
            if len(selected_ids) >= self.max_auto_activated_skills:
                break

        return self.hydrate(selected_ids)

    def hydrate(self, skill_ids: list[str]) -> list[ActivatedSkill]:
        hydrated: list[ActivatedSkill] = []
        for skill_id in skill_ids:
            skill = self.catalog.get(skill_id)
            if skill is None:
                continue
            hydrated.append(self._activate(skill))
        return hydrated

    def _activate(self, skill: SkillDefinition) -> ActivatedSkill:
        return ActivatedSkill(
            id=skill.id,
            name=skill.name,
            scope=skill.scope,
            trusted=skill.trusted,
            instructions=skill.instructions,
        )
