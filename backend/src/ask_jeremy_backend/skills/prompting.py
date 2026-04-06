from __future__ import annotations

from .models import ActivatedSkill, SkillDefinition


class SkillPromptRenderer:
    def render_catalog(self, skills: list[SkillDefinition]) -> str:
        if not skills:
            return "No skills are currently available."

        lines = ["Available skills:"]
        for skill in skills:
            trust = "trusted" if skill.trusted else "requires explicit activation"
            lines.append(f"- {skill.name}: {skill.description} ({skill.scope}, {trust})")
        return "\n".join(lines)

    def render_selection_catalog(self, skills: list[SkillDefinition]) -> str:
        if not skills:
            return "No skills available."

        lines = []
        for skill in skills:
            trust = "trusted" if skill.trusted else "requires explicit user intent"
            lines.append(
                f"- id={skill.id} | name={skill.name} | description={skill.description} "
                f"| scope={skill.scope} | trust={trust}"
            )
        return "\n".join(lines)

    def render_selection_instructions(self) -> str:
        return (
            "You select which skills, if any, should be activated for the current user message.\n"
            "Choose only skills that are clearly relevant to the user's request.\n"
            "It is valid to choose no skills.\n"
            "Do not activate untrusted project skills unless the user clearly asks for that skill or its domain.\n"
            "Return strict JSON with this shape only: {\"skill_ids\": [\"skill-id-1\", \"skill-id-2\"]}."
        )

    def render_active_instructions(self, skills: list[ActivatedSkill]) -> str:
        if not skills:
            return ""

        sections = ["Activated skills:"]
        for skill in skills:
            sections.append(f"## {skill.name}")
            sections.append(skill.instructions)
        return "\n\n".join(sections).strip()
