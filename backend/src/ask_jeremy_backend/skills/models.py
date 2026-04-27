from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


SkillScope = Literal["project", "user"]


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str


@dataclass(frozen=True)
class SkillDefinition:
    id: str
    name: str
    description: str
    scope: SkillScope
    trusted: bool
    skill_dir: Path
    skill_file: Path
    instructions: str
    references: tuple[Path, ...] = field(default_factory=tuple)
    reference_path_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ActivatedSkill:
    id: str
    name: str
    scope: SkillScope
    trusted: bool
    instructions: str
