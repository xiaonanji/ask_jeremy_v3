from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


WORKING_MEMORY_SECTIONS = (
    "task_goal",
    "loaded_sources",
    "business_rules",
    "warehouse_mapping",
    "failed_attempts",
    "open_questions",
    "current_plan",
    "artifacts",
    "notes",
)

_DEFAULT_MAX_ITEMS = 24
_SECTION_MAX_ITEMS = {
    "task_goal": 4,
    "current_plan": 12,
    "open_questions": 12,
    "artifacts": 16,
}
_MAX_STRING_CHARS = 2_000
_MAX_RENDER_CHARS = 14_000


def empty_working_memory() -> dict[str, list[dict[str, Any]]]:
    return {section: [] for section in WORKING_MEMORY_SECTIONS}


def normalize_working_memory(value: object) -> dict[str, list[dict[str, Any]]]:
    memory = empty_working_memory()
    if not isinstance(value, dict):
        return memory

    for section in WORKING_MEMORY_SECTIONS:
        raw_items = value.get(section, [])
        if isinstance(raw_items, dict):
            raw_items = [raw_items]
        if not isinstance(raw_items, list):
            continue
        normalized_items: list[dict[str, Any]] = []
        for item in raw_items:
            if isinstance(item, dict):
                normalized_items.append(_normalize_item(item))
            elif isinstance(item, str) and item.strip():
                normalized_items.append(_normalize_item({"content": item.strip()}))
        memory[section] = _trim_section(section, _dedupe_items(normalized_items))
    return memory


def make_memory_update(
    *,
    section: str,
    content: object,
    source: str | None = None,
    confidence: str | None = None,
    pinned_by: str = "llm",
    mode: str = "append",
) -> dict[str, object]:
    normalized_section = section.strip().lower()
    if normalized_section not in WORKING_MEMORY_SECTIONS:
        raise ValueError(
            "Unknown working memory section. Use one of: "
            + ", ".join(WORKING_MEMORY_SECTIONS)
        )

    normalized_mode = mode.strip().lower() if isinstance(mode, str) else "append"
    if normalized_mode not in {"append", "replace"}:
        normalized_mode = "append"

    return {
        "section": normalized_section,
        "mode": normalized_mode,
        "item": _normalize_item(
            {
                "content": content,
                "source": source or "",
                "confidence": _normalize_confidence(confidence),
                "pinned_by": pinned_by,
            }
        ),
    }


def apply_memory_update(
    memory: object,
    update: object,
) -> tuple[dict[str, list[dict[str, Any]]], bool]:
    normalized_memory = normalize_working_memory(memory)
    if not isinstance(update, dict):
        return normalized_memory, False

    section = str(update.get("section", "")).strip().lower()
    if section not in WORKING_MEMORY_SECTIONS:
        return normalized_memory, False

    item = update.get("item")
    if not isinstance(item, dict):
        return normalized_memory, False

    before = json.dumps(normalized_memory.get(section, []), sort_keys=True, default=str)
    normalized_item = _normalize_item(item)
    mode = str(update.get("mode", "append")).strip().lower()
    if mode == "replace":
        normalized_memory[section] = [normalized_item]
    else:
        normalized_memory[section] = [
            *normalized_memory.get(section, []),
            normalized_item,
        ]
    normalized_memory[section] = _trim_section(
        section,
        _dedupe_items(normalized_memory[section]),
    )
    after = json.dumps(normalized_memory.get(section, []), sort_keys=True, default=str)
    return normalized_memory, before != after


def tool_payload_memory_updates(
    *,
    tool_name: str | None,
    payload: object,
) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        return []

    updates: list[dict[str, object]] = []
    inferred_tool = tool_name or _infer_tool_name(payload)

    memory_update = payload.get("memory_update")
    if inferred_tool == "pin_working_memory" and isinstance(memory_update, dict):
        updates.append(memory_update)

    if inferred_tool == "load_skill_reference" and payload.get("ok") is True:
        file_path = payload.get("file_path")
        if isinstance(file_path, str) and file_path:
            updates.append(
                make_memory_update(
                    section="loaded_sources",
                    content={
                        "source_type": "skill_reference",
                        "file_path": file_path,
                        "message": payload.get("message", ""),
                        "truncated": bool(payload.get("truncated", False)),
                    },
                    source=file_path,
                    confidence="high",
                    pinned_by="system",
                )
            )

    if inferred_tool == "execute_sql_query":
        if payload.get("ok") is True and isinstance(payload.get("artifact_id"), str):
            updates.append(
                make_memory_update(
                    section="artifacts",
                    content={
                        "artifact_type": "sql",
                        "artifact_id": payload.get("artifact_id"),
                        "database": payload.get("database"),
                        "row_count": payload.get("row_count"),
                        "columns": payload.get("columns", []),
                        "truncated": bool(payload.get("truncated", False)),
                    },
                    source="execute_sql_query",
                    confidence="high",
                    pinned_by="system",
                )
            )
        elif payload.get("ok") is False and payload.get("error_type"):
            updates.append(
                make_memory_update(
                    section="failed_attempts",
                    content={
                        "tool": "execute_sql_query",
                        "error_type": payload.get("error_type"),
                        "recoverable": payload.get("recoverable"),
                        "message": payload.get("message", ""),
                    },
                    source="execute_sql_query",
                    confidence="high",
                    pinned_by="system",
                )
            )

    if inferred_tool in {"run_analysis_script", "read_analysis_result"}:
        if payload.get("ok") is True and isinstance(payload.get("analysis_artifact_id"), str):
            result = payload.get("result")
            summary = result.get("summary", "") if isinstance(result, dict) else ""
            updates.append(
                make_memory_update(
                    section="artifacts",
                    content={
                        "artifact_type": "analysis",
                        "analysis_artifact_id": payload.get("analysis_artifact_id"),
                        "raw_artifact_id": payload.get("raw_artifact_id"),
                        "summary": summary,
                    },
                    source=inferred_tool,
                    confidence="high",
                    pinned_by="system",
                )
            )
        elif payload.get("ok") is False and payload.get("error_type"):
            updates.append(
                make_memory_update(
                    section="failed_attempts",
                    content={
                        "tool": inferred_tool,
                        "error_type": payload.get("error_type"),
                        "recoverable": payload.get("recoverable"),
                        "message": payload.get("message", ""),
                    },
                    source=inferred_tool,
                    confidence="high",
                    pinned_by="system",
                )
            )

    return updates


def render_working_memory(value: object) -> str:
    memory = normalize_working_memory(value)
    active_memory = {
        section: items
        for section, items in memory.items()
        if items
    }
    if not active_memory:
        rendered = "{}"
    else:
        rendered = json.dumps(active_memory, indent=2, ensure_ascii=False, default=str)

    if len(rendered) > _MAX_RENDER_CHARS:
        rendered = rendered[:_MAX_RENDER_CHARS] + "\n... [working memory truncated]"

    return (
        "Pinned task working memory survives conversation compaction and should be "
        "treated as operational truth for the current task.\n"
        "When you learn critical information needed across future iterations, call "
        "`pin_working_memory` to save it here. Pin business rules, source summaries, "
        "warehouse mappings, failed attempts, open questions, and the current plan.\n"
        "Current pinned memory JSON:\n"
        f"{rendered}"
    )


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "content": _coerce_content(item.get("content", "")),
        "source": _truncate_string(str(item.get("source", "") or "")),
        "confidence": _normalize_confidence(item.get("confidence")),
        "pinned_by": _truncate_string(str(item.get("pinned_by", "") or "")) or "llm",
    }
    for key, value in item.items():
        if key in normalized:
            continue
        normalized[key] = _truncate_value(value)
    return normalized


def _coerce_content(value: object) -> object:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ""
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return _truncate_string(stripped)
        return _truncate_value(parsed)
    return _truncate_value(value)


def _normalize_confidence(value: object) -> str:
    normalized = str(value or "medium").strip().lower()
    if normalized not in {"high", "medium", "low"}:
        return "medium"
    return normalized


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        signature = json.dumps(
            {
                "content": item.get("content"),
                "source": item.get("source", ""),
                "pinned_by": item.get("pinned_by", ""),
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(item)
    return deduped


def _trim_section(section: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_items = _SECTION_MAX_ITEMS.get(section, _DEFAULT_MAX_ITEMS)
    return items[-max_items:]


def _truncate_value(value: object) -> object:
    if isinstance(value, str):
        return _truncate_string(value)
    if isinstance(value, list):
        return [_truncate_value(item) for item in value[:50]]
    if isinstance(value, tuple):
        return [_truncate_value(item) for item in value[:50]]
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 50:
                break
            result[_truncate_string(str(key), 200)] = _truncate_value(item)
        return result
    return deepcopy(value)


def _truncate_string(value: str, max_chars: int = _MAX_STRING_CHARS) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "... [truncated]"


def _infer_tool_name(payload: dict[str, Any]) -> str | None:
    if isinstance(payload.get("memory_update"), dict):
        return "pin_working_memory"
    if "file_path" in payload and "content" in payload:
        return "load_skill_reference"
    if "artifact_id" in payload and "database" in payload:
        return "execute_sql_query"
    if payload.get("error_type") == "warehouse_table_policy_error":
        return "execute_sql_query"
    if "analysis_artifact_id" in payload or "raw_artifact_id" in payload:
        return "run_analysis_script"
    return None
