from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ask_jeremy_backend.artifacts import collect_artifacts, is_user_visible_artifact, snapshot_artifacts
from ask_jeremy_backend.config import Settings
from ask_jeremy_backend.database import QueryValidationError, SqlQueryExecutor
from ask_jeremy_backend.tools import LocalToolRegistry


class SqlQueryExecutorTests(unittest.TestCase):
    def test_sqlite_query_is_materialized_to_session_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            database_path = root / "sample.sqlite"
            session_root = root / "sessions"
            (session_root / "session-1" / "artifacts").mkdir(parents=True, exist_ok=True)

            connection = sqlite3.connect(database_path)
            try:
                connection.execute("create table metrics (id integer primary key, label text)")
                connection.execute("insert into metrics (label) values ('alpha')")
                connection.execute("insert into metrics (label) values ('beta')")
                connection.commit()
            finally:
                connection.close()

            settings = Settings(
                _env_file=None,
                project_root=root,
                session_root=session_root,
                sqlite_database_path=database_path,
                sql_query_max_rows=1,
            )
            executor = SqlQueryExecutor(settings)

            metadata_path = session_root / "session-1" / "metadata.json"
            metadata_path.write_text(
                json.dumps({"database_backend": "sqlite"}),
                encoding="utf-8",
            )

            result = executor.execute_query(
                query="select id, label from metrics order by id",
                session_id="session-1",
            )

            self.assertEqual(result.database, "sqlite")
            self.assertEqual(result.row_count, 1)
            self.assertEqual(result.columns, ["id", "label"])
            self.assertTrue(result.json_path.exists())
            self.assertTrue(result.csv_path.exists())

            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["row_count"], 1)
            self.assertEqual(payload["rows"], [{"id": 1, "label": "alpha"}])
            self.assertTrue(payload["executed_query"].lower().endswith("limit 1"))

    def test_non_select_queries_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_root = root / "sessions"
            (session_root / "session-1").mkdir(parents=True, exist_ok=True)
            (session_root / "session-1" / "metadata.json").write_text(
                json.dumps({"database_backend": "sqlite"}),
                encoding="utf-8",
            )
            settings = Settings(
                _env_file=None,
                project_root=root,
                session_root=session_root,
                sqlite_database_path=root / "sample.sqlite",
            )
            executor = SqlQueryExecutor(settings)

            with self.assertRaises(QueryValidationError):
                executor.execute_query(
                    query="delete from metrics",
                    session_id="session-1",
                )

    def test_tool_returns_exit_code_zero_for_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            database_path = root / "sample.sqlite"
            session_root = root / "sessions"
            (session_root / "session-1" / "artifacts").mkdir(parents=True, exist_ok=True)
            (session_root / "session-1" / "metadata.json").write_text(
                json.dumps({"database_backend": "sqlite"}),
                encoding="utf-8",
            )

            connection = sqlite3.connect(database_path)
            try:
                connection.execute("create table metrics (id integer primary key, label text)")
                connection.execute("insert into metrics (label) values ('alpha')")
                connection.commit()
            finally:
                connection.close()

            settings = Settings(
                _env_file=None,
                project_root=root,
                session_root=session_root,
                sqlite_database_path=database_path,
            )
            tool = next(
                item for item in LocalToolRegistry(settings).build() if item.name == "execute_sql_query"
            )

            payload = json.loads(
                tool.invoke(
                    {"query": "select id, label from metrics"},
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )

            self.assertEqual(payload["exit_code"], 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["database"], "sqlite")
            self.assertIn("artifact_id", payload)

    def test_tool_returns_exit_code_one_with_recoverable_syntax_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            database_path = root / "sample.sqlite"
            session_root = root / "sessions"
            (session_root / "session-1" / "artifacts").mkdir(parents=True, exist_ok=True)
            (session_root / "session-1" / "metadata.json").write_text(
                json.dumps({"database_backend": "sqlite"}),
                encoding="utf-8",
            )

            connection = sqlite3.connect(database_path)
            try:
                connection.execute("create table metrics (id integer primary key, label text)")
                connection.commit()
            finally:
                connection.close()

            settings = Settings(
                _env_file=None,
                project_root=root,
                session_root=session_root,
                sqlite_database_path=database_path,
            )
            tool = next(
                item for item in LocalToolRegistry(settings).build() if item.name == "execute_sql_query"
            )

            payload = json.loads(
                tool.invoke(
                    {"query": "select from metrics"},
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )

            self.assertEqual(payload["exit_code"], 1)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error_type"], "syntax_error")
            self.assertTrue(payload["recoverable"])
            self.assertIn("syntax", payload["message"].lower())

    def test_tool_returns_exit_code_one_with_nonrecoverable_connection_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_root = root / "sessions"
            (session_root / "session-1" / "artifacts").mkdir(parents=True, exist_ok=True)
            (session_root / "session-1" / "metadata.json").write_text(
                json.dumps({"database_backend": "sqlite"}),
                encoding="utf-8",
            )

            settings = Settings(
                _env_file=None,
                project_root=root,
                session_root=session_root,
                sqlite_database_path=root / "missing.sqlite",
            )
            tool = next(
                item for item in LocalToolRegistry(settings).build() if item.name == "execute_sql_query"
            )

            payload = json.loads(
                tool.invoke(
                    {"query": "select 1"},
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )

            self.assertEqual(payload["exit_code"], 1)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error_type"], "database_connection_error")
            self.assertFalse(payload["recoverable"])
            self.assertIn("configured sqlite database was not found", payload["message"].lower())

    def test_run_python_script_returns_detected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_root = root / "sessions"
            (session_root / "session-1" / "artifacts").mkdir(parents=True, exist_ok=True)

            settings = Settings(
                _env_file=None,
                project_root=root,
                session_root=session_root,
            )
            tool = next(
                item for item in LocalToolRegistry(settings).build() if item.name == "run_python_script"
            )

            payload = json.loads(
                tool.invoke(
                    {
                        "script": (
                            "from pathlib import Path\n"
                            "import os\n"
                            "artifact_root = Path(os.environ['SESSION_ARTIFACTS_PATH'])\n"
                            "(artifact_root / 'charts').mkdir(parents=True, exist_ok=True)\n"
                            "(artifact_root / 'charts' / 'figure.png').write_bytes(b'plot-data')\n"
                            "print('saved chart')\n"
                        )
                    },
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )

            self.assertEqual(payload["exit_code"], 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["stdout"], "saved chart")
            self.assertEqual(payload["stderr"], "")
            self.assertEqual(len(payload["artifacts"]), 1)
            self.assertEqual(payload["artifacts"][0]["relative_path"], "charts/figure.png")
            self.assertTrue(Path(payload["artifacts"][0]["path"]).exists())

    def test_sql_cache_artifacts_are_not_user_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir) / "artifacts"
            before_snapshot = snapshot_artifacts(artifact_root)

            (artifact_root / "sql" / "query-1").mkdir(parents=True, exist_ok=True)
            (artifact_root / "sql" / "query-1" / "result.json").write_text("{}", encoding="utf-8")
            (artifact_root / "sql" / "query-1" / "result.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            (artifact_root / "charts").mkdir(parents=True, exist_ok=True)
            (artifact_root / "charts" / "figure.png").write_bytes(b"png-data")

            artifacts = collect_artifacts(artifact_root, before_snapshot)
            visible_paths = [
                item.relative_path for item in artifacts if is_user_visible_artifact(item.relative_path)
            ]

            self.assertEqual(visible_paths, ["charts/figure.png"])


if __name__ == "__main__":
    unittest.main()
