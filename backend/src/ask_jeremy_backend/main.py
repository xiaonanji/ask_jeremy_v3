import json
from mimetypes import guess_type

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from .artifacts import (
    collect_artifacts,
    is_user_visible_artifact,
    resolve_session_artifact_path,
    session_artifact_root,
    snapshot_artifacts,
)
from .config import get_settings
from .llm import SessionContext, build_chat_client
from .model_catalog import ModelCatalog
from .schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    ChatArtifact,
    ModelCatalogResponse,
    SendMessageRequest,
    SendMessageResponse,
    SessionDetail,
    SessionLog,
    SessionMetadata,
    SessionModelConfig,
    SessionSkillsResponse,
    SessionSummary,
    SkillCatalogResponse,
    UpdateSessionRequest,
    UpdateSessionDatabaseRequest,
    UpdateSessionModelRequest,
)
from .sessions import SessionStore

settings = get_settings()
session_store = SessionStore(settings.session_root)
model_catalog = ModelCatalog(settings)
chat_client = build_chat_client(settings)

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
def shutdown_event() -> None:
    chat_client.close()


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get(f"{settings.api_prefix}/models", response_model=ModelCatalogResponse)
def get_model_catalog() -> ModelCatalogResponse:
    return model_catalog.as_response()


@app.get(f"{settings.api_prefix}/skills", response_model=SkillCatalogResponse)
def get_skill_catalog() -> SkillCatalogResponse:
    return SkillCatalogResponse(skills=chat_client.list_skills())


@app.get(f"{settings.api_prefix}/sessions", response_model=list[SessionSummary])
def list_sessions() -> list[SessionSummary]:
    return session_store.list_sessions()


@app.post(f"{settings.api_prefix}/sessions", response_model=CreateSessionResponse)
def create_session(payload: CreateSessionRequest) -> CreateSessionResponse:
    model_config = _resolve_session_model_config(
        provider=payload.model_provider,
        model_name=payload.model_name,
    )
    session = session_store.create_session(
        model_config=model_config,
        database_backend=payload.database_backend or settings.default_database_backend,
        title=payload.title,
    )
    return CreateSessionResponse(session=session, messages=[])


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}", response_model=SessionDetail)
def get_session(session_id: str) -> SessionDetail:
    return session_store.get_session(session_id)


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/artifacts/{{artifact_path:path}}")
def get_session_artifact(session_id: str, artifact_path: str) -> FileResponse:
    try:
        artifact = resolve_session_artifact_path(settings.session_root, session_id, artifact_path)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact was not found: {artifact_path}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    media_type, _ = guess_type(artifact.name)
    return FileResponse(
        path=artifact,
        filename=artifact.name,
        media_type=media_type,
        content_disposition_type=_artifact_content_disposition_type(media_type),
    )


@app.get(f"{settings.api_prefix}/sessions/{{session_id}}/log", response_model=SessionLog)
def get_session_log(session_id: str) -> SessionLog:
    return session_store.get_session_log(session_id)


@app.get(
    f"{settings.api_prefix}/sessions/{{session_id}}/skills",
    response_model=SessionSkillsResponse,
)
def get_session_skills(session_id: str) -> SessionSkillsResponse:
    session_store.get_session(session_id)
    return SessionSkillsResponse(
        session_id=session_id,
        skills=chat_client.get_active_skills(session_id),
    )


@app.patch(f"{settings.api_prefix}/sessions/{{session_id}}", response_model=SessionMetadata)
def update_session(session_id: str, payload: UpdateSessionRequest) -> SessionMetadata:
    return session_store.update_session_title(session_id, payload.title)


@app.patch(
    f"{settings.api_prefix}/sessions/{{session_id}}/model",
    response_model=SessionMetadata,
)
def update_session_model(
    session_id: str,
    payload: UpdateSessionModelRequest,
) -> SessionMetadata:
    model_config = _resolve_session_model_config(
        provider=payload.model_provider,
        model_name=payload.model_name,
    )
    return session_store.update_session_model(session_id, model_config)


@app.patch(
    f"{settings.api_prefix}/sessions/{{session_id}}/database",
    response_model=SessionMetadata,
)
def update_session_database(
    session_id: str,
    payload: UpdateSessionDatabaseRequest,
) -> SessionMetadata:
    return session_store.update_session_database(session_id, payload.database_backend)


@app.delete(f"{settings.api_prefix}/sessions/{{session_id}}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str) -> Response:
    session_store.delete_session(session_id)
    chat_client.delete_thread(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    f"{settings.api_prefix}/sessions/{{session_id}}/messages",
    response_model=SendMessageResponse,
)
def send_message(session_id: str, payload: SendMessageRequest) -> SendMessageResponse:
    artifact_root = session_artifact_root(settings.session_root, session_id)
    before_snapshot = snapshot_artifacts(artifact_root)
    user_message = session_store.append_message(session_id, "user", payload.content)
    session_detail = session_store.get_session(session_id)
    model_config = SessionModelConfig(
        model_provider=session_detail.session.model_provider,
        model_name=session_detail.session.model_name,
    )
    assistant_reply = chat_client.generate_reply(
        SessionContext(
            session_id=session_detail.session.id,
            workspace_path=session_detail.session.workspace_path,
            artifacts_path=session_detail.session.workspace_path.parent / "artifacts",
            database_backend=session_detail.session.database_backend,
            model=model_config,
        ),
        session_detail.messages,
    )
    assistant_message = session_store.append_message(
        session_id,
        "assistant",
        assistant_reply.content,
        message_id=assistant_reply.message_id,
        artifacts=_artifacts_for_turn(artifact_root, before_snapshot),
    )
    session_store.append_log_turn(session_id, user_message, assistant_message, model_config)
    session = session_store.get_session(session_id).session
    return SendMessageResponse(
        session=session,
        user_message=user_message,
        assistant_message=assistant_message,
    )


@app.post(f"{settings.api_prefix}/sessions/{{session_id}}/messages/stream")
async def stream_message(session_id: str, payload: SendMessageRequest) -> StreamingResponse:
    artifact_root = session_artifact_root(settings.session_root, session_id)
    before_snapshot = snapshot_artifacts(artifact_root)
    user_message = session_store.append_message(session_id, "user", payload.content)
    session_detail = session_store.get_session(session_id)
    model_config = SessionModelConfig(
        model_provider=session_detail.session.model_provider,
        model_name=session_detail.session.model_name,
    )

    async def event_generator():
        try:
            async for event in chat_client.stream_reply(
                SessionContext(
                    session_id=session_detail.session.id,
                    workspace_path=session_detail.session.workspace_path,
                    artifacts_path=session_detail.session.workspace_path.parent / "artifacts",
                    database_backend=session_detail.session.database_backend,
                    model=model_config,
                ),
                session_detail.messages,
            ):
                event_type = str(event.get("type"))
                if event_type != "final_response":
                    yield _sse_event(event_type, event)
                    continue

                assistant_message = session_store.append_message(
                    session_id,
                    "assistant",
                    str(event["content"]),
                    message_id=str(event["message_id"]),
                    artifacts=_artifacts_for_turn(artifact_root, before_snapshot),
                )
                session_store.append_log_turn(
                    session_id,
                    user_message,
                    assistant_message,
                    model_config,
                )
                session = session_store.get_session(session_id).session
                yield _sse_event(
                    "done",
                    {
                        "session": session.model_dump(mode="json"),
                        "user_message": user_message.model_dump(mode="json"),
                        "assistant_message": assistant_message.model_dump(mode="json"),
                    },
                )
        except Exception as exc:
            yield _sse_event(
                "error",
                {
                    "message": str(exc),
                },
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _resolve_session_model_config(
    provider: str | None,
    model_name: str | None,
) -> SessionModelConfig:
    if provider is None and model_name is None:
        return model_catalog.default_config()

    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="model_provider is required when model_name is provided",
        )

    try:
        if model_name is None:
            model_name = model_catalog.default_for(provider)
        return model_catalog.validate(provider, model_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def _sse_event(event_name: str, payload: object) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n"


def _artifacts_for_turn(
    artifact_root,
    before_snapshot: dict[str, tuple[int, int]],
) -> list[ChatArtifact]:
    return [
        ChatArtifact(
            filename=item.filename,
            relative_path=item.relative_path,
            mime_type=item.mime_type,
            size_bytes=item.size_bytes,
        )
        for item in collect_artifacts(artifact_root, before_snapshot)
        if is_user_visible_artifact(item.relative_path)
    ]


def _artifact_content_disposition_type(media_type: str | None) -> str:
    if not media_type:
        return "attachment"

    if media_type.startswith("image/") or media_type.startswith("text/"):
        return "inline"

    if media_type in {
        "application/pdf",
        "application/json",
    }:
        return "inline"

    return "attachment"
