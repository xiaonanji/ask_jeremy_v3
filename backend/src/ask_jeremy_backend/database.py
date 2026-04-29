from __future__ import annotations

import csv
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from .config import Settings
from .schemas import DatabaseBackend
from .warehouse_policy import (
    WarehouseTablePolicyError,
    validate_snowflake_table_policy,
)

_QUERY_TAG = "ask_jeremy_sql_connector"

_CREATE_TEMP_TABLE_RE = re.compile(
    r"^create\s+(or\s+replace\s+)?(temp|temporary)\s+table\s",
    re.IGNORECASE,
)


class DatabaseConnectorError(RuntimeError):
    """Base class for database connector failures."""


class DatabaseConfigurationError(DatabaseConnectorError):
    """Raised when a connector is requested without valid configuration."""


class QueryValidationError(DatabaseConnectorError):
    """Raised when a query violates the connector safety contract."""


class WarehouseTablePolicyValidationError(QueryValidationError):
    """Raised when Snowflake SQL uses a table outside the reference set."""


@dataclass(frozen=True)
class QueryArtifact:
    artifact_id: str
    database: DatabaseBackend
    query: str
    executed_query: str
    row_count: int
    truncated: bool
    columns: list[str]
    artifact_dir: Path
    json_path: Path
    csv_path: Path
    created_at: datetime


class SqlQueryExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute_query(
        self,
        *,
        query: str,
        session_id: str,
    ) -> QueryArtifact:
        normalized_database = self._session_database_backend(session_id)
        sanitized_query = _sanitize_query(query)
        executed_query = sanitized_query

        if normalized_database == "sqlite":
            columns, rows, truncated = self._execute_sqlite(executed_query)
        elif normalized_database == "snowflake":
            try:
                validate_snowflake_table_policy(
                    executed_query,
                    self.settings.project_skill_root,
                )
            except WarehouseTablePolicyError as exc:
                raise WarehouseTablePolicyValidationError(str(exc)) from exc
            columns, rows, truncated = self._execute_snowflake(executed_query)
        else:
            raise DatabaseConfigurationError(
                f"Unsupported database backend: {normalized_database!r}. "
                "Supported values are 'sqlite' and 'snowflake'."
            )

        created_at = datetime.now(timezone.utc)
        artifact_dir = self._artifact_dir_for(session_id, normalized_database, created_at)
        json_path = artifact_dir / "result.json"
        csv_path = artifact_dir / "result.csv"
        payload = {
            "artifact_id": artifact_dir.name,
            "database": normalized_database,
            "created_at": created_at.isoformat(),
            "row_count": len(rows),
            "row_limit": self.settings.sql_query_max_rows,
            "truncated": truncated,
            "columns": columns,
            "query": sanitized_query,
            "executed_query": executed_query,
            "rows": rows,
        }
        self._write_json(json_path, payload)
        self._write_csv(csv_path, columns, rows)
        self._write_sql_code_artifact(
            session_id=session_id,
            artifact_id=artifact_dir.name,
            database=normalized_database,
            created_at=created_at,
            executed_query=executed_query,
        )

        return QueryArtifact(
            artifact_id=artifact_dir.name,
            database=normalized_database,
            query=sanitized_query,
            executed_query=executed_query,
            row_count=len(rows),
            truncated=truncated,
            columns=columns,
            artifact_dir=artifact_dir,
            json_path=json_path,
            csv_path=csv_path,
            created_at=created_at,
        )

    def _execute_sqlite(self, query: str) -> tuple[list[str], list[dict[str, Any]], bool]:
        database_path = self.settings.sqlite_database_path
        if database_path is None:
            raise DatabaseConfigurationError(
                "SQLite execution is not configured. Set SQLITE_DATABASE_PATH in backend/.env."
            )

        resolved_path = self._resolve_configured_path(database_path)
        if not resolved_path.exists() or not resolved_path.is_file():
            raise DatabaseConfigurationError(
                f"Configured SQLite database was not found: {resolved_path}"
            )

        connection = sqlite3.connect(
            str(resolved_path),
            timeout=self.settings.sql_query_timeout_seconds,
        )
        connection.row_factory = sqlite3.Row
        started_at = monotonic()

        try:
            if not _CREATE_TEMP_TABLE_RE.match(query):
                connection.execute("PRAGMA query_only = ON")
            connection.set_progress_handler(
                lambda: int(
                    monotonic() - started_at > self.settings.sql_query_timeout_seconds
                ),
                1_000,
            )
            cursor = connection.execute(query)
            columns = [item[0] for item in (cursor.description or [])]
            truncated = False
            raw_rows = cursor.fetchmany(self.settings.sql_query_max_rows + 1)
            if len(raw_rows) > self.settings.sql_query_max_rows:
                truncated = True
                raw_rows = raw_rows[: self.settings.sql_query_max_rows]
            rows = [
                {
                    column: _to_json_value(row[column])
                    for column in columns
                }
                for row in raw_rows
            ]
            return columns, rows, truncated
        except sqlite3.Error as exc:
            if "interrupted" in str(exc).lower():
                raise DatabaseConnectorError(
                    "SQLite query exceeded the configured timeout."
                ) from exc
            raise DatabaseConnectorError(f"SQLite query failed: {exc}") from exc
        finally:
            connection.set_progress_handler(None, 0)
            connection.close()

    def _execute_snowflake(self, query: str) -> tuple[list[str], list[dict[str, Any]], bool]:
        connection_kwargs = self._snowflake_connection_kwargs()

        try:
            import snowflake.connector
        except ImportError as exc:
            raise DatabaseConfigurationError(
                "Snowflake execution requires the `snowflake-connector-python` package."
            ) from exc

        try:
            with snowflake.connector.connect(**connection_kwargs) as connection:
                cursor = connection.cursor()
                try:
                    cursor.execute(query, timeout=self.settings.sql_query_timeout_seconds)
                    columns = [item[0] for item in (cursor.description or [])]
                    truncated = False
                    raw_rows = cursor.fetchmany(self.settings.sql_query_max_rows + 1)
                    if len(raw_rows) > self.settings.sql_query_max_rows:
                        truncated = True
                        raw_rows = raw_rows[: self.settings.sql_query_max_rows]
                    rows = [
                        {
                            column: _to_json_value(value)
                            for column, value in zip(columns, record)
                        }
                        for record in raw_rows
                    ]
                    return columns, rows, truncated
                finally:
                    cursor.close()
        except Exception as exc:  # pragma: no cover - depends on external connector/runtime
            raise DatabaseConnectorError(f"Snowflake query failed: {exc}") from exc

    def _snowflake_connection_kwargs(self) -> dict[str, Any]:
        required = {
            "SNOWFLAKE_ACCOUNT": self.settings.snowflake_account,
            "SNOWFLAKE_USER": self.settings.snowflake_user,
            "SNOWFLAKE_ROLE": self.settings.snowflake_role,
            "SNOWFLAKE_WAREHOUSE": self.settings.snowflake_warehouse,
            "SNOWFLAKE_DATABASE": self.settings.snowflake_database,
            "SNOWFLAKE_SCHEMA": self.settings.snowflake_schema,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            joined = ", ".join(missing)
            raise DatabaseConfigurationError(
                "Snowflake execution is not configured. "
                f"Set {joined} in backend/.env."
            )
        return {
            "account": self.settings.snowflake_account,
            "user": self.settings.snowflake_user,
            "role": self.settings.snowflake_role,
            "warehouse": self.settings.snowflake_warehouse,
            "database": self.settings.snowflake_database,
            "schema": self.settings.snowflake_schema,
            "authenticator": self.settings.snowflake_authenticator,
            "login_timeout": self.settings.sql_query_timeout_seconds,
            "network_timeout": self.settings.sql_query_timeout_seconds,
            "session_parameters": {"QUERY_TAG": _QUERY_TAG},
        }

    def _write_sql_code_artifact(
        self,
        *,
        session_id: str,
        artifact_id: str,
        database: DatabaseBackend,
        created_at: datetime,
        executed_query: str,
    ) -> None:
        code_dir = self.settings.session_root / session_id / "artifacts" / "code" / "sql"
        code_dir.mkdir(parents=True, exist_ok=True)
        sql_path = code_dir / f"{artifact_id}.sql"
        header = (
            f"-- Executed {created_at.isoformat()} against {database}\n"
            f"-- Artifact: {artifact_id}\n\n"
        )
        sql_path.write_text(header + executed_query.rstrip() + "\n", encoding="utf-8")

    def _artifact_dir_for(
        self,
        session_id: str,
        database: DatabaseBackend,
        created_at: datetime,
    ) -> Path:
        sql_root = self.settings.session_root / session_id / "artifacts" / "sql"
        sql_root.mkdir(parents=True, exist_ok=True)
        artifact_id = (
            f"{database}_query_{created_at.strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
        )
        artifact_dir = sql_root / artifact_id
        artifact_dir.mkdir(parents=True, exist_ok=False)
        return artifact_dir

    def _resolve_configured_path(self, value: Path) -> Path:
        candidate = value.expanduser()
        if not candidate.is_absolute():
            candidate = self.settings.project_root / candidate
        return candidate.resolve()

    def _session_database_backend(self, session_id: str) -> DatabaseBackend:
        metadata_path = self.settings.session_root / session_id / "metadata.json"
        if not metadata_path.exists():
            raise DatabaseConfigurationError(f"Unknown session for SQL execution: {session_id}")

        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DatabaseConfigurationError(
                f"Session metadata is unreadable for SQL execution: {metadata_path}"
            ) from exc

        backend = payload.get("database_backend", self.settings.default_database_backend)
        return _normalize_database_name(str(backend))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    def _write_csv(
        self,
        path: Path,
        columns: list[str],
        rows: list[dict[str, Any]],
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            if columns:
                writer.writeheader()
                for row in rows:
                    writer.writerow({column: row.get(column) for column in columns})


def _normalize_database_name(database: str) -> DatabaseBackend:
    normalized = database.strip().lower()
    if normalized in {"sqlite", "snowflake"}:
        return normalized
    raise DatabaseConfigurationError(
        f"Unsupported database backend: {database!r}. Supported values are 'sqlite' and 'snowflake'."
    )


def _sanitize_query(query: str) -> str:
    normalized = query.strip()
    if not normalized:
        raise QueryValidationError("SQL query must not be empty.")

    while normalized.endswith(";"):
        normalized = normalized[:-1].rstrip()

    statement_without_comments = _strip_leading_comments(normalized)
    if not statement_without_comments:
        raise QueryValidationError("SQL query must not be empty.")

    if ";" in statement_without_comments:
        raise QueryValidationError(
            "Only a single read-only SQL statement is allowed."
        )

    lowered = statement_without_comments.lower()
    _ALLOWED_PREFIXES = (
        "select",
        "with",
        "show",
        "desc",
        "describe",
        "explain",
        "list",
    )
    if lowered.startswith("create"):
        if not _CREATE_TEMP_TABLE_RE.match(statement_without_comments):
            raise QueryValidationError(
                "Only CREATE [OR REPLACE] TEMPORARY TABLE statements are allowed. "
                "Creating non-temporary tables, views, or other objects is prohibited."
            )
    elif not any(lowered.startswith(prefix) for prefix in _ALLOWED_PREFIXES):
        raise QueryValidationError(
            "Only read-only statements and CREATE TEMPORARY TABLE are allowed "
            "(SELECT, WITH, SHOW, DESCRIBE, EXPLAIN, LIST, "
            "CREATE [OR REPLACE] TEMPORARY TABLE). "
            "Data-modifying statements (INSERT, UPDATE, DELETE, DROP, ALTER, etc.) "
            "are prohibited."
        )

    return statement_without_comments


def _strip_leading_comments(query: str) -> str:
    remaining = query.lstrip()
    while True:
        if remaining.startswith("--"):
            newline_index = remaining.find("\n")
            if newline_index == -1:
                return ""
            remaining = remaining[newline_index + 1 :].lstrip()
            continue
        if remaining.startswith("/*"):
            closing_index = remaining.find("*/")
            if closing_index == -1:
                raise QueryValidationError("Unterminated SQL block comment.")
            remaining = remaining[closing_index + 2 :].lstrip()
            continue
        return remaining
def _to_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
