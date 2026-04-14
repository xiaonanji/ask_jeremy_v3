from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ask_jeremy_backend.artifacts import collect_artifacts, is_user_visible_artifact, snapshot_artifacts
from ask_jeremy_backend.analysis import AnalysisArtifactError, validate_analysis_result
from ask_jeremy_backend.config import Settings
from ask_jeremy_backend.database import QueryValidationError, SqlQueryExecutor
from ask_jeremy_backend.tools import LocalToolRegistry
from ask_jeremy_backend.verification import verify_answer_against_analysis


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
            self.assertTrue(result.truncated)
            self.assertEqual(result.columns, ["id", "label"])
            self.assertTrue(result.json_path.exists())
            self.assertTrue(result.csv_path.exists())

            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["row_count"], 1)
            self.assertTrue(payload["truncated"])
            self.assertEqual(payload["rows"], [{"id": 1, "label": "alpha"}])
            self.assertEqual(payload["executed_query"], "select id, label from metrics order by id")

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
            self.assertTrue({"artifact_dir", "json_path", "csv_path"}.isdisjoint(payload.keys()))
            self.assertIn("truncated", payload)

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

    def test_generic_execution_tools_are_blocked_for_data_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            session_root = root / "sessions"
            session_dir = session_root / "session-1"
            (session_dir / "artifacts").mkdir(parents=True, exist_ok=True)
            (session_dir / "metadata.json").write_text(
                json.dumps({"database_backend": "sqlite"}),
                encoding="utf-8",
            )
            (session_dir / "messages.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "msg-1",
                            "role": "user",
                            "content": "How many students received awards?",
                            "created_at": "2026-04-14T00:00:00+00:00",
                            "artifacts": [],
                        }
                    ]
                ),
                encoding="utf-8",
            )

            settings = Settings(
                _env_file=None,
                project_root=root,
                session_root=session_root,
            )
            tools = {item.name: item for item in LocalToolRegistry(settings).build()}

            shell_output = tools["run_shell_command"].invoke(
                {"command": "Get-ChildItem"},
                config={"configurable": {"thread_id": "session-1"}},
            )
            self.assertIn("disabled for database-backed turns", shell_output)

            python_payload = json.loads(
                tools["run_python_script"].invoke(
                    {"script": "print('hello')"},
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )
            self.assertFalse(python_payload["ok"])
            self.assertEqual(python_payload["error_type"], "tool_blocked")

    def test_sql_cache_artifacts_are_not_user_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_root = Path(tmpdir) / "artifacts"
            before_snapshot = snapshot_artifacts(artifact_root)

            (artifact_root / "sql" / "query-1").mkdir(parents=True, exist_ok=True)
            (artifact_root / "sql" / "query-1" / "result.json").write_text("{}", encoding="utf-8")
            (artifact_root / "sql" / "query-1" / "result.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            (artifact_root / "analysis" / "analysis-1").mkdir(parents=True, exist_ok=True)
            (artifact_root / "analysis" / "analysis-1" / "analysis_result.json").write_text(
                "{}",
                encoding="utf-8",
            )
            (artifact_root / "charts").mkdir(parents=True, exist_ok=True)
            (artifact_root / "charts" / "figure.png").write_bytes(b"png-data")

            artifacts = collect_artifacts(artifact_root, before_snapshot)
            visible_paths = [
                item.relative_path for item in artifacts if is_user_visible_artifact(item.relative_path)
            ]

            self.assertEqual(visible_paths, ["charts/figure.png"])

    def test_analysis_pipeline_returns_bounded_analysis_result(self) -> None:
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
                connection.execute("create table metrics (id integer primary key, school text)")
                connection.execute("insert into metrics (school) values ('Scotch College')")
                connection.execute("insert into metrics (school) values ('James Ruse Agricultural High School')")
                connection.commit()
            finally:
                connection.close()

            settings = Settings(
                _env_file=None,
                project_root=root,
                session_root=session_root,
                sqlite_database_path=database_path,
            )
            tools = {item.name: item for item in LocalToolRegistry(settings).build()}

            sql_payload = json.loads(
                tools["execute_sql_query"].invoke(
                    {"query": "select school from metrics order by id"},
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )
            self.assertTrue(sql_payload["ok"])

            analysis_script = (
                "import json\n"
                "import os\n"
                "from pathlib import Path\n"
                "raw_path = Path(os.environ['RAW_SQL_RESULT_JSON_PATH'])\n"
                "output_path = Path(os.environ['ANALYSIS_OUTPUT_PATH'])\n"
                "payload = json.loads(raw_path.read_text(encoding='utf-8'))\n"
                "schools = [row['school'] for row in payload['rows']]\n"
                "result = {\n"
                "  'summary': f\"Found {len(schools)} schools in the current result set.\",\n"
                "  'metrics': {'school_count': len(schools)},\n"
                "  'findings': ['Scotch College appears in the result set.'],\n"
                "  'evidence': [\n"
                "    {'label': 'row_count', 'detail': 'Total rows returned by SQL', 'value': len(schools)},\n"
                "    {'label': 'schools', 'detail': 'Schools found in the result', 'value': schools},\n"
                "  ],\n"
                "  'caveats': [],\n"
                "  'uncertainty': [],\n"
                "  'needs_user_input': False,\n"
                "  'follow_up_question': None,\n"
                "  'allowed_mentions': schools,\n"
                "}\n"
                "output_path.write_text(json.dumps(result), encoding='utf-8')\n"
            )

            run_payload = json.loads(
                tools["run_analysis_script"].invoke(
                    {
                        "raw_artifact_id": sql_payload["artifact_id"],
                        "script": analysis_script,
                    },
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )
            self.assertTrue(run_payload["ok"])
            self.assertEqual(run_payload["result"]["metrics"]["school_count"], 2)
            self.assertFalse(run_payload["result"]["metrics"].get("sql_result_truncated", False))

            read_payload = json.loads(
                tools["read_analysis_result"].invoke(
                    {"analysis_artifact_id": run_payload["analysis_artifact_id"]},
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )
            self.assertTrue(read_payload["ok"])
            self.assertEqual(read_payload["result"]["metrics"]["school_count"], 2)
            self.assertEqual(
                read_payload["result"]["allowed_mentions"],
                ["Scotch College", "James Ruse Agricultural High School"],
            )

    def test_analysis_pipeline_exposes_legacy_raw_artifact_env_aliases(self) -> None:
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
                connection.execute("create table metrics (id integer primary key, awarded_students integer)")
                connection.execute("insert into metrics (awarded_students) values (141)")
                connection.commit()
            finally:
                connection.close()

            settings = Settings(
                _env_file=None,
                project_root=root,
                session_root=session_root,
                sqlite_database_path=database_path,
            )
            tools = {item.name: item for item in LocalToolRegistry(settings).build()}

            sql_payload = json.loads(
                tools["execute_sql_query"].invoke(
                    {"query": "select awarded_students from metrics limit 1"},
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )
            self.assertTrue(sql_payload["ok"])

            analysis_script = (
                "import json, os\n"
                "input_path = os.environ['RAW_RESULT_JSON_PATH']\n"
                "artifact_dir = os.environ['RAW_ARTIFACT_DIR']\n"
                "output_path = os.environ['ANALYSIS_OUTPUT_PATH']\n"
                "payload = json.loads(open(input_path, 'r', encoding='utf-8').read())\n"
                "assert artifact_dir\n"
                "count = payload['rows'][0]['awarded_students']\n"
                "result = {\n"
                "  'summary': f'{count} students received awards.',\n"
                "  'metrics': {'awarded_students': count},\n"
                "  'findings': [],\n"
                "  'evidence': [{'label': 'awarded_students', 'detail': '', 'value': count}],\n"
                "  'caveats': [],\n"
                "  'uncertainty': [],\n"
                "  'needs_user_input': False,\n"
                "  'follow_up_question': None,\n"
                "  'allowed_mentions': []\n"
                "}\n"
                "open(output_path, 'w', encoding='utf-8').write(json.dumps(result))\n"
            )

            run_payload = json.loads(
                tools["run_analysis_script"].invoke(
                    {
                        "raw_artifact_id": sql_payload["artifact_id"],
                        "script": analysis_script,
                    },
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )

            self.assertTrue(run_payload["ok"])
            self.assertEqual(run_payload["result"]["metrics"]["awarded_students"], 141)

    def test_analysis_pipeline_persists_truncation_signal_into_bounded_result(self) -> None:
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
            tools = {item.name: item for item in LocalToolRegistry(settings).build()}

            sql_payload = json.loads(
                tools["execute_sql_query"].invoke(
                    {"query": "select label from metrics order by id"},
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )
            self.assertTrue(sql_payload["truncated"])

            analysis_script = (
                "import json\n"
                "import os\n"
                "from pathlib import Path\n"
                "raw_path = Path(os.environ['RAW_SQL_RESULT_JSON_PATH'])\n"
                "output_path = Path(os.environ['ANALYSIS_OUTPUT_PATH'])\n"
                "payload = json.loads(raw_path.read_text(encoding='utf-8'))\n"
                "labels = [row['label'] for row in payload['rows']]\n"
                "result = {\n"
                "  'summary': 'Materialized a subset of labels.',\n"
                "  'metrics': {'label_count': len(labels)},\n"
                "  'findings': [],\n"
                "  'evidence': [{'label': 'labels', 'detail': 'Labels present in the artifact', 'value': labels}],\n"
                "  'caveats': [],\n"
                "  'uncertainty': [],\n"
                "  'needs_user_input': False,\n"
                "  'follow_up_question': None,\n"
                "  'allowed_mentions': []\n"
                "}\n"
                "output_path.write_text(json.dumps(result), encoding='utf-8')\n"
            )

            run_payload = json.loads(
                tools["run_analysis_script"].invoke(
                    {
                        "raw_artifact_id": sql_payload["artifact_id"],
                        "script": analysis_script,
                    },
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )

            self.assertTrue(run_payload["ok"])
            self.assertTrue(run_payload["result"]["metrics"]["sql_result_truncated"])
            self.assertEqual(run_payload["result"]["metrics"]["sql_row_limit"], 1)
            self.assertIn("truncated", run_payload["result"]["caveats"][0].lower())

    def test_analysis_pipeline_rejects_raw_rows_in_output(self) -> None:
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
            tools = {item.name: item for item in LocalToolRegistry(settings).build()}

            sql_payload = json.loads(
                tools["execute_sql_query"].invoke(
                    {"query": "select id, label from metrics"},
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )

            bad_script = (
                "import json\n"
                "import os\n"
                "from pathlib import Path\n"
                "raw_path = Path(os.environ['RAW_SQL_RESULT_JSON_PATH'])\n"
                "output_path = Path(os.environ['ANALYSIS_OUTPUT_PATH'])\n"
                "payload = json.loads(raw_path.read_text(encoding='utf-8'))\n"
                "result = {\n"
                "  'summary': 'This illegally includes raw rows.',\n"
                "  'metrics': {},\n"
                "  'findings': [],\n"
                "  'evidence': [],\n"
                "  'caveats': [],\n"
                "  'uncertainty': [],\n"
                "  'needs_user_input': False,\n"
                "  'follow_up_question': None,\n"
                "  'allowed_mentions': [],\n"
                "  'rows': payload['rows'],\n"
                "}\n"
                "output_path.write_text(json.dumps(result), encoding='utf-8')\n"
            )

            run_payload = json.loads(
                tools["run_analysis_script"].invoke(
                    {
                        "raw_artifact_id": sql_payload["artifact_id"],
                        "script": bad_script,
                    },
                    config={"configurable": {"thread_id": "session-1"}},
                )
            )

            self.assertFalse(run_payload["ok"])
            self.assertEqual(run_payload["error_type"], "analysis_output_error")
            self.assertIn("unsupported keys", run_payload["message"].lower())

    def test_answer_verifier_catches_ungrounded_numbers_and_entities(self) -> None:
        analysis_result = {
            "summary": "Found 2 schools.",
            "metrics": {"school_count": 2},
            "findings": [],
            "evidence": [
                {"label": "schools", "detail": "", "value": ["Scotch College", "James Ruse Agricultural High School"]},
                {"label": "row_count", "detail": "", "value": 2},
            ],
            "caveats": [],
            "uncertainty": [],
            "needs_user_input": False,
            "follow_up_question": None,
            "allowed_mentions": ["Scotch College", "James Ruse Agricultural High School"],
        }

        issues = verify_answer_against_analysis(
            "Balwyn High School has 3 students in the result.",
            analysis_result,
        )

        self.assertEqual(len(issues), 2)
        self.assertIn("numbers", issues[0].lower())
        self.assertIn("named entities", issues[1].lower())

    def test_answer_verifier_requires_truncation_disclosure(self) -> None:
        analysis_result = {
            "summary": "Materialized the first 1000 rows.",
            "metrics": {
                "sql_result_truncated": True,
                "sql_row_limit": 1000,
                "sql_materialized_row_count": 1000,
            },
            "findings": ["The current artifact includes only the first 1000 rows."],
            "evidence": [
                {
                    "label": "sql_result_truncated",
                    "detail": "The SQL artifact was truncated during materialization.",
                    "value": {"truncated": True, "row_limit": 1000, "materialized_row_count": 1000},
                }
            ],
            "caveats": ["SQL materialization was truncated to the first 1000 rows for safety."],
            "uncertainty": [],
            "needs_user_input": False,
            "follow_up_question": None,
            "allowed_mentions": [],
        }

        issues = verify_answer_against_analysis(
            "The result set contains 1000 rows.",
            analysis_result,
        )

        self.assertEqual(len(issues), 1)
        self.assertIn("truncated", issues[0].lower())

    def test_analysis_result_normalizes_common_model_near_misses(self) -> None:
        payload = {
            "question": "How many students got awards in AMO Summary 2026?",
            "award_count": 141,
            "notes": ["Counted rows where the award field is populated."],
            "evidence": {"filter_used": "award IS NOT NULL"},
            "uncertainty": "Low if student rows are unique.",
            "caveats": [],
        }

        normalized = validate_analysis_result(payload)

        self.assertEqual(normalized["metrics"]["award_count"], 141)
        self.assertEqual(
            normalized["findings"],
            ["Counted rows where the award field is populated."],
        )
        self.assertEqual(
            normalized["uncertainty"],
            ["Low if student rows are unique."],
        )
        self.assertEqual(normalized["evidence"][0]["label"], "filter_used")
        self.assertEqual(normalized["evidence"][0]["value"], "award IS NOT NULL")

    def test_analysis_result_normalizes_string_evidence_and_type_labels(self) -> None:
        payload = {
            "summary": {"award_student_count": 141},
            "metrics": {"award_student_count": 141},
            "findings": "Counted populated award rows.",
            "evidence": [
                "Filter used: award IS NOT NULL",
                {"type": "source", "detail": "COUNT(*) over filtered rows", "value": None},
            ],
            "caveats": [],
            "uncertainty": [],
        }

        normalized = validate_analysis_result(payload)

        self.assertIn("award_student_count=141", normalized["summary"])
        self.assertEqual(normalized["findings"], ["Counted populated award rows."])
        self.assertEqual(normalized["evidence"][0]["label"], "evidence_1")
        self.assertEqual(normalized["evidence"][1]["label"], "source")

    def test_analysis_result_still_rejects_raw_rows(self) -> None:
        with self.assertRaises(AnalysisArtifactError):
            validate_analysis_result(
                {
                    "summary": "Unsafe payload",
                    "rows": [{"student": "Alice"}],
                }
            )


if __name__ == "__main__":
    unittest.main()
