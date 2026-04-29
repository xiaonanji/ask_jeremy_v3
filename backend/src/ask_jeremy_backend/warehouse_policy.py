from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReferencedWarehouseTable:
    full_name: str
    reference_path: Path


class WarehouseTablePolicyError(ValueError):
    """Raised when SQL references a warehouse object outside the reference set."""


_FULL_NAME_RE = re.compile(r"Full name:\s*`([^`]+)`", re.IGNORECASE)
_REFERENCE_RE = re.compile(r"Reference:\s*`([^`]+)`", re.IGNORECASE)
_TOKEN_RE = re.compile(r'"(?:""|[^"])*"|[A-Za-z_][A-Za-z0-9_$]*|[(),.]')

_FROM_TERMINATORS = {
    "where",
    "group",
    "order",
    "having",
    "qualify",
    "limit",
    "union",
    "except",
    "intersect",
    "minus",
}

_SCALAR_FROM_FUNCTIONS = {
    "extract",
    "position",
    "substr",
    "substring",
    "trim",
}


def load_referenced_warehouse_tables(project_skill_root: Path) -> list[ReferencedWarehouseTable]:
    """Return warehouse tables that are explicitly paired with reference files."""

    skill_dir = project_skill_root / "snowflake-datawarehouse"
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.exists():
        return []

    tables: list[ReferencedWarehouseTable] = []
    seen: set[str] = set()
    pending_full_name: str | None = None

    for line in skill_path.read_text(encoding="utf-8").splitlines():
        full_match = _FULL_NAME_RE.search(line)
        if full_match:
            pending_full_name = full_match.group(1).strip()
            continue

        ref_match = _REFERENCE_RE.search(line)
        if ref_match and pending_full_name:
            reference_path = (skill_dir / ref_match.group(1).strip()).resolve()
            normalized = normalize_table_identifier(pending_full_name)
            if reference_path.exists() and reference_path.is_file() and normalized not in seen:
                tables.append(
                    ReferencedWarehouseTable(
                        full_name=pending_full_name,
                        reference_path=reference_path,
                    )
                )
                seen.add(normalized)
            pending_full_name = None

    return tables


def referenced_warehouse_table_names(project_skill_root: Path) -> list[str]:
    return [
        table.full_name
        for table in load_referenced_warehouse_tables(project_skill_root)
    ]


def snowflake_table_policy_prompt(project_skill_root: Path) -> str:
    tables = load_referenced_warehouse_tables(project_skill_root)
    if not tables:
        return (
            "For Snowflake data warehouse analysis, no referenced warehouse tables are "
            "currently configured. Do not query Snowflake tables. Ask the user to add "
            "or confirm a data warehouse table reference before continuing."
        )

    lines = [
        "For Snowflake data warehouse analysis, use only tables explicitly listed below.",
        "Each allowed table is paired with a local reference file.",
        "Do not discover, guess, SHOW, LIST, query INFORMATION_SCHEMA, query ACCOUNT_USAGE, or use unlisted warehouse tables.",
        "Use DESC TABLE only for an allowed referenced table.",
        "If the referenced tables do not cover the requested logic, stop and ask the user which table reference should be added.",
        "",
        "Allowed referenced Snowflake tables:",
    ]
    skill_dir = project_skill_root / "snowflake-datawarehouse"
    for table in tables:
        try:
            reference = table.reference_path.relative_to(skill_dir.resolve())
        except ValueError:
            reference = table.reference_path
        lines.append(f"- {table.full_name} (reference: {reference})")
    return "\n".join(lines)


def validate_snowflake_table_policy(query: str, project_skill_root: Path) -> None:
    """Validate that a Snowflake query only touches referenced warehouse tables."""

    tables = load_referenced_warehouse_tables(project_skill_root)
    if not tables:
        raise WarehouseTablePolicyError(
            "Snowflake table policy blocked this query because no referenced "
            "warehouse tables are configured. Ask the user to add or confirm a "
            "data warehouse table reference before continuing."
        )

    aliases = _allowed_reference_aliases(tables)
    cleaned_query = _mask_sql_comments_and_literals(query)
    tokens = _tokenize(cleaned_query)
    first_token = _first_keyword(tokens)

    if first_token in {"show", "list"}:
        raise WarehouseTablePolicyError(
            "Blocked due to non-reference warehouse table policy: SHOW and LIST "
            "statements can search or discover warehouse objects that are not "
            "paired with data warehouse reference files. Use DESC TABLE only for "
            "a referenced table, or ask the user to add the missing table reference."
        )

    if first_token in {"desc", "describe"}:
        target = _describe_target(tokens)
        if not target or not _is_allowed_reference(target, aliases):
            _raise_unreferenced_tables([target or "<missing DESCRIBE target>"], tables)
        return

    cte_names = _extract_cte_names(tokens)
    temp_target = _create_temp_table_target(tokens)
    ignored_names = set(cte_names)
    if temp_target:
        ignored_names.add(normalize_table_identifier(temp_target))

    references = _extract_table_references(tokens)
    blocked: list[str] = []
    for reference in references:
        normalized = normalize_table_identifier(reference)
        if normalized in ignored_names:
            continue
        if _is_local_intermediate_name(normalized):
            continue
        if not _is_allowed_reference(reference, aliases):
            blocked.append(reference)

    if blocked:
        _raise_unreferenced_tables(blocked, tables)


def normalize_table_identifier(value: str) -> str:
    parts = []
    for raw_part in value.split("."):
        part = raw_part.strip()
        if not part:
            continue
        if part.startswith('"') and part.endswith('"') and len(part) >= 2:
            part = part[1:-1].replace('""', '"')
        parts.append(part.lower())
    return ".".join(parts)


def _allowed_reference_aliases(
    tables: list[ReferencedWarehouseTable],
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    collisions: set[str] = set()
    for table in tables:
        normalized = normalize_table_identifier(table.full_name)
        parts = normalized.split(".")
        for index in range(len(parts)):
            alias = ".".join(parts[index:])
            existing = aliases.get(alias)
            if existing is not None and existing != normalized:
                collisions.add(alias)
            else:
                aliases[alias] = normalized

    for alias in collisions:
        aliases.pop(alias, None)
    return aliases


def _is_allowed_reference(reference: str, aliases: dict[str, str]) -> bool:
    return normalize_table_identifier(reference) in aliases


def _raise_unreferenced_tables(
    references: list[str],
    tables: list[ReferencedWarehouseTable],
) -> None:
    unique_references = []
    seen = set()
    for reference in references:
        normalized = normalize_table_identifier(reference)
        if normalized not in seen:
            unique_references.append(reference)
            seen.add(normalized)

    allowed = ", ".join(table.full_name for table in tables)
    blocked = ", ".join(unique_references)
    raise WarehouseTablePolicyError(
        "Blocked due to non-reference warehouse table(s): this Snowflake query "
        f"references table(s) that are not paired with data warehouse reference files: {blocked}. "
        "Use only referenced tables, or ask the user to add or confirm the missing "
        f"table reference before continuing. Referenced tables: {allowed}."
    )


def _mask_sql_comments_and_literals(query: str) -> str:
    chars = list(query)
    index = 0
    while index < len(chars):
        char = chars[index]
        next_char = chars[index + 1] if index + 1 < len(chars) else ""

        if char == "-" and next_char == "-":
            start = index
            index += 2
            while index < len(chars) and chars[index] not in "\r\n":
                index += 1
            for pos in range(start, index):
                chars[pos] = " "
            continue

        if char == "/" and next_char == "*":
            start = index
            index += 2
            while index + 1 < len(chars) and not (chars[index] == "*" and chars[index + 1] == "/"):
                index += 1
            index = min(len(chars), index + 2)
            for pos in range(start, index):
                chars[pos] = " "
            continue

        if char == "'":
            start = index
            index += 1
            while index < len(chars):
                if chars[index] == "'" and index + 1 < len(chars) and chars[index + 1] == "'":
                    index += 2
                    continue
                if chars[index] == "'":
                    index += 1
                    break
                index += 1
            for pos in range(start, min(index, len(chars))):
                chars[pos] = " "
            continue

        index += 1

    return "".join(chars)


def _tokenize(query: str) -> list[str]:
    return [match.group(0) for match in _TOKEN_RE.finditer(query)]


def _first_keyword(tokens: list[str]) -> str | None:
    for token in tokens:
        if _is_identifier_token(token):
            return _keyword(token)
    return None


def _keyword(token: str) -> str:
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1].replace('""', '"').lower()
    return token.lower()


def _is_identifier_token(token: str) -> bool:
    return bool(token) and token not in {"(", ")", ",", "."}


def _describe_target(tokens: list[str]) -> str | None:
    index = 0
    while index < len(tokens) and _keyword(tokens[index]) not in {"desc", "describe"}:
        index += 1
    if index >= len(tokens):
        return None
    index += 1
    if index < len(tokens) and _keyword(tokens[index]) in {"table", "view"}:
        index += 1
    target, _ = _read_identifier_path(tokens, index)
    return target


def _create_temp_table_target(tokens: list[str]) -> str | None:
    index = 0
    while index < len(tokens) and not _is_identifier_token(tokens[index]):
        index += 1
    if index >= len(tokens) or _keyword(tokens[index]) != "create":
        return None

    index += 1
    if index + 1 < len(tokens) and _keyword(tokens[index]) == "or" and _keyword(tokens[index + 1]) == "replace":
        index += 2
    if index >= len(tokens) or _keyword(tokens[index]) not in {"temp", "temporary"}:
        return None
    index += 1
    if index >= len(tokens) or _keyword(tokens[index]) != "table":
        return None
    index += 1
    target, _ = _read_identifier_path(tokens, index)
    return target


def _extract_cte_names(tokens: list[str]) -> set[str]:
    names: set[str] = set()
    index = 0
    while index < len(tokens):
        if _keyword(tokens[index]) != "with":
            index += 1
            continue

        index += 1
        if index < len(tokens) and _keyword(tokens[index]) == "recursive":
            index += 1

        while index < len(tokens):
            if not _is_identifier_token(tokens[index]):
                break
            names.add(normalize_table_identifier(tokens[index]))
            index += 1

            if index < len(tokens) and tokens[index] == "(":
                index = _skip_parenthesized(tokens, index)

            if index >= len(tokens) or _keyword(tokens[index]) != "as":
                break
            index += 1

            if index >= len(tokens) or tokens[index] != "(":
                break
            index = _skip_parenthesized(tokens, index)

            if index < len(tokens) and tokens[index] == ",":
                index += 1
                continue
            break
    return names


def _extract_table_references(tokens: list[str]) -> list[str]:
    references: list[str] = []
    from_depths: set[int] = set()
    depth = 0
    index = 0

    while index < len(tokens):
        token = tokens[index]
        token_keyword = _keyword(token)

        if token == "(":
            depth += 1
            index += 1
            continue

        if token == ")":
            depth = max(0, depth - 1)
            from_depths = {item for item in from_depths if item <= depth}
            index += 1
            continue

        if token_keyword in _FROM_TERMINATORS:
            from_depths.discard(depth)

        if token_keyword == "from" and not _is_scalar_function_from(tokens, index):
            from_depths.add(depth)
            reference, _ = _read_relation_after(tokens, index + 1)
            if reference:
                references.append(reference)
            index += 1
            continue

        if token_keyword == "join":
            reference, _ = _read_relation_after(tokens, index + 1)
            if reference:
                references.append(reference)
            index += 1
            continue

        if token == "," and depth in from_depths:
            reference, _ = _read_relation_after(tokens, index + 1)
            if reference:
                references.append(reference)

        index += 1

    return references


def _read_relation_after(tokens: list[str], index: int) -> tuple[str | None, int]:
    while index < len(tokens) and _keyword(tokens[index]) in {"only", "lateral"}:
        index += 1

    if index >= len(tokens) or tokens[index] == "(":
        return None, index

    if _keyword(tokens[index]) == "table" and index + 1 < len(tokens) and tokens[index + 1] == "(":
        return None, index

    reference, next_index = _read_identifier_path(tokens, index)
    return reference, next_index


def _read_identifier_path(tokens: list[str], index: int) -> tuple[str | None, int]:
    if index >= len(tokens) or not _is_identifier_token(tokens[index]):
        return None, index

    parts = [tokens[index]]
    index += 1
    while index + 1 < len(tokens) and tokens[index] == "." and _is_identifier_token(tokens[index + 1]):
        parts.append(tokens[index + 1])
        index += 2

    return ".".join(parts), index


def _skip_parenthesized(tokens: list[str], index: int) -> int:
    depth = 0
    while index < len(tokens):
        if tokens[index] == "(":
            depth += 1
        elif tokens[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def _is_scalar_function_from(tokens: list[str], index: int) -> bool:
    depth = 0
    cursor = index - 1
    while cursor >= 0:
        token = tokens[cursor]
        if token == ")":
            depth += 1
        elif token == "(":
            if depth == 0:
                function_index = cursor - 1
                if function_index >= 0 and _is_identifier_token(tokens[function_index]):
                    return _keyword(tokens[function_index]) in _SCALAR_FROM_FUNCTIONS
                return False
            depth -= 1
        cursor -= 1
    return False


def _is_local_intermediate_name(normalized: str) -> bool:
    return normalized.split(".")[-1].startswith("ask_jeremy_")
