from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timezone, datetime
import os
import subprocess
import sys
import json
from pathlib import Path

from langchain_core.tools import tool
from langchain_core.runnables.config import ensure_config

from .analysis import (
    AnalysisArtifactError,
    load_analysis_result,
    raw_sql_artifact_paths,
    validate_analysis_result,
)
from .artifacts import collect_artifacts, session_artifact_root, snapshot_artifacts
from .config import Settings
from .database import (
    DatabaseConfigurationError,
    DatabaseConnectorError,
    QueryValidationError,
    SqlQueryExecutor,
    WarehouseTablePolicyValidationError,
)
from .working_memory import make_memory_update

_MAX_OUTPUT_CHARS = 8_000


def _session_id() -> str:
    """Read the LangGraph thread_id from LangChain's ambient config context."""
    config = ensure_config()
    return str(config.get("configurable", {}).get("thread_id", "")).strip()


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
            workdir: str | None = None,
            timeout_seconds: int | None = None,
        ) -> str:
            """Run inline Python using the backend interpreter. Use this for quick structured parsing, calculations, and small local inspections. Save generated charts or files into the session artifacts directory exposed as the SESSION_ARTIFACTS_PATH environment variable. The tool returns JSON with exit_code, stdout, stderr, and detected artifacts."""
            session_id = _session_id()
            artifact_root = session_artifact_root(settings.session_root, session_id)
            before_snapshot = snapshot_artifacts(artifact_root)
            script_path = _write_python_code_artifact(
                artifact_root=artifact_root,
                script=script,
            )
            run_args = (
                [sys.executable, str(script_path)]
                if script_path is not None
                else [sys.executable, "-c", script]
            )
            result = _run_process(
                args=run_args,
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
        ) -> str:
            """Execute a SQL statement against the configured session database and save the raw result set as an internal artifact. Allowed statements: SELECT, WITH (CTEs), DESCRIBE/DESC, EXPLAIN, and CREATE [OR REPLACE] TEMPORARY TABLE (for storing intermediate results). Non-temporary CREATE statements and other data-modifying statements (INSERT, UPDATE, DELETE, DROP, ALTER, etc.) are prohibited. For Snowflake, this tool only allows tables explicitly paired with reference files in the snowflake-datawarehouse skill; SHOW/LIST and warehouse catalog exploration are blocked. Do not rely on this tool alone for user-facing answers; follow it with `run_analysis_script` and `read_analysis_result`."""
            session_id = _session_id()
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
                    "row_count": result.row_count,
                    "row_limit": settings.sql_query_max_rows,
                    "truncated": result.truncated,
                    "columns": result.columns,
                    "created_at": result.created_at.isoformat(),
                },
                indent=2,
            )

        @tool
        def run_analysis_script(
            raw_artifact_id: str,
            script: str,
            timeout_seconds: int | None = None,
        ) -> str:
            """Write and run a Python analysis script against a previously materialized SQL artifact. The script reads raw data from the provided environment variables and writes a structured JSON object to ANALYSIS_OUTPUT_PATH. Do NOT print raw rows to stdout — that output is not seen by the model. Available input env vars: RAW_SQL_RESULT_JSON_PATH, RAW_SQL_RESULT_CSV_PATH, RAW_ARTIFACT_JSON_PATH, RAW_ARTIFACT_CSV_PATH, RAW_RESULT_JSON_PATH, RAW_RESULT_CSV_PATH, RAW_ARTIFACT_PATH, RAW_ARTIFACT_DIR. Allowed top-level output keys: summary, metrics, findings, evidence, caveats, uncertainty, needs_user_input, follow_up_question, allowed_mentions, table. Key guidance: (1) If the user asks for a list, ranking, or set of records (e.g. 'show all schools ranked', 'give me the full table'), produce the full result in the 'table' field — do not summarize or truncate it. Set 'table' to a list of row dicts (e.g. [{"rank": 1, "school": "X", "score": 95}]) or an object with 'headers' (list of strings) and 'rows' (list of lists). Supports up to 500 rows and 20 columns. (2) If the user asks for a summary, aggregate, or insight, use metrics/findings/evidence instead. (3) Put scalar numbers in metrics or evidence, not as bare top-level keys. (4) If the SQL artifact was truncated, disclose it in caveats. On success, this tool returns the validated analysis result inline so the model answers directly from it."""
            session_id = _session_id()
            if not session_id:
                return json.dumps(
                    {
                        "exit_code": 1,
                        "ok": False,
                        "error_type": "runtime_error",
                        "recoverable": False,
                        "message": "Missing session id for analysis execution.",
                    },
                    indent=2,
                )

            try:
                raw_json_path, raw_csv_path = raw_sql_artifact_paths(
                    settings,
                    session_id,
                    raw_artifact_id,
                )
            except AnalysisArtifactError as exc:
                return json.dumps(
                    {
                        "exit_code": 1,
                        "ok": False,
                        "error_type": "analysis_input_error",
                        "recoverable": False,
                        "message": str(exc),
                    },
                    indent=2,
                )

            artifact_root = session_artifact_root(settings.session_root, session_id)
            if artifact_root is None:
                return json.dumps(
                    {
                        "exit_code": 1,
                        "ok": False,
                        "error_type": "runtime_error",
                        "recoverable": False,
                        "message": "Missing session artifact root for analysis execution.",
                    },
                    indent=2,
                )

            now = datetime.now(timezone.utc)
            analysis_id = f"analysis_{now.strftime('%Y%m%dT%H%M%SZ')}_{os.urandom(4).hex()}"
            analysis_dir = artifact_root / "analysis" / analysis_id
            analysis_dir.mkdir(parents=True, exist_ok=False)
            script_path = analysis_dir / "analysis.py"
            output_path = analysis_dir / "analysis_result.json"
            stdout_path = analysis_dir / "stdout.txt"
            stderr_path = analysis_dir / "stderr.txt"
            script_path.write_text(script, encoding="utf-8")
            _write_python_code_artifact(
                artifact_root=artifact_root,
                script=script,
                filename=f"{analysis_id}.py",
                header=(
                    f"# Analysis {analysis_id} run against SQL artifact {raw_artifact_id}\n\n"
                ),
            )

            result = _run_process(
                args=[sys.executable, str(script_path)],
                settings=settings,
                workdir=str(analysis_dir),
                timeout_seconds=timeout_seconds,
                session_id=session_id,
                artifact_root=artifact_root,
                extra_env={
                    "RAW_SQL_RESULT_JSON_PATH": str(raw_json_path),
                    "RAW_SQL_RESULT_CSV_PATH": str(raw_csv_path),
                    "RAW_ARTIFACT_JSON_PATH": str(raw_json_path),
                    "RAW_ARTIFACT_CSV_PATH": str(raw_csv_path),
                    "RAW_RESULT_JSON_PATH": str(raw_json_path),
                    "RAW_RESULT_CSV_PATH": str(raw_csv_path),
                    "RAW_ARTIFACT_PATH": str(raw_json_path),
                    "RAW_ARTIFACT_DIR": str(raw_json_path.parent),
                    "ANALYSIS_ARTIFACT_DIR": str(analysis_dir),
                    "ANALYSIS_OUTPUT_PATH": str(output_path),
                },
            )
            stdout = str(result.get("stdout", ""))
            stderr = str(result.get("stderr", ""))
            stdout_path.write_text(stdout, encoding="utf-8")
            stderr_path.write_text(stderr, encoding="utf-8")

            if result["exit_code"] != 0:
                return json.dumps(
                    {
                        "exit_code": result["exit_code"],
                        "ok": False,
                        "error_type": "analysis_execution_error",
                        "recoverable": True,
                        "message": "Analysis script failed. Inspect stdout/stderr, amend the script, and retry.",
                        "analysis_artifact_id": analysis_id,
                        "artifact_dir": str(analysis_dir),
                        "script_path": str(script_path),
                        "stdout_path": str(stdout_path),
                        "stderr_path": str(stderr_path),
                    },
                    indent=2,
                )

            try:
                analysis_result = load_analysis_result(settings, session_id, analysis_id)
            except AnalysisArtifactError as exc:
                return json.dumps(
                    {
                        "exit_code": 1,
                        "ok": False,
                        "error_type": "analysis_output_error",
                        "recoverable": True,
                        "message": (
                            f"{exc} Allowed top-level keys are: "
                            "summary, metrics, findings, evidence, caveats, uncertainty, "
                            "needs_user_input, follow_up_question, allowed_mentions, table."
                        ),
                        "analysis_artifact_id": analysis_id,
                        "artifact_dir": str(analysis_dir),
                        "script_path": str(script_path),
                        "stdout_path": str(stdout_path),
                        "stderr_path": str(stderr_path),
                    },
                    indent=2,
                )

            analysis_result = _attach_sql_truncation_signal(
                raw_json_path=raw_json_path,
                analysis_result=analysis_result,
            )
            analysis_result = validate_analysis_result(analysis_result)
            output_path.write_text(json.dumps(analysis_result, indent=2), encoding="utf-8")

            return json.dumps(
                {
                    "exit_code": 0,
                    "ok": True,
                    "raw_artifact_id": raw_artifact_id,
                    "analysis_artifact_id": analysis_id,
                    "artifact_dir": str(analysis_dir),
                    "script_path": str(script_path),
                    "output_path": str(output_path),
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "result": analysis_result,
                },
                indent=2,
            )

        @tool
        def read_analysis_result(
            analysis_artifact_id: str,
        ) -> str:
            """Read a previously validated analysis result. This returns only bounded analysis JSON, never raw SQL rows."""
            session_id = _session_id()
            if not session_id:
                return json.dumps(
                    {
                        "exit_code": 1,
                        "ok": False,
                        "error_type": "runtime_error",
                        "recoverable": False,
                        "message": "Missing session id for analysis result reading.",
                    },
                    indent=2,
                )

            try:
                payload = load_analysis_result(settings, session_id, analysis_artifact_id)
            except AnalysisArtifactError as exc:
                return json.dumps(
                    {
                        "exit_code": 1,
                        "ok": False,
                        "error_type": "analysis_output_error",
                        "recoverable": False,
                        "message": str(exc),
                        "analysis_artifact_id": analysis_artifact_id,
                    },
                    indent=2,
                )

            return json.dumps(
                {
                    "exit_code": 0,
                    "ok": True,
                    "analysis_artifact_id": analysis_artifact_id,
                    "result": payload,
                },
                indent=2,
            )

        @tool
        def pin_working_memory(
            section: str,
            content: str,
            source: str | None = None,
            confidence: str = "medium",
            mode: str = "append",
        ) -> str:
            """Pin critical task information so it survives long tool loops and conversation compaction. Use this when you learn durable information needed later in the same task: business rules, source summaries, warehouse mappings, failed attempts, blockers, open questions, current plan, or artifact notes. Valid sections: task_goal, loaded_sources, business_rules, warehouse_mapping, failed_attempts, open_questions, current_plan, artifacts, notes. `content` may be concise text or a JSON string. Use mode='replace' for current_plan or task_goal when replacing older content."""
            try:
                update = make_memory_update(
                    section=section,
                    content=content,
                    source=source,
                    confidence=confidence,
                    pinned_by="llm",
                    mode=mode,
                )
            except ValueError as exc:
                return json.dumps(
                    {
                        "exit_code": 1,
                        "ok": False,
                        "error_type": "working_memory_error",
                        "recoverable": True,
                        "message": str(exc),
                    },
                    indent=2,
                )

            return json.dumps(
                {
                    "exit_code": 0,
                    "ok": True,
                    "tool_name": "pin_working_memory",
                    "message": "Pinned information to task working memory.",
                    "memory_update": update,
                },
                indent=2,
            )

        @tool
        def load_skill_reference(
            file_path: str,
        ) -> str:
            """Load a reference file bundled inside a .agents/skills/ directory. Only use this for files that live within the skill directories themselves (e.g. schema docs shipped alongside a SKILL.md). Do NOT use this to read external files such as wiki pages, project files, or repositories — use run_shell_command for those instead."""
            target = Path(file_path).resolve()

            allowed_roots = [
                settings.project_skill_root.resolve(),
                settings.user_skill_root.resolve(),
            ]
            if not any(
                target == root or target.is_relative_to(root)
                for root in allowed_roots
                if root.exists()
            ):
                return json.dumps(
                    {
                        "ok": False,
                        "error_type": "permission_error",
                        "message": f"Path is not within a recognised skill directory: {file_path}",
                    },
                    indent=2,
                )

            if not target.exists():
                return json.dumps(
                    {
                        "ok": False,
                        "error_type": "file_not_found",
                        "message": f"File does not exist: {file_path}",
                    },
                    indent=2,
                )

            if not target.is_file():
                return json.dumps(
                    {
                        "ok": False,
                        "error_type": "invalid_path",
                        "message": f"Path is not a file: {file_path}",
                    },
                    indent=2,
                )

            try:
                content = target.read_text(encoding="utf-8")
            except Exception as exc:
                return json.dumps(
                    {
                        "ok": False,
                        "error_type": "read_error",
                        "message": str(exc),
                    },
                    indent=2,
                )

            max_chars = 50_000
            truncated = len(content) > max_chars
            if truncated:
                content = content[:max_chars]

            suffix = " (truncated)" if truncated else ""
            return json.dumps(
                {
                    "ok": True,
                    "message": f"Loaded {len(content)} chars from {target.name}{suffix}",
                    "file_path": str(target),
                    "content": content,
                    "truncated": truncated,
                },
                indent=2,
            )

        return [
            run_shell_command,
            run_python_script,
            execute_sql_query,
            run_analysis_script,
            read_analysis_result,
            pin_working_memory,
            load_skill_reference,
        ]


def _write_python_code_artifact(
    *,
    artifact_root: Path | None,
    script: str,
    filename: str | None = None,
    header: str | None = None,
) -> Path | None:
    if artifact_root is None:
        return None
    code_dir = artifact_root / "code" / "python"
    code_dir.mkdir(parents=True, exist_ok=True)
    if filename is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"script_{stamp}_{os.urandom(4).hex()}.py"
    target = code_dir / filename
    body = script if not header else f"{header}{script}"
    target.write_text(body, encoding="utf-8")
    return target


def _run_process(
    *,
    args: list[str],
    settings: Settings,
    workdir: str | None,
    timeout_seconds: int | None,
    session_id: str | None = None,
    artifact_root: Path | None = None,
    extra_env: dict[str, str] | None = None,
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
    if extra_env:
        env.update(extra_env)

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

    if isinstance(exc, WarehouseTablePolicyValidationError):
        return SqlToolError(
            error_type="warehouse_table_policy_error",
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


def _attach_sql_truncation_signal(
    *,
    raw_json_path: Path,
    analysis_result: dict[str, object],
) -> dict[str, object]:
    try:
        raw_payload = json.loads(raw_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return analysis_result
    if not isinstance(raw_payload, dict) or not raw_payload.get("truncated"):
        return analysis_result

    row_limit = raw_payload.get("row_limit")
    row_count = raw_payload.get("row_count")
    result = dict(analysis_result)
    metrics = dict(result.get("metrics", {}))
    metrics["sql_result_truncated"] = True
    if isinstance(row_limit, int):
        metrics["sql_row_limit"] = row_limit
    if isinstance(row_count, int):
        metrics["sql_materialized_row_count"] = row_count
    result["metrics"] = metrics

    caveats = list(result.get("caveats", []))
    truncation_note = (
        f"SQL materialization was truncated to the first {row_limit} rows for safety; "
        "do not generalize beyond that window."
        if isinstance(row_limit, int)
        else "SQL materialization was truncated for safety; do not generalize beyond the returned rows."
    )
    if truncation_note not in caveats:
        caveats.append(truncation_note)
    result["caveats"] = caveats

    evidence = list(result.get("evidence", []))
    if not any(
        isinstance(item, dict) and item.get("label") == "sql_result_truncated"
        for item in evidence
    ):
        evidence.append(
            {
                "label": "sql_result_truncated",
                "detail": "The SQL artifact was truncated during materialization.",
                "value": {
                    "truncated": True,
                    "row_limit": row_limit,
                    "materialized_row_count": row_count,
                },
            }
        )
    result["evidence"] = evidence
    return result
