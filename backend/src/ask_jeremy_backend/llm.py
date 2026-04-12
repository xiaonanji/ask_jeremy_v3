from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import os
import sqlite3
from typing import Annotated, TypedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from langchain.chat_models import init_chat_model
from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.messages import AIMessageChunk, AnyMessage, BaseMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.runtime import Runtime

from .config import Settings
from .schemas import ChatMessage, DatabaseBackend, SessionModelConfig, SkillSummary
from .skills.activation import SkillActivationManager
from .skills.catalog import SkillCatalog
from .skills.discovery import SkillDiscoveryService
from .skills.parser import SkillParser
from .skills.prompting import SkillPromptRenderer
from .mcp_tools import set_mcp_event_emitter
from .tools import LocalToolRegistry


@dataclass
class SessionContext:
    session_id: str
    workspace_path: Path
    artifacts_path: Path
    database_backend: DatabaseBackend
    model: SessionModelConfig


@dataclass
class GraphContext:
    session_id: str
    workspace_path: str
    artifacts_path: str
    database_backend: DatabaseBackend
    project_root: str
    person_wiki_root: str | None
    model_provider: str
    model_name: str
    system_prompt: str
    api_key: str | None
    base_url: str | None
    max_tokens: int | None
    max_history_messages: int
    current_datetime: str
    current_date: str
    current_timezone: str


@dataclass
class GeneratedReply:
    message_id: str
    content: str


class SkillAwareState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    active_skill_ids: list[str]
    active_skill_names: list[str]
    active_skill_instructions: list[str]


class LangGraphChatClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # Ensure .env takes precedence over system environment variables for Anthropic
        # The Anthropic SDK reads ANTHROPIC_AUTH_TOKEN from os.environ directly,
        # so we need to override it with the value from .env if present
        if settings.anthropic_api_key:
            os.environ['ANTHROPIC_AUTH_TOKEN'] = settings.anthropic_api_key

        self.settings.langgraph_checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_connection = sqlite3.connect(
            self.settings.langgraph_checkpoint_path,
            check_same_thread=False,
        )
        self._checkpointer = SqliteSaver(self._checkpoint_connection)
        self._models: dict[tuple[str, str, str, str, int | None], object] = {}
        self.skill_catalog = SkillCatalog(settings, SkillDiscoveryService(SkillParser()))
        self.skill_activation = SkillActivationManager(
            self.skill_catalog,
            max_auto_activated_skills=settings.max_auto_activated_skills,
        )
        self.skill_prompt_renderer = SkillPromptRenderer()
        self._local_tools = LocalToolRegistry(settings).build()
        self._tools = list(self._local_tools)
        self._graph = self._build_graph(streaming=False)

    def generate_reply(
        self,
        session: SessionContext,
        history: list[ChatMessage],
    ) -> GeneratedReply:
        result = self._graph.invoke(
            {"messages": self._to_langchain_messages(history)},
            {"configurable": {"thread_id": session.session_id}},
            context=self._graph_context(session),
        )
        assistant_message = result["messages"][-1]
        message_id = assistant_message.id or str(uuid4())
        return GeneratedReply(
            message_id=message_id,
            content=self._message_text(assistant_message),
        )

    def delete_thread(self, session_id: str) -> None:
        self._checkpointer.delete_thread(session_id)

    def close(self) -> None:
        self._checkpoint_connection.close()

    async def stream_reply(
        self,
        session: SessionContext,
        history: list[ChatMessage],
    ) -> AsyncIterator[dict[str, object]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, object] | BaseException | object] = asyncio.Queue()
        sentinel = object()
        config = {"configurable": {"thread_id": session.session_id}}
        history_messages = self._to_langchain_messages(history)
        graph_context = self._graph_context(session)

        def worker() -> None:
            set_mcp_event_emitter(
                lambda event: loop.call_soon_threadsafe(queue.put_nowait, event)
            )
            connection = sqlite3.connect(
                self.settings.langgraph_checkpoint_path,
                check_same_thread=False,
            )
            try:
                checkpointer = SqliteSaver(connection)
                stream_graph = self._build_graph(streaming=False, checkpointer=checkpointer)

                for mode, data in stream_graph.stream(
                    {"messages": history_messages},
                    config,
                    context=graph_context,
                    stream_mode=["messages", "tasks"],
                ):
                    if mode == "messages":
                        message, metadata = data
                        if metadata.get("langgraph_node") != "call_model":
                            continue
                        if isinstance(message, AIMessageChunk):
                            delta = str(message.text)
                            if delta:
                                loop.call_soon_threadsafe(
                                    queue.put_nowait,
                                    {
                                        "type": "assistant_delta",
                                        "delta": delta,
                                    },
                                )
                        continue

                    if mode == "tasks":
                        if "triggers" in data:
                            loop.call_soon_threadsafe(
                                queue.put_nowait,
                                {
                                    "type": "task_started",
                                    "task_id": data["id"],
                                    "name": data["name"],
                                },
                            )
                            continue

                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            {
                                "type": "task_finished",
                                "task_id": data["id"],
                                "name": data["name"],
                                "error": data.get("error"),
                            },
                        )

                final_reply = self._final_reply_for_session(
                    session.session_id,
                    graph=stream_graph,
                )
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {
                        "type": "final_response",
                        "message_id": final_reply.message_id,
                        "content": final_reply.content,
                    },
                )
            except BaseException as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                connection.close()
                loop.call_soon_threadsafe(queue.put_nowait, sentinel)

        worker_task = asyncio.create_task(asyncio.to_thread(worker))
        try:
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            await worker_task

    def _build_graph(self, *, streaming: bool, checkpointer=None):
        builder = StateGraph(SkillAwareState, context_schema=GraphContext)
        builder.add_node("select_skills", self._select_skills)
        builder.add_node("call_model", self._call_model)
        builder.add_node("tools", ToolNode(self._tools))
        builder.add_edge(START, "select_skills")
        builder.add_edge("select_skills", "call_model")
        builder.add_conditional_edges("call_model", tools_condition)
        builder.add_edge("tools", "call_model")
        return builder.compile(checkpointer=checkpointer or self._checkpointer)

    def set_mcp_tools(self, tools: list) -> None:
        """Merge MCP tools with local tools and rebuild the graph.

        Called once during application startup after MCP connections are
        established. All sessions will pick up the new tools immediately.
        """
        self._tools = [*self._local_tools, *tools]
        self._graph = self._build_graph(streaming=False)

    def list_skills(self) -> list[SkillSummary]:
        return [self._to_skill_summary(skill) for skill in self.skill_catalog.list_skills()]

    def get_active_skills(self, session_id: str) -> list[SkillSummary]:
        snapshot = self._graph.get_state({"configurable": {"thread_id": session_id}})
        values = getattr(snapshot, "values", {}) or {}
        skill_ids = values.get("active_skill_ids", [])
        active_skills = self.skill_activation.hydrate(skill_ids)
        return [
            self._to_skill_summary(self.skill_catalog.get(skill.id))
            for skill in active_skills
            if self.skill_catalog.get(skill.id) is not None
        ]

    def _select_skills(
        self,
        state: SkillAwareState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, list[str]]:
        context = runtime.context
        messages = state.get("messages", [])
        latest_user_message = next(
            (
                self._message_text(message)
                for message in reversed(messages)
                if isinstance(message, HumanMessage)
            ),
            "",
        )
        if not latest_user_message:
            return {}

        if not context.api_key:
            return {}

        available_skills = self.skill_catalog.list_skills()
        if not available_skills:
            return {}

        current_ids = list(state.get("active_skill_ids", []))

        # Always include person-wiki-knowledge skill if available and PERSON_WIKI_ROOT is configured
        always_active_skills = []
        if context.person_wiki_root:
            wiki_skill = self.skill_catalog.get_by_name("person-wiki-knowledge")
            if wiki_skill and wiki_skill.id not in current_ids:
                always_active_skills.append(wiki_skill.id)

        selected_ids = self._select_skill_ids_with_model(
            context=context,
            messages=messages,
            skills=available_skills,
            active_skill_ids=current_ids,
        )

        # Merge always-active skills with LLM-selected skills
        selected_ids = [*always_active_skills, *selected_ids]
        selected_ids = [skill_id for skill_id in selected_ids if skill_id not in current_ids]
        newly_selected = self.skill_activation.activate_by_ids(selected_ids)
        if not newly_selected and state.get("active_skill_instructions"):
            return {}

        merged_ids = [*current_ids, *[skill.id for skill in newly_selected]]
        hydrated = self.skill_activation.hydrate(merged_ids)
        return {
            "active_skill_ids": [skill.id for skill in hydrated],
            "active_skill_names": [skill.name for skill in hydrated],
            "active_skill_instructions": [
                self.skill_prompt_renderer.render_active_instructions(hydrated)
            ]
            if hydrated
            else [],
        }

    def _select_skill_ids_with_model(
        self,
        context: GraphContext,
        messages: list[BaseMessage],
        skills,
        active_skill_ids: list[str],
    ) -> list[str]:
        selector_messages = [
            SystemMessage(content=self.skill_prompt_renderer.render_selection_instructions()),
            HumanMessage(
                content=(
                    f"Available skills:\n{self.skill_prompt_renderer.render_selection_catalog(skills)}\n\n"
                    f"Currently active skill ids: {json.dumps(active_skill_ids)}\n\n"
                    f"Recent conversation:\n{self._render_recent_conversation(messages)}"
                )
            ),
        ]
        response = self._get_model(context).invoke(selector_messages)
        response_text = self._message_text(response)
        return self._parse_selected_skill_ids(response_text)

    def _call_model(
        self,
        state: SkillAwareState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, list[AIMessage]]:
        context = runtime.context
        if not context.api_key:
            return {
                "messages": [
                    AIMessage(
                        id=str(uuid4()),
                        content=self._placeholder_reply(context, state["messages"]),
                    )
                ]
            }

        messages = list(state["messages"])
        if context.max_history_messages > 0:
            messages = messages[-context.max_history_messages :]

        prompt = [
            SystemMessage(
                content=(
                    f"{context.system_prompt}\n\n"
                    f"Current date/time: {context.current_datetime}\n"
                    f"Current date: {context.current_date}\n"
                    f"Current timezone: {context.current_timezone}\n"
                    f"Conversation session id: {context.session_id}\n"
                    f"Session workspace: {context.workspace_path}\n"
                    f"Session artifacts: {context.artifacts_path}\n"
                    f"Session database backend: {context.database_backend}\n"
                    f"Project root: {context.project_root}\n"
                    f"Configured PERSON_WIKI_ROOT: {context.person_wiki_root or 'not configured'}"
                )
            ),
            *self._skill_prompt_messages(state),
            *messages,
        ]
        response = self._get_model(context).bind_tools(self._tools).invoke(prompt)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(response))
        if not response.id:
            response = response.model_copy(update={"id": str(uuid4())})
        return {"messages": [response]}

    def _get_model(self, context: GraphContext):
        key = (
            context.model_provider,
            context.model_name,
            context.base_url or "",
            context.api_key or "",
            context.max_tokens,
        )
        if key not in self._models:
            model_kwargs: dict[str, object] = {
                "model": context.model_name,
                "model_provider": context.model_provider,
            }
            if context.api_key:
                model_kwargs["api_key"] = context.api_key
            if context.base_url:
                model_kwargs["base_url"] = context.base_url
            if context.max_tokens is not None:
                model_kwargs["max_tokens"] = context.max_tokens
            model_kwargs["streaming"] = True
            self._models[key] = init_chat_model(**model_kwargs)
        return self._models[key]

    def _graph_context(self, session: SessionContext) -> GraphContext:
        api_key: str | None
        base_url: str | None
        max_tokens: int | None = None

        if session.model.model_provider == "anthropic":
            api_key = self.settings.anthropic_api_key
            base_url = self.settings.anthropic_base_url
            max_tokens = self.settings.anthropic_max_tokens
        else:
            api_key = self.settings.openai_api_key
            base_url = self.settings.openai_base_url

        return GraphContext(
            session_id=session.session_id,
            workspace_path=str(session.workspace_path),
            artifacts_path=str(session.artifacts_path),
            database_backend=session.database_backend,
            project_root=str(self.settings.project_root),
            person_wiki_root=(
                str(self.settings.person_wiki_root)
                if self.settings.person_wiki_root is not None
                else None
            ),
            model_provider=session.model.model_provider,
            model_name=session.model.model_name,
            system_prompt=self.settings.system_prompt,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            max_history_messages=self.settings.max_history_messages,
            current_datetime=self._current_datetime_iso(),
            current_date=self._current_date(),
            current_timezone=self._current_timezone_name(),
        )

    def _to_langchain_messages(self, history: list[ChatMessage]) -> list[BaseMessage]:
        converted: list[BaseMessage] = []
        for message in history:
            if message.role == "user":
                converted.append(HumanMessage(content=message.content, id=message.id))
            elif message.role == "assistant":
                converted.append(AIMessage(content=message.content, id=message.id))
            else:
                converted.append(SystemMessage(content=message.content, id=message.id))
        return converted

    def _placeholder_reply(
        self,
        context: GraphContext,
        messages: list[BaseMessage],
    ) -> str:
        latest = next(
            (
                self._message_text(message)
                for message in reversed(messages)
                if isinstance(message, HumanMessage)
            ),
            "",
        )
        if context.model_provider == "anthropic":
            credential_hint = "Set ANTHROPIC_API_KEY in backend/.env to enable Claude responses."
        else:
            credential_hint = "Set OPENAI_API_KEY in backend/.env to enable ChatGPT responses."

        return (
            "The backend is running, but no provider credentials are configured yet. "
            f"{credential_hint}\n\n"
            f"Selected provider: {context.model_provider}\n"
            f"Selected model: {context.model_name}\n"
            f"Session: {context.session_id}\n"
            f"Workspace: {context.workspace_path}\n"
            f"Last user message: {latest}"
        )

    def _message_text(self, message: BaseMessage) -> str:
        content = message.content
        if isinstance(content, str):
            return content.strip()

        # Handle Anthropic-style content blocks: [{'text': '...', 'type': 'text'}]
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
                elif isinstance(block, str):
                    text_parts.append(block)
            if text_parts:
                return '\n'.join(text_parts).strip()

        # Fallback for any other format
        return str(content).strip()

    def _final_reply_for_session(self, session_id: str, *, graph) -> GeneratedReply:
        snapshot = graph.get_state({"configurable": {"thread_id": session_id}})
        values = getattr(snapshot, "values", {}) or {}
        messages = values.get("messages", [])
        assistant_message = next(
            (message for message in reversed(messages) if isinstance(message, AIMessage)),
            None,
        )
        if assistant_message is None:
            raise RuntimeError("No assistant message was produced for the streamed reply.")

        return GeneratedReply(
            message_id=assistant_message.id or str(uuid4()),
            content=self._message_text(assistant_message),
        )

    def _skill_prompt_messages(self, state: SkillAwareState) -> list[SystemMessage]:
        instructions = state.get("active_skill_instructions", [])
        if not instructions:
            return []
        return [SystemMessage(content=instruction) for instruction in instructions if instruction]

    def _render_recent_conversation(self, messages: list[BaseMessage], limit: int = 6) -> str:
        lines: list[str] = []
        for message in messages[-limit:]:
            if isinstance(message, HumanMessage):
                role = "user"
            elif isinstance(message, AIMessage):
                role = "assistant"
            elif isinstance(message, SystemMessage):
                role = "system"
            else:
                role = "other"
            lines.append(f"{role}: {self._message_text(message)}")
        return "\n".join(lines)

    def _parse_selected_skill_ids(self, response_text: str) -> list[str]:
        payload = self._extract_json_object(response_text)
        if payload is None:
            return []

        skill_ids = payload.get("skill_ids")
        if not isinstance(skill_ids, list):
            return []

        parsed: list[str] = []
        for item in skill_ids:
            if isinstance(item, str) and item.strip():
                parsed.append(item.strip())
        return parsed

    def _extract_json_object(self, value: str) -> dict[str, object] | None:
        stripped = value.strip()
        candidates = [stripped]
        if "```" in stripped:
            for block in stripped.split("```"):
                cleaned = block.strip()
                if not cleaned:
                    continue
                if cleaned.lower().startswith("json"):
                    cleaned = cleaned[4:].strip()
                if cleaned:
                    candidates.append(cleaned)

        for candidate in candidates:
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start == -1 or end == -1 or end <= start:
                continue
            try:
                parsed = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _to_skill_summary(self, skill) -> SkillSummary:
        return SkillSummary(
            id=skill.id,
            name=skill.name,
            description=skill.description,
            scope=skill.scope,
            trusted=skill.trusted,
            path=skill.skill_dir,
        )

    def _current_datetime_iso(self) -> str:
        current = self._now()
        return current.isoformat(timespec="seconds")

    def _current_date(self) -> str:
        return self._now().date().isoformat()

    def _current_timezone_name(self) -> str:
        return str(self._timezone())

    def _now(self) -> datetime:
        return datetime.now(self._timezone())

    def _timezone(self):
        local_tz = datetime.now().astimezone().tzinfo
        if local_tz is not None:
            return local_tz
        return timezone.utc


def build_chat_client(settings: Settings) -> LangGraphChatClient:
    return LangGraphChatClient(settings)
