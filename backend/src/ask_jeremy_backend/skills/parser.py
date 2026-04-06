from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

from .models import SkillDefinition, SkillMetadata, SkillScope

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_LOCAL_LINK_RE = re.compile(r"\[[^\]]+\]\((?!https?://|app://|plugin://|file://)([^)\s]+)\)")


class SkillParser:
    def parse(
        self,
        skill_file: Path,
        scope: SkillScope,
        trusted: bool,
    ) -> SkillDefinition:
        raw = skill_file.read_text(encoding="utf-8")
        metadata, instructions = self._parse_frontmatter(raw)
        skill_dir = skill_file.parent
        references = tuple(self._extract_references(instructions, skill_dir))
        return SkillDefinition(
            id=self._build_id(scope, skill_dir),
            name=metadata.name,
            description=metadata.description,
            scope=scope,
            trusted=trusted,
            skill_dir=skill_dir,
            skill_file=skill_file,
            instructions=instructions.strip(),
            references=references,
        )

    def _parse_frontmatter(self, raw: str) -> tuple[SkillMetadata, str]:
        match = _FRONTMATTER_RE.match(raw)
        if match:
            frontmatter, body = match.groups()
            parsed = self._safe_yaml(frontmatter)
            name = self._as_text(parsed.get("name"))
            description = self._as_text(parsed.get("description"))
            if name and description:
                return SkillMetadata(name=name, description=description), body

        return self._fallback_metadata(raw)

    def _fallback_metadata(self, raw: str) -> tuple[SkillMetadata, str]:
        lines = raw.splitlines()
        title = "Unknown Skill"
        description = "Skill metadata could not be parsed."
        body_start = 0

        for index, line in enumerate(lines):
            stripped = line.strip()
            lowered = stripped.lower()
            if lowered.startswith("name:") and title == "Unknown Skill":
                candidate = stripped.split(":", 1)[1].strip()
                if candidate:
                    title = candidate
            if lowered.startswith("description:") and description == "Skill metadata could not be parsed.":
                candidate = stripped.split(":", 1)[1].strip()
                if candidate:
                    description = candidate
            if stripped.startswith("# "):
                body_start = index
                if title == "Unknown Skill":
                    title = stripped[2:].strip() or title
                break

        body = "\n".join(lines[body_start:]).strip() or raw.strip()
        return SkillMetadata(name=title, description=description), body

    def _safe_yaml(self, frontmatter: str) -> dict[str, object]:
        try:
            parsed = yaml.safe_load(frontmatter) or {}
        except yaml.YAMLError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _as_text(self, value: object) -> str | None:
        if isinstance(value, str):
            normalized = " ".join(value.split())
            return normalized or None
        return None

    def _extract_references(self, instructions: str, skill_dir: Path) -> list[Path]:
        references: list[Path] = []
        seen: set[Path] = set()
        for relative_path in _LOCAL_LINK_RE.findall(instructions):
            candidate = (skill_dir / relative_path).resolve()
            try:
                candidate.relative_to(skill_dir.resolve())
            except ValueError:
                continue
            if candidate.exists() and candidate not in seen:
                seen.add(candidate)
                references.append(candidate)
        return references

    def _build_id(self, scope: SkillScope, skill_dir: Path) -> str:
        digest = hashlib.sha1(str(skill_dir).encode("utf-8")).hexdigest()[:12]
        return f"{scope}:{digest}"
