from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import logging
import os
import sqlite3
import threading
from typing import Annotated, TypedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from langchain.chat_models import init_chat_model
from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.messages import AIMessageChunk, AnyMessage, BaseMessage, RemoveMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime

from .config import Settings
from .schemas import ChatMessage, DatabaseBackend, SessionModelConfig, SkillSummary
from .skills.activation import SkillActivationManager
from .skills.catalog import SkillCatalog
from .skills.discovery import SkillDiscoveryService
from .skills.parser import SkillParser
from .skills.prompting import SkillPromptRenderer
from .mcp_tools import emit_custom_event, set_mcp_event_emitter
from .tools import LocalToolRegistry
from .warehouse_policy import snowflake_table_policy_prompt
from .working_memory import (
    apply_memory_update,
    normalize_working_memory,
    render_working_memory,
    tool_payload_memory_updates,
)

logger = logging.getLogger(__name__)


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
    conversation_summary: str
    requires_data_pipeline: bool
    working_memory: dict[str, object]


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
        self._repair_interrupted_state(session.session_id)
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

    def _repair_interrupted_state(
        self, session_id: str, *, graph=None
    ) -> None:
        """Fix checkpoint state left invalid by a mid-tool-call interruption.

        When a stream is cancelled after the model has issued tool_calls but
        before tool results are recorded, the checkpoint ends with an AIMessage
        containing tool_calls and no matching ToolMessages.  This violates the
        API's message format requirements.  We detect this and inject synthetic
        error ToolMessages so the next turn can proceed.
        """
        g = graph or self._graph
        config = {"configurable": {"thread_id": session_id}}
        snapshot = g.get_state(config)
        values = getattr(snapshot, "values", {}) or {}
        messages = values.get("messages", [])

        if not messages:
            return

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return

        tool_calls = getattr(last_msg, "tool_calls", None) or []
        if not tool_calls:
            return

        # Collect IDs of ToolMessages already present after the last AIMessage
        existing_tool_ids: set[str] = set()
        for msg in reversed(messages[:-1]):
            if isinstance(msg, ToolMessage):
                existing_tool_ids.add(getattr(msg, "tool_call_id", ""))
            else:
                break

        orphaned = [
            tc
            for tc in tool_calls
            if (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", ""))
            not in existing_tool_ids
        ]

        if not orphaned:
            return

        logger.warning(
            "Repairing interrupted checkpoint for session %s: "
            "injecting %d synthetic tool result(s)",
            session_id,
            len(orphaned),
        )

        repair_messages: list[ToolMessage] = []
        for tc in orphaned:
            tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
            tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            repair_messages.append(
                ToolMessage(
                    content=json.dumps({
                        "ok": False,
                        "error_type": "interrupted",
                        "message": "Tool execution was interrupted by the user.",
                    }),
                    tool_call_id=tc_id,
                    name=tc_name,
                )
            )

        g.update_state(config, {"messages": repair_messages})

    async def stream_reply(
        self,
        session: SessionContext,
        history: list[ChatMessage],
    ) -> AsyncIterator[dict[str, object]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, object] | BaseException | object] = asyncio.Queue()
        sentinel = object()
        cancelled = threading.Event()
        config = {"configurable": {"thread_id": session.session_id}}
        history_messages = self._to_langchain_messages(history)
        graph_context = self._graph_context(session)

        def worker() -> None:
            # Track details emitted during each node's execution so they
            # can be bundled into the task_finished event.
            node_details: list[dict] = []

            def _emit_to_queue(event: dict) -> None:
                """Put an event into node_details and the SSE queue."""
                node_details.append(event)
                loop.call_soon_threadsafe(queue.put_nowait, event)

            # Store on instance so graph nodes can emit directly
            self._stream_emit = _emit_to_queue

            def _capturing_emitter(event: dict) -> None:
                _emit_to_queue(event)

            set_mcp_event_emitter(_capturing_emitter)
            connection = sqlite3.connect(
                self.settings.langgraph_checkpoint_path,
                check_same_thread=False,
            )
            try:
                checkpointer = SqliteSaver(connection)
                stream_graph = self._build_graph(streaming=False, checkpointer=checkpointer)
                self._repair_interrupted_state(session.session_id, graph=stream_graph)

                for mode, data in stream_graph.stream(
                    {"messages": history_messages},
                    config,
                    context=graph_context,
                    stream_mode=["messages", "tasks"],
                ):
                    if cancelled.is_set():
                        break
                    if mode == "messages":
                        message, metadata = data
                        node_name = metadata.get("langgraph_node", "")

                        # Capture tool results from the "tools" node
                        if node_name == "tools" and isinstance(message, ToolMessage):
                            content_str = str(message.content) if message.content else ""
                            try:
                                parsed = json.loads(content_str)
                            except (json.JSONDecodeError, TypeError):
                                parsed = None
                            tool_result_event = {
                                "type": "tool_result",
                                "tool_call_id": getattr(message, "tool_call_id", ""),
                                "tool_name": getattr(message, "name", ""),
                                "ok": parsed.get("ok") if isinstance(parsed, dict) else None,
                                "exit_code": parsed.get("exit_code") if isinstance(parsed, dict) else None,
                                "error_type": parsed.get("error_type") if isinstance(parsed, dict) else None,
                                "message": parsed.get("message", "") if isinstance(parsed, dict) else content_str[:500],
                                "details": _summarize_tool_result(parsed, content_str),
                            }
                            node_details.append(tool_result_event)
                            loop.call_soon_threadsafe(
                                queue.put_nowait,
                                tool_result_event,
                            )
                            continue

                        if node_name != "call_model":
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

                        # Capture tool calls from ANY message type
                        # (AIMessage from .invoke(), or AIMessageChunk
                        # with accumulated tool_calls from streaming).
                        # Chunks arrive incrementally: ID/name first, args
                        # filled in by later chunks.  We update existing
                        # entries in-place so node_details always holds the
                        # most complete version for _build_task_finished_details.
                        seen_tc_map: dict[str, dict] = {
                            d["tool_call_id"]: d
                            for d in node_details
                            if d.get("type") == "tool_call"
                        }
                        for tc in getattr(message, "tool_calls", None) or []:
                            tc_id = (
                                tc.get("id", "")
                                if isinstance(tc, dict)
                                else getattr(tc, "id", "")
                            )
                            tc_name = (
                                tc.get("name", "")
                                if isinstance(tc, dict)
                                else getattr(tc, "name", "")
                            )
                            tc_args = (
                                tc.get("args", {})
                                if isinstance(tc, dict)
                                else getattr(tc, "args", {})
                            )
                            existing = seen_tc_map.get(tc_id)
                            if existing is not None:
                                # Update with latest (more complete) values
                                if tc_name:
                                    existing["tool_name"] = tc_name
                                if tc_args:
                                    existing["tool_args"] = tc_args
                                continue
                            tc_event = {
                                "type": "tool_call",
                                "tool_call_id": tc_id,
                                "tool_name": tc_name,
                                "tool_args": tc_args,
                            }
                            seen_tc_map[tc_id] = tc_event
                            node_details.append(tc_event)
                            loop.call_soon_threadsafe(
                                queue.put_nowait, tc_event
                            )
                        continue

                    if mode == "tasks":
                        if "triggers" in data:
                            node_details.clear()
                            loop.call_soon_threadsafe(
                                queue.put_nowait,
                                {
                                    "type": "task_started",
                                    "task_id": data["id"],
                                    "name": data["name"],
                                },
                            )
                            continue

                        # Bundle details captured during this node's execution
                        details = _build_task_finished_details(
                            data["name"], node_details
                        )
                        node_details.clear()
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            {
                                "type": "task_finished",
                                "task_id": data["id"],
                                "name": data["name"],
                                "error": data.get("error"),
                                "details": details,
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
                self._stream_emit = None
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
        except GeneratorExit:
            # Client disconnected — signal the worker to stop.
            cancelled.set()
            raise
        finally:
            cancelled.set()
            await worker_task

    def _build_graph(self, *, streaming: bool, checkpointer=None):
        builder = StateGraph(SkillAwareState, context_schema=GraphContext)
        builder.add_node("select_skills", self._select_skills)
        builder.add_node("compact_messages", self._compact_messages)
        builder.add_node("call_model", self._call_model)
        builder.add_node("tools", ToolNode(self._tools))
        builder.add_node("update_working_memory", self._update_working_memory)
        builder.add_node("enforce_analysis", self._enforce_data_pipeline)
        builder.add_edge(START, "select_skills")
        builder.add_edge("select_skills", "compact_messages")
        builder.add_edge("compact_messages", "call_model")
        builder.add_conditional_edges(
            "call_model",
            self._route_after_model,
            {
                "tools": "tools",
                "enforce_analysis": "enforce_analysis",
                "end": END,
            },
        )
        builder.add_edge("tools", "update_working_memory")
        builder.add_edge("update_working_memory", "compact_messages")
        builder.add_edge("enforce_analysis", "compact_messages")
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

        classification = self._classify_turn_with_model(
            context=context,
            messages=messages,
            skills=available_skills,
            active_skill_ids=current_ids,
        )
        selected_ids: list[str] = classification["skill_ids"]
        requires_data_pipeline: bool = classification["requires_data_pipeline"]

        # Always include person-wiki-knowledge skill so the agent can
        # consult the wiki for domain context — including during data
        # pipeline turns where definitions or terminology inform SQL.
        always_active_skills = []
        if context.person_wiki_root:
            wiki_skill = self.skill_catalog.get_by_name("person-wiki-knowledge")
            if wiki_skill and wiki_skill.id not in current_ids:
                always_active_skills.append(wiki_skill.id)

        # Merge always-active skills with LLM-selected skills
        selected_ids = [*always_active_skills, *selected_ids]
        selected_ids = [skill_id for skill_id in selected_ids if skill_id not in current_ids]
        newly_selected = self.skill_activation.activate_by_ids(selected_ids)
        if not newly_selected and state.get("active_skill_instructions"):
            return {"requires_data_pipeline": requires_data_pipeline}

        merged_ids = [*current_ids, *[skill.id for skill in newly_selected]]
        hydrated = self.skill_activation.hydrate(merged_ids)

        skill_names = [skill.name for skill in hydrated]
        if skill_names:
            skill_details = []
            for skill in hydrated:
                definition = self.skill_catalog.get(skill.id)
                detail: dict[str, str] = {"name": skill.name}
                if definition is not None:
                    detail["path"] = str(definition.skill_file)
                    detail["description"] = definition.description
                    detail["scope"] = definition.scope
                skill_details.append(detail)
            event = {
                "type": "skills_activated",
                "names": skill_names,
                "skills": skill_details,
            }
            # Emit directly via the queue (bypasses thread-local emitter)
            emitter = getattr(self, "_stream_emit", None)
            if emitter is not None:
                emitter(event)
            else:
                emit_custom_event(event)

        return {
            "active_skill_ids": [skill.id for skill in hydrated],
            "active_skill_names": skill_names,
            "active_skill_instructions": [
                self.skill_prompt_renderer.render_active_instructions(hydrated)
            ]
            if hydrated
            else [],
            "requires_data_pipeline": requires_data_pipeline,
        }

    def _classify_turn_with_model(
        self,
        context: GraphContext,
        messages: list[BaseMessage],
        skills,
        active_skill_ids: list[str],
    ) -> dict[str, object]:
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
        return self._parse_turn_classification(response_text)

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

        all_messages = list(state["messages"])

        # Separate any SystemMessages that ended up in the conversation history
        # (e.g. from _enforce_data_pipeline) so they can be consolidated at the
        # top of the prompt.  The Anthropic API rejects non-consecutive system
        # messages.
        messages: list[BaseMessage] = []
        extra_system_messages: list[SystemMessage] = []
        for msg in all_messages:
            if isinstance(msg, SystemMessage):
                extra_system_messages.append(msg)
            else:
                messages.append(msg)

        # Ensure tool_use / tool_result pairs are consistent before sending
        # to the LLM.  Checkpoint merges can leave orphaned ToolMessages or
        # AIMessages with tool_calls that lost their matching results.
        messages = _sanitize_tool_message_pairs(messages)

        database_display = _database_display_name(context.database_backend)
        warehouse_policy = ""
        if context.database_backend == "snowflake":
            warehouse_policy = (
                "\n\n=== SNOWFLAKE REFERENCED TABLE POLICY ===\n"
                f"{snowflake_table_policy_prompt(self.settings.project_skill_root)}"
            )

        summary = state.get("conversation_summary", "")
        summary_messages: list[SystemMessage] = []
        if summary:
            summary_messages = [SystemMessage(content=(
                "=== EARLIER CONVERSATION CONTEXT ===\n"
                "The following summarizes earlier parts of this conversation:\n\n"
                f"{summary}"
            ))]

        working_memory_message = SystemMessage(content=(
            "=== TASK WORKING MEMORY ===\n"
            f"{render_working_memory(state.get('working_memory', {}))}"
        ))

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
                    f"Project root: {context.project_root}\n"
                    f"Configured PERSON_WIKI_ROOT: {context.person_wiki_root or 'not configured'}\n\n"
                    "=== ACTIVE SQL DATABASE ===\n"
                    f"This session's `execute_sql_query` tool runs queries against: {database_display}.\n"
                    f"Every SQL statement you produce MUST be valid {database_display} syntax.\n"
                    f"Do not mix in syntax from other SQL dialects. If you are unsure whether a "
                    f"function or clause exists in {database_display}, use a form you are confident "
                    f"is supported there, or consult {database_display} documentation conventions."
                    f"{warehouse_policy}"
                )
            ),
            *summary_messages,
            working_memory_message,
            *self._skill_prompt_messages(state),
            *extra_system_messages,
            *messages,
        ]
        response = self._get_model(context).bind_tools(self._tools_for_turn(state)).invoke(prompt)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(response))
        if not response.id:
            response = response.model_copy(update={"id": str(uuid4())})
        if getattr(response, "tool_calls", None):
            emitter = getattr(self, "_stream_emit", None)
            for tc in response.tool_calls:
                event = {
                    "type": "tool_call",
                    "tool_call_id": tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", ""),
                    "tool_name": tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", ""),
                    "tool_args": tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {}),
                }
                if emitter is not None:
                    emitter(event)
                else:
                    emit_custom_event(event)
        return {"messages": [response]}

    def _enforce_data_pipeline(
        self,
        state: SkillAwareState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, list[HumanMessage]]:
        messages = state.get("messages", [])
        sql_artifact_id = self._latest_sql_artifact_id(messages)
        if sql_artifact_id:
            guidance = (
                "[SYSTEM GUIDANCE] "
                "This is a data-backed request. Do not answer yet. "
                f"You already have raw SQL artifact `{sql_artifact_id}` for the current turn. "
                "Write and run a Python analysis script with `run_analysis_script`. "
                "The script must write its output to ANALYSIS_OUTPUT_PATH as JSON — do not print raw rows to stdout. "
                "If the user asked for a full list or ranking (e.g. 'show all schools'), output the complete records in the 'table' field; do not summarize or truncate. "
                "Answer only from the bounded analysis result returned by the tool (or `read_analysis_result` if needed). "
                "Generic shell and inline Python tools are unavailable for this turn. "
                "If the user request is ambiguous, ask a clarifying question instead of guessing."
            )
        else:
            guidance = (
                "[SYSTEM GUIDANCE] "
                "This is a data-backed request. Do not answer yet. "
                "Run `execute_sql_query`, then `run_analysis_script`, and answer only from the bounded analysis result returned by that tool. "
                "The script must write its output to ANALYSIS_OUTPUT_PATH as JSON — do not print raw rows to stdout. "
                "If the user asked for a full list or ranking (e.g. 'show all schools'), output the complete records in the 'table' field of the analysis result; do not summarize or truncate. "
                "Use `read_analysis_result` only if you need to reread an earlier analysis artifact. "
                "Generic shell and inline Python tools are unavailable for this turn. "
                "If the request is ambiguous, ask a clarifying question instead of guessing."
            )
        return {"messages": [HumanMessage(content=guidance)]}

    def _update_working_memory(
        self,
        state: SkillAwareState,
        runtime: Runtime[GraphContext],
    ) -> dict[str, object]:
        memory = normalize_working_memory(state.get("working_memory", {}))
        changed = False

        for message in self._messages_since_latest_human(state.get("messages", [])):
            if not isinstance(message, ToolMessage):
                continue
            content = self._message_text(message)
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                continue
            tool_name = str(getattr(message, "name", "") or "")
            for update in tool_payload_memory_updates(
                tool_name=tool_name,
                payload=payload,
            ):
                memory, update_changed = apply_memory_update(memory, update)
                changed = changed or update_changed

        if not changed:
            return {}

        self._write_working_memory_file(runtime.context, memory)
        emitter = getattr(self, "_stream_emit", None)
        item_count = sum(len(items) for items in memory.values())
        event = {
            "type": "working_memory_updated",
            "item_count": item_count,
        }
        if emitter is not None:
            emitter(event)
        else:
            emit_custom_event(event)
        return {"working_memory": memory}

    def _write_working_memory_file(
        self,
        context: GraphContext,
        memory: dict[str, object],
    ) -> None:
        try:
            workspace_path = Path(context.workspace_path)
            workspace_path.mkdir(parents=True, exist_ok=True)
            (workspace_path / "working_memory.json").write_text(
                json.dumps(memory, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("Failed to persist task working memory file.", exc_info=True)

    def _route_after_model(self, state: SkillAwareState) -> str:
        messages = state.get("messages", [])
        assistant_message = self._latest_ai_message(messages)
        if assistant_message is None:
            return "end"

        if self._is_no_credentials_reply(assistant_message):
            return "end"

        if getattr(assistant_message, "tool_calls", None):
            return "tools"

        if not self._requires_data_pipeline(state):
            return "end"

        if self._assistant_requests_clarification(assistant_message):
            return "end"

        if self._has_terminal_tool_error(messages):
            return "end"

        if self._latest_analysis_result(messages) is None:
            return "enforce_analysis"

        return "end"

    def _tools_for_turn(self, state: SkillAwareState) -> list:
        if not self._requires_data_pipeline(state):
            return self._tools
        # Block run_python_script during data-pipeline turns so the agent
        # cannot bypass the bounded analysis pipeline.  Keep
        # run_shell_command available — the agent needs it for wiki
        # searches, file inspection, and other context-gathering that
        # informs SQL construction.  The system prompt already instructs
        # the agent not to use shell commands for data retrieval.
        blocked_names = {"run_python_script"}
        return [
            tool for tool in self._tools
            if getattr(tool, "name", "") not in blocked_names
        ]

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
            system_prompt=self.settings.resolved_system_prompt,
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

    def _is_no_credentials_reply(self, message: AIMessage) -> bool:
        return "no provider credentials are configured" in self._message_text(message)

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

    def _latest_ai_message(self, messages: list[BaseMessage]) -> AIMessage | None:
        return next(
            (message for message in reversed(messages) if isinstance(message, AIMessage)),
            None,
        )

    def _requires_data_pipeline(self, state: SkillAwareState) -> bool:
        messages = state.get("messages", [])
        # Pipeline already in progress — keep enforcing
        if self._latest_sql_artifact_id(messages) or self._latest_analysis_result(messages):
            return True
        # LLM classification from _select_skills
        return state.get("requires_data_pipeline", False)

    def _assistant_requests_clarification(self, message: AIMessage) -> bool:
        text = self._message_text(message).lower()
        if "?" not in text:
            return False
        clarifiers = (
            "clarify",
            "which",
            "what exactly",
            "what should",
            "do you want",
            "can you confirm",
            "could you confirm",
            "which table",
            "which metric",
        )
        return any(item in text for item in clarifiers)

    def _has_terminal_tool_error(self, messages: list[BaseMessage]) -> bool:
        for payload in self._current_turn_tool_payloads(messages):
            if payload.get("ok") is False and payload.get("recoverable") is False:
                return True
        return False

    def _latest_sql_artifact_id(self, messages: list[BaseMessage]) -> str | None:
        for payload in reversed(self._current_turn_tool_payloads(messages)):
            artifact_id = payload.get("artifact_id")
            if payload.get("ok") is True and isinstance(artifact_id, str) and artifact_id:
                return artifact_id
        return None

    def _latest_analysis_result(self, messages: list[BaseMessage]) -> dict[str, object] | None:
        for payload in reversed(self._current_turn_tool_payloads(messages)):
            result = payload.get("result")
            if payload.get("ok") is True and isinstance(result, dict):
                return result
        return None

    def _current_turn_tool_payloads(self, messages: list[BaseMessage]) -> list[dict[str, object]]:
        current_turn = self._messages_since_latest_human(messages)
        payloads: list[dict[str, object]] = []
        for message in current_turn:
            if not isinstance(message, ToolMessage):
                continue
            content = self._message_text(message)
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                payloads.append(parsed)
        return payloads

    def _messages_since_latest_human(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        latest_human_index = -1
        for index, message in enumerate(messages):
            if isinstance(message, HumanMessage):
                latest_human_index = index
        if latest_human_index == -1:
            return messages
        return messages[latest_human_index + 1 :]

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

    def _compact_messages(
        self,
        state: SkillAwareState,
        runtime: Runtime[GraphContext],
    ) -> dict:
        context = runtime.context
        messages = list(state.get("messages", []))

        if len(messages) < context.max_history_messages:
            return {}

        if not context.api_key:
            return {}

        # Find the latest HumanMessage index (pinned — always kept).
        pinned_index: int | None = None
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                pinned_index = i
                break

        # Identify the last 5 message indices (kept untouched).
        total = len(messages)
        tail_start = max(0, total - 5)
        tail_indices = set(range(tail_start, total))

        # Build the set of indices to keep.
        keep_indices = set(tail_indices)
        if pinned_index is not None:
            keep_indices.add(pinned_index)

        # Expand keep_indices to preserve tool-call integrity: an
        # AIMessage(tool_calls) and its ToolMessage responses must stay
        # together, otherwise the model API rejects the prompt.

        # Map tool_call_id → index of the parent AIMessage.
        tool_call_parent: dict[str, int] = {}
        # Map AIMessage index → set of its ToolMessage indices.
        ai_tool_children: dict[int, set[int]] = {}

        for i, msg in enumerate(messages):
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    ai_tool_children[i] = set()
                    for tc in tool_calls:
                        if isinstance(tc, dict) and "id" in tc:
                            tool_call_parent[tc["id"]] = i
            elif isinstance(msg, ToolMessage):
                tcid = getattr(msg, "tool_call_id", None)
                if tcid and tcid in tool_call_parent:
                    ai_tool_children.setdefault(tool_call_parent[tcid], set()).add(i)

        changed = True
        while changed:
            changed = False
            for idx in list(keep_indices):
                msg = messages[idx]
                # Keeping a ToolMessage → must also keep its parent AIMessage.
                if isinstance(msg, ToolMessage):
                    tcid = getattr(msg, "tool_call_id", None)
                    if tcid and tcid in tool_call_parent:
                        parent_idx = tool_call_parent[tcid]
                        if parent_idx not in keep_indices:
                            keep_indices.add(parent_idx)
                            changed = True
                # Keeping an AIMessage with tool_calls → must keep all its ToolMessages.
                if isinstance(msg, AIMessage) and idx in ai_tool_children:
                    for child_idx in ai_tool_children[idx]:
                        if child_idx not in keep_indices:
                            keep_indices.add(child_idx)
                            changed = True

        # Messages to summarize: everything NOT in keep_indices.
        to_summarize = [
            (i, messages[i])
            for i in range(total)
            if i not in keep_indices
        ]

        if not to_summarize:
            return {}

        old_summary = state.get("conversation_summary", "")

        try:
            new_summary = self._generate_compaction_summary(
                context, [msg for _, msg in to_summarize], old_summary
            )
        except Exception:
            logger.warning(
                "Message compaction summary failed; skipping compaction this cycle.",
                exc_info=True,
            )
            return {}

        # Build RemoveMessage entries for all summarized messages.
        removals: list[RemoveMessage] = []
        for _, msg in to_summarize:
            if getattr(msg, "id", None):
                removals.append(RemoveMessage(id=msg.id))

        return {
            "messages": removals,
            "conversation_summary": new_summary,
        }

    def _generate_compaction_summary(
        self,
        context: GraphContext,
        messages_to_summarize: list[BaseMessage],
        previous_summary: str,
    ) -> str:
        lines: list[str] = []
        for msg in messages_to_summarize:
            if isinstance(msg, HumanMessage):
                lines.append(f"User: {self._message_text(msg)}")
            elif isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None)
                text = self._message_text(msg)
                if text:
                    lines.append(f"Assistant: {text[:500]}")
                elif tool_calls:
                    names = ", ".join(
                        tc.get("name", "unknown") for tc in tool_calls if isinstance(tc, dict)
                    )
                    lines.append(f"Assistant: [called tools: {names}]")
            elif isinstance(msg, ToolMessage):
                lines.append(f"Tool result: {self._message_text(msg)[:300]}")
            elif isinstance(msg, SystemMessage):
                lines.append(f"System: {self._message_text(msg)[:200]}")

        conversation_block = "\n".join(lines)

        user_content = ""
        if previous_summary:
            user_content += (
                "Previous conversation summary:\n"
                f"{previous_summary}\n\n"
            )
        user_content += (
            "New messages to incorporate:\n"
            f"{conversation_block}"
        )

        summary_prompt = [
            SystemMessage(content=(
                "Summarize the following conversation history into a concise context "
                "paragraph (3-5 sentences). Capture: user questions asked, data queries "
                "performed and their outcomes, key findings, and any user preferences. "
                "Be factual. Output ONLY the summary."
            )),
            HumanMessage(content=user_content),
        ]

        response = self._get_model(context).invoke(summary_prompt)
        return self._message_text(response)

    def _parse_turn_classification(self, response_text: str) -> dict[str, object]:
        payload = self._extract_json_object(response_text)
        if payload is None:
            return {"skill_ids": [], "requires_data_pipeline": False}

        skill_ids = payload.get("skill_ids")
        if not isinstance(skill_ids, list):
            skill_ids = []

        parsed_ids: list[str] = []
        for item in skill_ids:
            if isinstance(item, str) and item.strip():
                parsed_ids.append(item.strip())

        requires_data_pipeline = payload.get("requires_data_pipeline", False)
        if not isinstance(requires_data_pipeline, bool):
            requires_data_pipeline = False

        return {
            "skill_ids": parsed_ids,
            "requires_data_pipeline": requires_data_pipeline,
        }

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


def _sanitize_tool_message_pairs(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Ensure every ToolMessage references a tool_call in the preceding AIMessage.

    When LangGraph's ``add_messages`` reducer merges session-store messages
    (plain ``AIMessage`` without ``tool_calls``) with checkpoint messages
    (which include ``AIMessage`` with ``tool_calls`` and ``ToolMessage``
    results), the merge can replace an ``AIMessage`` that *had* tool_calls
    with one that doesn't, leaving orphaned ``ToolMessage`` objects.

    The Anthropic API rejects conversations with mismatched
    ``tool_use`` / ``tool_result`` pairs, so we strip any ``ToolMessage``
    whose ``tool_call_id`` doesn't appear in the immediately preceding
    ``AIMessage.tool_calls``.  We also inject synthetic error
    ``ToolMessage`` objects when an ``AIMessage`` has ``tool_calls`` that
    lack matching ``ToolMessage`` replies (interrupted execution).
    """
    sanitized: list[BaseMessage] = []
    i = 0
    while i < len(messages):
        msg = messages[i]

        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            sanitized.append(msg)
            expected_ids: dict[str, str] = {}
            for tc in msg.tool_calls:
                tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                expected_ids[tc_id] = tc_name
            seen_ids: set[str] = set()

            # Consume following ToolMessages that belong to this AIMessage
            j = i + 1
            while j < len(messages) and isinstance(messages[j], ToolMessage):
                tm = messages[j]
                tc_id = getattr(tm, "tool_call_id", "")
                if tc_id in expected_ids:
                    sanitized.append(tm)
                    seen_ids.add(tc_id)
                else:
                    logger.debug(
                        "Dropping orphaned ToolMessage for tool_call_id=%s",
                        tc_id,
                    )
                j += 1

            # Inject synthetic results for any tool_calls without a response
            for missing_id, missing_name in expected_ids.items():
                if missing_id not in seen_ids:
                    logger.debug(
                        "Injecting synthetic ToolMessage for tool_call_id=%s",
                        missing_id,
                    )
                    sanitized.append(
                        ToolMessage(
                            content=json.dumps({
                                "ok": False,
                                "error_type": "interrupted",
                                "message": "Tool execution was interrupted by the user.",
                            }),
                            tool_call_id=missing_id,
                            name=missing_name,
                        )
                    )

            i = j  # skip past the consumed ToolMessages
            continue

        if isinstance(msg, ToolMessage):
            # Orphaned ToolMessage not preceded by an AIMessage with tool_calls
            logger.debug(
                "Dropping orphaned ToolMessage (no preceding tool_calls) "
                "for tool_call_id=%s",
                getattr(msg, "tool_call_id", ""),
            )
            i += 1
            continue

        sanitized.append(msg)
        i += 1

    return sanitized


def _database_display_name(backend: DatabaseBackend) -> str:
    normalized = str(backend).strip().lower()
    if normalized == "sqlite":
        return "SQLite"
    if normalized == "snowflake":
        return "Snowflake"
    return str(backend)


def _build_task_finished_details(
    node_name: str, captured_events: list[dict]
) -> dict[str, object]:
    """Summarise what happened during a node's execution for the log panel."""
    details: dict[str, object] = {}

    if node_name == "select_skills":
        # Look for skills_activated events emitted during this node
        for event in captured_events:
            if event.get("type") == "skills_activated":
                details["skills"] = event.get("skills", [])
                details["skill_names"] = event.get("names", [])
                break
        if "skill_names" not in details:
            details["skill_names"] = []

    elif node_name == "call_model":
        tool_calls = []
        for event in captured_events:
            if event.get("type") == "tool_call":
                tool_calls.append({
                    "tool_name": event.get("tool_name", ""),
                    "tool_args": event.get("tool_args", {}),
                })
        details["tool_calls"] = tool_calls

    elif node_name == "tools":
        tool_results = []
        for event in captured_events:
            if event.get("type") == "tool_result":
                tool_results.append({
                    "tool_name": event.get("tool_name", ""),
                    "ok": event.get("ok"),
                    "details": event.get("details", {}),
                })
        details["tool_results"] = tool_results

    return details


def _summarize_tool_result(parsed: dict | None, raw: str) -> dict[str, object]:
    """Extract the most useful fields from a tool result for the log panel."""
    if not isinstance(parsed, dict):
        return {"raw": raw[:1000]} if raw else {}

    summary: dict[str, object] = {}

    # SQL query results (execute_sql_query)
    if "row_count" in parsed:
        summary["database"] = parsed.get("database", "")
        summary["row_count"] = parsed.get("row_count")
        summary["columns"] = parsed.get("columns", [])
        summary["truncated"] = parsed.get("truncated", False)
        if parsed.get("artifact_id"):
            summary["artifact_id"] = parsed["artifact_id"]

    # Analysis results (run_analysis_script, read_analysis_result)
    if "result" in parsed and isinstance(parsed["result"], dict):
        result = parsed["result"]
        if result.get("summary"):
            summary["summary"] = str(result["summary"])[:500]
        if result.get("metrics"):
            summary["metrics"] = result["metrics"]
        if result.get("findings"):
            summary["findings_count"] = len(result["findings"])
        if result.get("table"):
            table = result["table"]
            if isinstance(table, list):
                summary["table_rows"] = len(table)
            elif isinstance(table, dict) and "rows" in table:
                summary["table_rows"] = len(table["rows"])
        if parsed.get("analysis_artifact_id"):
            summary["analysis_artifact_id"] = parsed["analysis_artifact_id"]

    # Python script results (run_python_script)
    if "stdout" in parsed:
        stdout = str(parsed.get("stdout", ""))
        stderr = str(parsed.get("stderr", ""))
        if stdout.strip():
            summary["stdout"] = stdout[:1000]
        if stderr.strip():
            summary["stderr"] = stderr[:1000]
        if parsed.get("artifacts"):
            summary["artifacts_count"] = len(parsed["artifacts"])

    # Error details
    if parsed.get("message"):
        summary["message"] = str(parsed["message"])[:500]
    if parsed.get("error_type"):
        summary["error_type"] = parsed["error_type"]
    if parsed.get("recoverable") is not None:
        summary["recoverable"] = parsed["recoverable"]

    return summary


