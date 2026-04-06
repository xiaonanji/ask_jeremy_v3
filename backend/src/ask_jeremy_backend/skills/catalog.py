from __future__ import annotations

from threading import Lock

from ..config import Settings
from .discovery import SkillDiscoveryService, SkillRoot
from .models import SkillDefinition


class SkillCatalog:
    def __init__(self, settings: Settings, discovery: SkillDiscoveryService) -> None:
        self.settings = settings
        self.discovery = discovery
        self._lock = Lock()
        self._skills_by_id: dict[str, SkillDefinition] = {}
        self.refresh()

    def refresh(self) -> list[SkillDefinition]:
        with self._lock:
            roots = self._roots()
            skills = self.discovery.discover(roots)
            self._skills_by_id = {skill.id: skill for skill in skills}
            return list(self._skills_by_id.values())

    def list_skills(self) -> list[SkillDefinition]:
        return self.refresh()

    def get(self, skill_id: str) -> SkillDefinition | None:
        self.refresh()
        return self._skills_by_id.get(skill_id)

    def get_by_name(self, name: str) -> SkillDefinition | None:
        normalized = name.strip().lower()
        if not normalized:
            return None
        self.refresh()
        return next(
            (skill for skill in self._skills_by_id.values() if skill.name.strip().lower() == normalized),
            None,
        )

    def _roots(self) -> list[SkillRoot]:
        roots: list[SkillRoot] = []
        if self.settings.enable_project_skills:
            roots.append(
                SkillRoot(
                    path=self.settings.project_skill_root,
                    scope="project",
                    trusted=self.settings.trust_project_skills,
                )
            )
        if self.settings.enable_user_skills:
            roots.append(
                SkillRoot(
                    path=self.settings.user_skill_root,
                    scope="user",
                    trusted=True,
                )
            )
        return roots
