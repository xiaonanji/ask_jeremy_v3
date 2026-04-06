from __future__ import annotations

import json
import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException, status

from .schemas import (
    ChatMessage,
    SessionDetail,
    SessionLog,
    SessionLogTurn,
    SessionMetadata,
    SessionModelConfig,
    SessionSummary,
)


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, Lock] = {}
        self._creation_lock = Lock()

    def list_sessions(self) -> list[SessionSummary]:
        summaries: list[SessionSummary] = []
        for metadata_path in self.root.glob("*/metadata.json"):
            metadata = self._read_metadata(metadata_path.parent)
            summaries.append(
                SessionSummary(
                    id=metadata.id,
                    title=metadata.title,
                    created_at=metadata.created_at,
                    updated_at=metadata.updated_at,
                    model_provider=metadata.model_provider,
                    model_name=metadata.model_name,
                )
            )
        return sorted(summaries, key=lambda item: item.updated_at, reverse=True)

    def create_session(
        self,
        model_config: SessionModelConfig,
        title: str | None = None,
    ) -> SessionMetadata:
        with self._creation_lock:
            session_id = str(uuid4())
            session_dir = self.root / session_id
            workspace_dir = session_dir / "workspace"
            artifacts_dir = session_dir / "artifacts"

            workspace_dir.mkdir(parents=True, exist_ok=False)
            artifacts_dir.mkdir(parents=True, exist_ok=False)

            now = self._utc_now()
            metadata = SessionMetadata(
                id=session_id,
                title=title or self._next_default_title(),
                created_at=now,
                updated_at=now,
                workspace_path=workspace_dir,
                model_provider=model_config.model_provider,
                model_name=model_config.model_name,
            )

            self._write_json(session_dir / "metadata.json", metadata.model_dump(mode="json"))
            self._write_json(session_dir / "messages.json", [])
            self._write_json(
                session_dir / "conversation_log.json",
                SessionLog(
                    session_id=session_id,
                    log_path=session_dir / "conversation_log.json",
                    created_at=now,
                    updated_at=now,
                    turns=[],
                ).model_dump(mode="json"),
            )
            return metadata

    def get_session(self, session_id: str) -> SessionDetail:
        session_dir = self._session_dir(session_id)
        return SessionDetail(
            session=self._read_metadata(session_dir),
            messages=self._read_messages(session_dir),
        )

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_id: str | None = None,
    ) -> ChatMessage:
        session_dir = self._session_dir(session_id)
        with self._lock_for(session_id):
            messages = self._read_messages(session_dir)
            message = ChatMessage(
                id=message_id or str(uuid4()),
                role=role,
                content=content,
                created_at=self._utc_now(),
            )
            messages.append(message)
            self._write_json(
                session_dir / "messages.json",
                [item.model_dump(mode="json") for item in messages],
            )

            metadata = self._read_metadata(session_dir)
            updated_title = metadata.title
            if self._is_default_title(metadata.title) and role == "user":
                updated_title = self._derive_title(content)
            metadata = metadata.model_copy(
                update={
                    "title": updated_title,
                    "updated_at": message.created_at,
                }
            )
            self._write_json(session_dir / "metadata.json", metadata.model_dump(mode="json"))
            return message

    def build_history(self, session_id: str, max_messages: int) -> list[dict[str, str]]:
        session = self.get_session(session_id)
        history = session.messages[-max_messages:]
        return [{"role": item.role, "content": item.content} for item in history]

    def get_session_log(self, session_id: str) -> SessionLog:
        session_dir = self._session_dir(session_id)
        return self._read_or_rebuild_log(session_dir)

    def update_session_model(
        self,
        session_id: str,
        model_config: SessionModelConfig,
    ) -> SessionMetadata:
        session_dir = self._session_dir(session_id)
        with self._lock_for(session_id):
            metadata = self._read_metadata(session_dir).model_copy(
                update={
                    "model_provider": model_config.model_provider,
                    "model_name": model_config.model_name,
                    "updated_at": self._utc_now(),
                }
            )
            self._write_json(session_dir / "metadata.json", metadata.model_dump(mode="json"))
            return metadata

    def update_session_title(self, session_id: str, title: str) -> SessionMetadata:
        session_dir = self._session_dir(session_id)
        with self._lock_for(session_id):
            metadata = self._read_metadata(session_dir).model_copy(
                update={
                    "title": title,
                    "updated_at": self._utc_now(),
                }
            )
            self._write_json(session_dir / "metadata.json", metadata.model_dump(mode="json"))
            return metadata

    def delete_session(self, session_id: str) -> None:
        session_dir = self._session_dir(session_id)
        with self._lock_for(session_id):
            shutil.rmtree(session_dir)
        self._locks.pop(session_id, None)

    def append_log_turn(
        self,
        session_id: str,
        user_message: ChatMessage,
        assistant_message: ChatMessage,
        model_config: SessionModelConfig,
    ) -> SessionLogTurn:
        session_dir = self._session_dir(session_id)
        with self._lock_for(session_id):
            log = self._read_or_rebuild_log(session_dir)
            turn = self._build_turn(
                user_message=user_message,
                assistant_message=assistant_message,
                model_config=model_config,
            )
            log = log.model_copy(
                update={
                    "updated_at": assistant_message.created_at,
                    "turns": [*log.turns, turn],
                }
            )
            self._write_json(self._log_path(session_dir), log.model_dump(mode="json"))
            return turn

    def _session_dir(self, session_id: str) -> Path:
        session_dir = self.root / session_id
        if not session_dir.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown session: {session_id}",
            )
        return session_dir

    def _read_metadata(self, session_dir: Path) -> SessionMetadata:
        payload = self._read_json(session_dir / "metadata.json")
        return SessionMetadata.model_validate(payload)

    def _read_messages(self, session_dir: Path) -> list[ChatMessage]:
        payload = self._read_json(session_dir / "messages.json")
        return [ChatMessage.model_validate(item) for item in payload]

    def _read_or_rebuild_log(self, session_dir: Path) -> SessionLog:
        log_path = self._log_path(session_dir)
        if log_path.exists():
            payload = self._read_json(log_path)
            return SessionLog.model_validate(payload)

        metadata = self._read_metadata(session_dir)
        messages = self._read_messages(session_dir)
        turns: list[SessionLogTurn] = []
        pending_user: ChatMessage | None = None

        for message in messages:
            if message.role == "user":
                pending_user = message
                continue
            if message.role == "assistant" and pending_user is not None:
                turns.append(
                    self._build_turn(
                        user_message=pending_user,
                        assistant_message=message,
                        model_config=SessionModelConfig(
                            model_provider=metadata.model_provider,
                            model_name=metadata.model_name,
                        ),
                    )
                )
                pending_user = None

        log = SessionLog(
            session_id=metadata.id,
            log_path=log_path,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
            turns=turns,
        )
        self._write_json(log_path, log.model_dump(mode="json"))
        return log

    def _build_turn(
        self,
        user_message: ChatMessage,
        assistant_message: ChatMessage,
        model_config: SessionModelConfig,
    ) -> SessionLogTurn:
        user_word_count = self._word_count(user_message.content)
        assistant_word_count = self._word_count(assistant_message.content)
        response_time_seconds = (
            assistant_message.created_at - user_message.created_at
        ).total_seconds()

        return SessionLogTurn(
            turn_id=str(uuid4()),
            model_provider=model_config.model_provider,
            model_name=model_config.model_name,
            user_message_id=user_message.id,
            user_message=user_message.content,
            user_created_at=user_message.created_at,
            user_word_count=user_word_count,
            user_token_estimate=self._estimate_tokens(user_message.content),
            assistant_message_id=assistant_message.id,
            assistant_response=assistant_message.content,
            assistant_created_at=assistant_message.created_at,
            assistant_word_count=assistant_word_count,
            assistant_token_estimate=self._estimate_tokens(assistant_message.content),
            response_time_ms=max(0, round(response_time_seconds * 1000)),
            response_time_seconds=max(0.0, round(response_time_seconds, 3)),
        )

    def _write_json(self, path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _read_json(self, path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8"))

    def _log_path(self, session_dir: Path) -> Path:
        return session_dir / "conversation_log.json"

    def _lock_for(self, session_id: str) -> Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = Lock()
            self._locks[session_id] = lock
        return lock

    def _derive_title(self, content: str) -> str:
        compact = " ".join(content.split())
        return compact[:47] + "..." if len(compact) > 50 else compact

    def _is_default_title(self, title: str) -> bool:
        return bool(re.fullmatch(r"New chat \d+", title))

    def _next_default_title(self) -> str:
        highest_index = 0
        for metadata_path in self.root.glob("*/metadata.json"):
            try:
                title = self._read_metadata(metadata_path.parent).title
            except (json.JSONDecodeError, FileNotFoundError, KeyError, ValueError):
                continue
            match = re.fullmatch(r"New chat (\d+)", title)
            if match:
                highest_index = max(highest_index, int(match.group(1)))
        return f"New chat {highest_index + 1}"

    def _word_count(self, text: str) -> int:
        return len(re.findall(r"\S+", text))

    def _estimate_tokens(self, text: str) -> int:
        word_count = self._word_count(text)
        if word_count == 0:
            return 0
        return max(1, math.ceil(word_count * 1.33))

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)
