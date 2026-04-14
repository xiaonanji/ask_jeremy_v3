from __future__ import annotations

import json
import re
from typing import Any

from .analysis import extract_allowed_mentions

_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?(?![A-Za-z0-9_])")
_PHRASE_PATTERN = re.compile(r"\b[A-Z][A-Za-z'&.-]+(?:\s+[A-Z][A-Za-z'&.-]+)+\b")
_IGNORED_PHRASES = {
    "Plan",
    "Current Date",
    "Current Time",
    "Current Timezone",
}


def verify_answer_against_analysis(answer: str, analysis_result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    serialized_payload = json.dumps(analysis_result, ensure_ascii=True)

    unexpected_numbers = sorted(
        {
            match.group(0)
            for match in _NUMBER_PATTERN.finditer(answer)
            if match.group(0) not in serialized_payload
        }
    )
    if unexpected_numbers:
        errors.append(
            "Answer mentions numbers that do not appear in the current analysis result: "
            + ", ".join(unexpected_numbers[:8])
        )

    allowed_mentions = extract_allowed_mentions(analysis_result)
    if allowed_mentions:
        unexpected_phrases = sorted(
            {
                phrase.strip()
                for phrase in _PHRASE_PATTERN.findall(answer)
                if phrase.strip() not in allowed_mentions
                and phrase.strip() not in _IGNORED_PHRASES
            }
        )
        if unexpected_phrases:
            errors.append(
                "Answer mentions named entities that are not grounded in the analysis result: "
                + ", ".join(unexpected_phrases[:8])
            )

    if _analysis_requires_truncation_disclosure(analysis_result) and not _answer_mentions_truncation(answer):
        errors.append(
            "Answer does not disclose that SQL materialization was truncated to the configured row limit."
        )

    return errors


def _analysis_requires_truncation_disclosure(analysis_result: dict[str, Any]) -> bool:
    metrics = analysis_result.get("metrics", {})
    if isinstance(metrics, dict) and metrics.get("sql_result_truncated") is True:
        return True
    for item in analysis_result.get("evidence", []):
        if isinstance(item, dict) and item.get("label") == "sql_result_truncated":
            return True
    return False


def _answer_mentions_truncation(answer: str) -> bool:
    normalized = answer.lower()
    markers = (
        "truncated",
        "limited to the first",
        "limited to first",
        "row limit",
        "materialized",
        "returned rows",
    )
    return any(marker in normalized for marker in markers)
