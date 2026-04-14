from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import Settings

_MAX_ANALYSIS_JSON_BYTES = 50_000
_MAX_SUMMARY_CHARS = 2_000
_MAX_LIST_ITEMS = 12
_MAX_STRING_CHARS = 300
_MAX_ALLOWED_MENTIONS = 100
_MAX_TABLE_ROWS = 500
_MAX_TABLE_COLS = 20
_RAW_DATA_KEYS = {
    "rows",
    "raw_rows",
    "data",
    "records",
    "record_set",
    "result_rows",
    "sample_rows",
    "preview_rows",
    "dataframe",
}


class AnalysisArtifactError(RuntimeError):
    """Raised when an analysis artifact is missing or invalid."""


@dataclass(frozen=True)
class AnalysisArtifact:
    analysis_artifact_id: str
    raw_artifact_id: str
    artifact_dir: Path
    script_path: Path
    output_path: Path
    stdout_path: Path
    stderr_path: Path
    created_at: datetime


def create_analysis_artifact(
    *,
    settings: Settings,
    session_id: str,
    raw_artifact_id: str,
    script: str,
    stdout: str,
    stderr: str,
) -> AnalysisArtifact:
    created_at = datetime.now(timezone.utc)
    artifact_dir = _analysis_artifact_dir(settings, session_id, created_at)
    script_path = artifact_dir / "analysis.py"
    output_path = artifact_dir / "analysis_result.json"
    stdout_path = artifact_dir / "stdout.txt"
    stderr_path = artifact_dir / "stderr.txt"

    script_path.write_text(script, encoding="utf-8")
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")

    return AnalysisArtifact(
        analysis_artifact_id=artifact_dir.name,
        raw_artifact_id=raw_artifact_id,
        artifact_dir=artifact_dir,
        script_path=script_path,
        output_path=output_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        created_at=created_at,
    )


def raw_sql_artifact_paths(
    settings: Settings,
    session_id: str,
    raw_artifact_id: str,
) -> tuple[Path, Path]:
    artifact_dir = settings.session_root / session_id / "artifacts" / "sql" / raw_artifact_id
    json_path = artifact_dir / "result.json"
    csv_path = artifact_dir / "result.csv"
    if not json_path.exists() or not csv_path.exists():
        raise AnalysisArtifactError(
            f"SQL artifact was not found for analysis: {raw_artifact_id}"
        )
    return json_path, csv_path


def load_analysis_result(
    settings: Settings,
    session_id: str,
    analysis_artifact_id: str,
) -> dict[str, Any]:
    output_path = (
        settings.session_root
        / session_id
        / "artifacts"
        / "analysis"
        / analysis_artifact_id
        / "analysis_result.json"
    )
    if not output_path.exists():
        raise AnalysisArtifactError(
            f"Analysis output was not found: {analysis_artifact_id}"
        )

    raw_text = output_path.read_text(encoding="utf-8")
    if len(raw_text.encode("utf-8")) > _MAX_ANALYSIS_JSON_BYTES:
        raise AnalysisArtifactError(
            "Analysis output is too large to expose to the model safely."
        )

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AnalysisArtifactError("Analysis output is not valid JSON.") from exc

    return validate_analysis_result(payload)


def validate_analysis_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AnalysisArtifactError("Analysis output must be a JSON object.")

    normalized_payload = _normalize_payload(payload)

    summary = _validated_summary(normalized_payload)
    findings = _validated_string_list(
        normalized_payload.get("findings", []),
        field_name="findings",
    )
    caveats = _validated_string_list(
        normalized_payload.get("caveats", []),
        field_name="caveats",
    )
    uncertainty = _validated_string_list(
        normalized_payload.get("uncertainty", []),
        field_name="uncertainty",
    )
    needs_user_input = bool(normalized_payload.get("needs_user_input", False))

    follow_up_question = normalized_payload.get("follow_up_question")
    if follow_up_question in (None, ""):
        normalized_follow_up: str | None = None
    else:
        normalized_follow_up = _validated_string(
            follow_up_question,
            field_name="follow_up_question",
            required=False,
        )

    if needs_user_input and not normalized_follow_up:
        raise AnalysisArtifactError(
            "Analysis output must include follow_up_question when needs_user_input is true."
        )

    metrics = _validated_small_mapping(
        normalized_payload.get("metrics", {}),
        field_name="metrics",
    )
    evidence = _validated_evidence_list(normalized_payload.get("evidence", []))
    allowed_mentions = _validated_allowed_mentions(
        normalized_payload.get("allowed_mentions", []),
    )
    table = _validated_table(normalized_payload.get("table"))

    normalized = {
        "summary": summary,
        "metrics": metrics,
        "findings": findings,
        "evidence": evidence,
        "caveats": caveats,
        "uncertainty": uncertainty,
        "needs_user_input": needs_user_input,
        "follow_up_question": normalized_follow_up,
        "allowed_mentions": allowed_mentions,
        "table": table,
    }

    encoded = json.dumps(normalized, ensure_ascii=True)
    if len(encoded.encode("utf-8")) > _MAX_ANALYSIS_JSON_BYTES:
        raise AnalysisArtifactError(
            "Analysis output is too large after normalization."
        )

    return normalized


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "summary",
        "metrics",
        "findings",
        "evidence",
        "caveats",
        "uncertainty",
        "needs_user_input",
        "follow_up_question",
        "allowed_mentions",
        "table",
    }

    normalized = dict(payload)
    metrics = normalized.get("metrics")
    if metrics is None:
        metrics = {}
    elif not isinstance(metrics, dict):
        metrics = {"value": metrics}
    else:
        metrics = dict(metrics)

    findings = _coerce_text_list(
        normalized.pop("findings", None),
        fallback_field_names=("notes", "insights", "observations"),
        source=normalized,
    )
    caveats = _coerce_text_list(
        normalized.pop("caveats", None),
        fallback_field_names=("caveat", "source_note"),
        source=normalized,
    )
    uncertainty = _coerce_text_list(
        normalized.pop("uncertainty", None),
        fallback_field_names=(),
        source=normalized,
    )

    evidence = normalized.pop("evidence", [])
    table = normalized.pop("table", None)
    summary = normalized.get("summary")
    if summary is None and metrics:
        summary = _summary_from_metrics(metrics)

    extra_allowed_mentions = _coerce_text_list(
        normalized.pop("allowed_mentions", None),
        fallback_field_names=(),
        source=normalized,
    )

    unsupported_keys: list[str] = []
    for key in list(normalized.keys()):
        if key in allowed_keys or key == "summary":
            continue
        lower_key = key.strip().lower()
        value = normalized.pop(key)
        if lower_key in _RAW_DATA_KEYS:
            raise AnalysisArtifactError(
                "Analysis output contains unsupported keys: " + key
            )
        if lower_key == "question":
            continue
        if lower_key in {"notes", "insights", "observations", "caveat", "source_note"}:
            continue
        if lower_key in {"follow_up_question", "needs_user_input"}:
            normalized[lower_key] = value
            continue
        if _is_metric_candidate(value):
            metrics[key] = value
            continue
        unsupported_keys.append(key)

    if unsupported_keys:
        raise AnalysisArtifactError(
            "Analysis output contains unsupported keys: "
            + ", ".join(sorted(unsupported_keys))
        )

    normalized["summary"] = summary
    normalized["metrics"] = metrics
    normalized["findings"] = findings
    normalized["caveats"] = caveats
    normalized["uncertainty"] = uncertainty
    normalized["evidence"] = _coerce_evidence(evidence)
    normalized["allowed_mentions"] = extra_allowed_mentions
    normalized["table"] = table
    return normalized


def extract_allowed_mentions(payload: dict[str, Any]) -> set[str]:
    explicit = {
        item.strip()
        for item in payload.get("allowed_mentions", [])
        if isinstance(item, str) and item.strip()
    }
    if explicit:
        return explicit

    discovered: set[str] = set()
    for text in _collect_strings(payload):
        cleaned = " ".join(text.split()).strip()
        if len(cleaned) < 3:
            continue
        if any(char.isdigit() for char in cleaned):
            continue
        if cleaned.lower() in {"summary", "findings", "evidence"}:
            continue
        if re.search(r"[A-Z][a-z]+(?:\s+[A-Z][A-Za-z'&.-]+)+", cleaned):
            discovered.add(cleaned)
    return discovered


def _analysis_artifact_dir(
    settings: Settings,
    session_id: str,
    created_at: datetime,
) -> Path:
    root = settings.session_root / session_id / "artifacts" / "analysis"
    root.mkdir(parents=True, exist_ok=True)
    artifact_id = f"analysis_{created_at.strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}"
    artifact_dir = root / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=False)
    return artifact_dir


def _validated_string(value: Any, *, field_name: str, required: bool) -> str:
    if value is None:
        if required:
            raise AnalysisArtifactError(f"{field_name} is required in analysis output.")
        return ""
    if not isinstance(value, str):
        raise AnalysisArtifactError(f"{field_name} must be a string.")
    normalized = " ".join(value.split()).strip()
    if required and not normalized:
        raise AnalysisArtifactError(f"{field_name} must not be empty.")
    limit = _MAX_SUMMARY_CHARS if field_name == "summary" else _MAX_STRING_CHARS
    if len(normalized) > limit:
        raise AnalysisArtifactError(f"{field_name} is too large.")
    return normalized


def _validated_summary(payload: dict[str, Any]) -> str:
    summary = payload.get("summary")
    if isinstance(summary, str):
        return _validated_string(summary, field_name="summary", required=True)
    if summary is None:
        generated = _summary_from_metrics(payload.get("metrics", {}))
        return _validated_string(generated, field_name="summary", required=True)
    if isinstance(summary, dict):
        generated = _summary_from_metrics(summary)
        return _validated_string(generated, field_name="summary", required=True)
    return _validated_string(str(summary), field_name="summary", required=True)


def _validated_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AnalysisArtifactError(f"{field_name} must be a list.")
    if len(value) > _MAX_LIST_ITEMS:
        raise AnalysisArtifactError(f"{field_name} has too many items.")
    return [
        _validated_string(item, field_name=field_name, required=True)
        for item in value
    ]


def _validated_small_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AnalysisArtifactError(f"{field_name} must be an object.")
    if len(value) > _MAX_LIST_ITEMS:
        raise AnalysisArtifactError(f"{field_name} contains too many entries.")
    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise AnalysisArtifactError(f"{field_name} keys must be non-empty strings.")
        normalized[key.strip()] = _validated_small_value(item, field_name=field_name)
    return normalized


def _validated_evidence_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AnalysisArtifactError("evidence must be a list.")
    if len(value) > _MAX_LIST_ITEMS:
        raise AnalysisArtifactError("evidence has too many items.")

    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise AnalysisArtifactError("Each evidence item must be an object.")
        label_value = item.get("label")
        if label_value is None:
            label_value = item.get("type") or item.get("name") or item.get("key")
        label = _validated_string(label_value, field_name="evidence.label", required=True)
        detail = _validated_string(
            item.get("detail", ""),
            field_name="evidence.detail",
            required=False,
        )
        value_payload = _validated_small_value(item.get("value"), field_name="evidence.value")
        normalized.append(
            {
                "label": label,
                "detail": detail,
                "value": value_payload,
            }
        )
    return normalized


def _validated_allowed_mentions(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AnalysisArtifactError("allowed_mentions must be a list.")
    if len(value) > _MAX_ALLOWED_MENTIONS:
        raise AnalysisArtifactError("allowed_mentions has too many items.")
    return [
        _validated_string(item, field_name="allowed_mentions", required=True)
        for item in value
    ]


def _validated_table(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None

    # Accept list of row dicts → convert to {headers, rows}
    if isinstance(value, list):
        if len(value) == 0:
            return {"headers": [], "rows": []}
        if len(value) > _MAX_TABLE_ROWS:
            raise AnalysisArtifactError(
                f"table has too many rows (max {_MAX_TABLE_ROWS})."
            )
        first = value[0]
        if not isinstance(first, dict):
            raise AnalysisArtifactError(
                "table list rows must be dicts; use {headers, rows} for list-of-lists."
            )
        headers = list(first.keys())
        if len(headers) > _MAX_TABLE_COLS:
            raise AnalysisArtifactError(f"table has too many columns (max {_MAX_TABLE_COLS}).")
        rows: list[list[Any]] = []
        for row in value:
            if not isinstance(row, dict):
                raise AnalysisArtifactError("All table rows must be dicts.")
            rows.append([row.get(h) for h in headers])
        return {"headers": [str(h) for h in headers], "rows": rows}

    # Accept {headers, rows} format
    if isinstance(value, dict):
        headers_raw = value.get("headers")
        rows_raw = value.get("rows")
        if headers_raw is None or rows_raw is None:
            raise AnalysisArtifactError(
                "table object must have 'headers' (list) and 'rows' (list of lists or dicts)."
            )
        if not isinstance(headers_raw, list):
            raise AnalysisArtifactError("table.headers must be a list of strings.")
        if not isinstance(rows_raw, list):
            raise AnalysisArtifactError("table.rows must be a list.")
        if len(headers_raw) > _MAX_TABLE_COLS:
            raise AnalysisArtifactError(f"table has too many columns (max {_MAX_TABLE_COLS}).")
        if len(rows_raw) > _MAX_TABLE_ROWS:
            raise AnalysisArtifactError(f"table has too many rows (max {_MAX_TABLE_ROWS}).")
        validated_headers = [str(h) for h in headers_raw]
        validated_rows: list[list[Any]] = []
        for row in rows_raw:
            if isinstance(row, dict):
                validated_rows.append([row.get(h) for h in validated_headers])
            elif isinstance(row, list):
                validated_rows.append(list(row))
            else:
                raise AnalysisArtifactError(
                    "Each table row must be a list or a dict."
                )
        return {"headers": validated_headers, "rows": validated_rows}

    raise AnalysisArtifactError(
        "table must be a list of row dicts or an object with 'headers' and 'rows'."
    )


def _validated_small_value(value: Any, *, field_name: str, depth: int = 0) -> Any:
    if depth > 3:
        raise AnalysisArtifactError(f"{field_name} exceeds maximum nesting depth.")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _validated_string(value, field_name=field_name, required=False)
    if isinstance(value, list):
        if len(value) > _MAX_LIST_ITEMS:
            raise AnalysisArtifactError(f"{field_name} contains too many list items.")
        return [
            _validated_small_value(item, field_name=field_name, depth=depth + 1)
            for item in value
        ]
    if isinstance(value, dict):
        if len(value) > _MAX_LIST_ITEMS:
            raise AnalysisArtifactError(f"{field_name} contains too many object entries.")
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise AnalysisArtifactError(f"{field_name} contains an invalid key.")
            normalized[key.strip()] = _validated_small_value(
                item,
                field_name=field_name,
                depth=depth + 1,
            )
        return normalized
    raise AnalysisArtifactError(f"{field_name} contains an unsupported value type.")


def _collect_strings(value: Any) -> list[str]:
    collected: list[str] = []
    if isinstance(value, str):
        collected.append(value)
    elif isinstance(value, list):
        for item in value:
            collected.extend(_collect_strings(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            collected.append(str(key))
            collected.extend(_collect_strings(item))
    return collected


def _coerce_text_list(
    value: Any,
    *,
    fallback_field_names: tuple[str, ...],
    source: dict[str, Any],
) -> list[str]:
    candidates: list[str] = []
    if value is not None:
        candidates.extend(_value_to_strings(value))
    for field_name in fallback_field_names:
        if field_name in source:
            candidates.extend(_value_to_strings(source.pop(field_name)))
    return candidates


def _value_to_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        collected: list[str] = []
        for item in value:
            if isinstance(item, str):
                collected.append(item)
            elif isinstance(item, dict):
                collected.append(json.dumps(item, ensure_ascii=True))
            else:
                collected.append(str(item))
        return collected
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=True)]
    return [str(value)]


def _coerce_evidence(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [
            {"label": str(key), "detail": "", "value": item}
            for key, item in value.items()
        ]
    if isinstance(value, list):
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, dict):
                normalized.append(item)
            elif isinstance(item, str):
                normalized.append(
                    {"label": f"evidence_{index}", "detail": item, "value": None}
                )
            else:
                normalized.append(
                    {"label": f"evidence_{index}", "detail": "", "value": item}
                )
        return normalized
    if isinstance(value, str):
        return [{"label": "evidence_1", "detail": value, "value": None}]
    return [{"label": "evidence_1", "detail": "", "value": value}]


def _is_metric_candidate(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, list):
        return len(value) <= _MAX_LIST_ITEMS and all(
            item is None or isinstance(item, (bool, int, float, str))
            for item in value
        )
    if isinstance(value, dict):
        return len(value) <= _MAX_LIST_ITEMS and all(
            isinstance(key, str) and item is not None and isinstance(item, (bool, int, float, str))
            for key, item in value.items()
        )
    return False


def _summary_from_metrics(metrics: Any) -> str:
    if not isinstance(metrics, dict) or not metrics:
        return "Analysis completed."
    parts: list[str] = []
    for key, value in list(metrics.items())[:3]:
        parts.append(f"{key}={value}")
    return "Analysis completed with metrics: " + ", ".join(parts) + "."
