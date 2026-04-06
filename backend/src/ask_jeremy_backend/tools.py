from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from .config import Settings

_MAX_OUTPUT_CHARS = 8_000


class LocalToolRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build(self) -> list:
        settings = self.settings

        @tool
        def run_shell_command(
            command: str,
            workdir: str | None = None,
            timeout_seconds: int | None = None,
        ) -> str:
            """Run a local shell command. Use this for file search, repository inspection, and calling local CLIs. Prefer read-only commands unless the user explicitly asked to modify files."""
            return _run_process(
                args=_shell_invocation(command),
                settings=settings,
                workdir=workdir,
                timeout_seconds=timeout_seconds,
            )

        @tool
        def run_python_script(
            script: str,
            workdir: str | None = None,
            timeout_seconds: int | None = None,
        ) -> str:
            """Run inline Python using the backend interpreter. Use this for quick structured parsing, calculations, and small local inspections."""
            return _run_process(
                args=[sys.executable, "-c", script],
                settings=settings,
                workdir=workdir,
                timeout_seconds=timeout_seconds,
            )

        return [run_shell_command, run_python_script]


def _run_process(
    *,
    args: list[str],
    settings: Settings,
    workdir: str | None,
    timeout_seconds: int | None,
) -> str:
    cwd = _resolve_workdir(workdir, settings.project_root)
    if cwd is None:
        target = workdir if workdir else str(settings.project_root)
        return f"ERROR: Working directory does not exist or is not a directory: {target}"

    timeout = _resolve_timeout(timeout_seconds, settings.tool_timeout_seconds)
    env = os.environ.copy()
    env.setdefault("PROJECT_ROOT", str(settings.project_root))
    if settings.person_wiki_root is not None:
        env.setdefault("PERSON_WIKI_ROOT", str(settings.person_wiki_root))

    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return (
            f"Command timed out after {timeout} seconds.\n"
            f"Working directory: {cwd}"
        )
    except OSError as exc:
        return f"Command failed to start: {exc}"

    stdout = _truncate_output(completed.stdout)
    stderr = _truncate_output(completed.stderr)
    sections = [
        f"Exit code: {completed.returncode}",
        f"Working directory: {cwd}",
    ]
    if stdout:
        sections.append(f"STDOUT:\n{stdout}")
    if stderr:
        sections.append(f"STDERR:\n{stderr}")
    if not stdout and not stderr:
        sections.append("No output.")
    return "\n\n".join(sections)


def _resolve_workdir(workdir: str | None, default_workdir: Path) -> str | None:
    candidate = Path(workdir).expanduser() if workdir else default_workdir
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        return None
    if not resolved.is_dir():
        return None
    return str(resolved)


def _resolve_timeout(timeout_seconds: int | None, default_timeout: int) -> int:
    if timeout_seconds is None:
        return max(1, default_timeout)
    return max(1, min(timeout_seconds, default_timeout))


def _truncate_output(value: str) -> str:
    normalized = value.strip()
    if len(normalized) <= _MAX_OUTPUT_CHARS:
        return normalized
    return f"{normalized[:_MAX_OUTPUT_CHARS]}\n...[truncated]"


def _shell_invocation(command: str) -> list[str]:
    if os.name == "nt":
        return ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["/bin/bash", "-lc", command]
