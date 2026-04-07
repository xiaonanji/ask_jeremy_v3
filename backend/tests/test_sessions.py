from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ask_jeremy_backend.schemas import ChatArtifact, SessionModelConfig
from ask_jeremy_backend.sessions import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_new_session_uses_selected_database_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(root)

            session = store.create_session(
                model_config=SessionModelConfig(
                    model_provider="openai",
                    model_name="gpt-5.4",
                ),
                database_backend="snowflake",
            )

            self.assertEqual(session.database_backend, "snowflake")
            loaded = store.get_session(session.id)
            self.assertEqual(loaded.session.database_backend, "snowflake")

    def test_existing_session_database_backend_can_be_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(root)

            session = store.create_session(
                model_config=SessionModelConfig(
                    model_provider="openai",
                    model_name="gpt-5.4",
                ),
            )

            updated = store.update_session_database(session.id, "snowflake")

            self.assertEqual(updated.database_backend, "snowflake")
            loaded = store.get_session(session.id)
            self.assertEqual(loaded.session.database_backend, "snowflake")

    def test_messages_persist_artifact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionStore(root)

            session = store.create_session(
                model_config=SessionModelConfig(
                    model_provider="openai",
                    model_name="gpt-5.4",
                ),
            )

            store.append_message(session.id, "user", "Make me a chart")
            store.append_message(
                session.id,
                "assistant",
                "The chart is ready.",
                artifacts=[
                    ChatArtifact(
                        filename="figure.png",
                        relative_path="charts/figure.png",
                        mime_type="image/png",
                        size_bytes=1234,
                    )
                ],
            )

            loaded = store.get_session(session.id)
            self.assertEqual(len(loaded.messages), 2)
            self.assertEqual(len(loaded.messages[1].artifacts), 1)
            self.assertEqual(loaded.messages[1].artifacts[0].relative_path, "charts/figure.png")


if __name__ == "__main__":
    unittest.main()
