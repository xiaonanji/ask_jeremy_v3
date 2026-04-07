from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import subprocess
import sys
import json
from pathlib import Path

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from .artifacts import collect_artifacts, session_artifact_root, snapshot_artifacts
from .config import Settings
from .database import (
    DatabaseConfigurationError,
    DatabaseConnectorError,
    QueryValidationError,
    SqlQueryExecutor,
)

_MAX_OUTPUT_CHARS = 8_000


@dataclass(frozen=True)
class SqlToolError:
    error_type: str
    recoverable: bool
    message: str


class LocalToolRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sql_executor = SqlQueryExecutor(settings)

    def build(self) -> list:
        settings = self.settings
        sql_executor = self.sql_executor

        @tool
        def run_shell_command(
            command: str,
            workdir: str | None = None,
            timeout_seconds: int | None = None,
        ) -> str:
            """Run a local shell command. Use this for file search, repository inspection, and calling local CLIs. Prefer read-only commands unless the user explicitly asked to modify files."""
            result = _run_process(
                args=_shell_invocation(command),
                settings=settings,
                workdir=workdir,
                timeout_seconds=timeout_seconds,
            )
            return _format_process_result(result)

        @tool
        def run_python_script(
            script: str,
            config: RunnableConfig,
            workdir: str | None = None,
            timeout_seconds: int | None = None,
        ) -> str:
            """Run inline Python using the backend interpreter. Use this for quick structured parsing, calculations, and small local inspections. Save generated charts or files into the session artifacts directory exposed as the SESSION_ARTIFACTS_PATH environment variable. The tool returns JSON with exit_code, stdout, stderr, and detected artifacts."""
            session_id = str(config.get("configurable", {}).get("thread_id", "")).strip()
            artifact_root = session_artifact_root(settings.session_root, session_id)
            before_snapshot = snapshot_artifacts(artifact_root)
            result = _run_process(
                args=[sys.executable, "-c", script],
                settings=settings,
                workdir=workdir,
                timeout_seconds=timeout_seconds,
                session_id=session_id or None,
                artifact_root=artifact_root,
            )
            artifacts = collect_artifacts(artifact_root, before_snapshot)
            return json.dumps(
                {
                    "exit_code": result["exit_code"],
                    "ok": result["exit_code"] == 0,
                    "working_directory": result["working_directory"],
                    "stdout": result["stdout"],
                    "stderr": result["stderr"],
                    "artifacts_dir": str(artifact_root) if artifact_root is not None else None,
                    "artifacts": [asdict(item) for item in artifacts],
                },
                indent=2,
            )

        @tool
        def execute_sql_query(
            query: str,
            config: RunnableConfig,
        ) -> str:
            """Execute a read-only SQL query against the database backend configured for the current session and save the materialized result set to the active session's artifacts folder. Supported session backends: sqlite, snowflake. Use explicit projections and filters whenever possible."""
            session_id = str(config.get("configurable", {}).get("thread_id", "")).strip()
            if not session_id:
                return json.dumps(
                    {
                        "exit_code": 1,
                        "ok": False,
                        "error_type": "runtime_error",
                        "recoverable": False,
                        "message": "Missing session id for SQL execution.",
                    },
                    indent=2,
                )

            try:
                result = sql_executor.execute_query(
                    query=query,
                    session_id=session_id,
                )
            except DatabaseConnectorError as exc:
                error = _classify_sql_tool_error(exc)
                return json.dumps(
                    {
                        "exit_code": 1,
                        "ok": False,
                        **asdict(error),
                    },
                    indent=2,
                )

            return json.dumps(
                {
                    "exit_code": 0,
                    "ok": True,
                    "database": result.database,
                    "artifact_id": result.artifact_id,
                    "artifact_dir": str(result.artifact_dir),
                    "json_path": str(result.json_path),
                    "csv_path": str(result.csv_path),
                    "row_count": result.row_count,
                    "row_limit": settings.sql_query_max_rows,
                    "columns": result.columns,
                    "created_at": result.created_at.isoformat(),
                },
                indent=2,
            )

        return [run_shell_command, run_python_script, execute_sql_query]


def _run_process(
    *,
    args: list[str],
    settings: Settings,
    workdir: str | None,
    timeout_seconds: int | None,
    session_id: str | None = None,
    artifact_root: Path | None = None,
) -> dict[str, object]:
    cwd = _resolve_workdir(workdir, settings.project_root)
    if cwd is None:
        target = workdir if workdir else str(settings.project_root)
        return {
            "exit_code": 1,
            "working_directory": target,
            "stdout": "",
            "stderr": f"Working directory does not exist or is not a directory: {target}",
        }

    timeout = _resolve_timeout(timeout_seconds, settings.tool_timeout_seconds)
    env = os.environ.copy()
    env.setdefault("PROJECT_ROOT", str(settings.project_root))
    if settings.person_wiki_root is not None:
        env.setdefault("PERSON_WIKI_ROOT", str(settings.person_wiki_root))
    if session_id:
        env.setdefault("SESSION_ID", session_id)
    if artifact_root is not None:
        artifact_root.mkdir(parents=True, exist_ok=True)
        env.setdefault("SESSION_ARTIFACTS_PATH", str(artifact_root))

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
        return {
            "exit_code": 124,
            "working_directory": cwd,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds.",
        }
    except OSError as exc:
        return {
            "exit_code": 1,
            "working_directory": cwd,
            "stdout": "",
            "stderr": f"Command failed to start: {exc}",
        }

    return {
        "exit_code": completed.returncode,
        "working_directory": cwd,
        "stdout": _truncate_output(completed.stdout),
        "stderr": _truncate_output(completed.stderr),
    }


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


def _classify_sql_tool_error(exc: DatabaseConnectorError) -> SqlToolError:
    message = str(exc)
    lowered = message.lower()

    if isinstance(exc, DatabaseConfigurationError):
        return SqlToolError(
            error_type="database_connection_error",
            recoverable=False,
            message=message,
        )

    if isinstance(exc, QueryValidationError):
        if "syntax" in lowered:
            return SqlToolError(
                error_type="syntax_error",
                recoverable=True,
                message=message,
            )
        return SqlToolError(
            error_type="validation_error",
            recoverable=False,
            message=message,
        )

    syntax_markers = (
        "syntax error",
        "parse error",
        "unexpected",
        "incorrect syntax",
    )
    if any(marker in lowered for marker in syntax_markers):
        return SqlToolError(
            error_type="syntax_error",
            recoverable=True,
            message=message,
        )

    connection_markers = (
        "could not connect",
        "connection",
        "login",
        "network",
        "authenticator",
        "authentication",
        "timed out",
        "timeout",
    )
    if any(marker in lowered for marker in connection_markers):
        return SqlToolError(
            error_type="database_connection_error",
            recoverable=False,
            message=message,
        )

    return SqlToolError(
        error_type="execution_error",
        recoverable=False,
        message=message,
    )


def _format_process_result(result: dict[str, object]) -> str:
    stdout = str(result.get("stdout", "")).strip()
    stderr = str(result.get("stderr", "")).strip()
    sections = [
        f"Exit code: {result.get('exit_code', 1)}",
        f"Working directory: {result.get('working_directory', '')}",
    ]
    if stdout:
        sections.append(f"STDOUT:\n{stdout}")
    if stderr:
        sections.append(f"STDERR:\n{stderr}")
    if not stdout and not stderr:
        sections.append("No output.")
    return "\n\n".join(sections)
