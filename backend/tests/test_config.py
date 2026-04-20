from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ask_jeremy_backend.config import DEFAULT_SYSTEM_PROMPT, Settings


class SettingsPromptTests(unittest.TestCase):
    def test_resolved_system_prompt_loads_repo_jeremy_markdown_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "jeremy.md"
            prompt_path.write_text("Seasoned analyst prompt", encoding="utf-8")

            settings = Settings(
                _env_file=None,
                project_root=root,
            )

            self.assertEqual(settings.resolved_jeremy_prompt_path, prompt_path)
            self.assertEqual(settings.resolved_system_prompt, "Seasoned analyst prompt")

    def test_resolved_system_prompt_prefers_env_override_over_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "jeremy.md").write_text("Prompt from file", encoding="utf-8")

            settings = Settings(
                _env_file=None,
                project_root=root,
                system_prompt="Prompt from env",
            )

            self.assertEqual(settings.resolved_system_prompt, "Prompt from env")

    def test_resolved_system_prompt_falls_back_when_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            settings = Settings(
                _env_file=None,
                project_root=root,
            )

            self.assertEqual(settings.resolved_system_prompt, DEFAULT_SYSTEM_PROMPT)

    def test_relative_jeremy_prompt_path_is_resolved_from_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt_path = root / "prompts" / "jeremy.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("Prompt from nested file", encoding="utf-8")

            settings = Settings(
                _env_file=None,
                project_root=root,
                jeremy_prompt_path=Path("prompts/jeremy.md"),
            )

            self.assertEqual(settings.resolved_jeremy_prompt_path, prompt_path)
            self.assertEqual(settings.resolved_system_prompt, "Prompt from nested file")


if __name__ == "__main__":
    unittest.main()
