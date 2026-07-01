from __future__ import annotations

import json
import re

_INTERFACE_CONTEXT_MAX_TOP_VALUES = 5
_INTERFACE_CONTEXT_MAX_SAMPLE_ROWS = 5

_RESULT_FIRST_OPERATIONAL_SUMMARY_KEYS = frozenset(
    {
        "row_count",
        "highest_null_ratio_column",
        "mixed_format_columns",
    }
)


def _formatted_presented_option_lines(
    session,
    rendered_options: list[dict[str, object]] | None = None,
) -> list[str]:
    options = rendered_options
    if options is None:
        try:
            options = session.rendered_presented_options()
        except Exception:
            options = []
    return [
        f"{int(option.get('index', 0))}. {str(option.get('display_text', option.get('label', ''))).strip()}"
        for option in options or []
        if int(option.get("index", 0)) > 0 and str(option.get("display_text", option.get("label", ""))).strip()
    ]


def _align_reply_numbering_with_presented_options(session, text: str) -> str:
    rendered_options = []
    try:
        rendered_options = session.rendered_presented_options()
    except Exception:
        rendered_options = []
    if not rendered_options:
        return text
    lines = text.splitlines()
    numbered_line_positions = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^\s*\d+\.\s+\S+", line)
    ]
    if not numbered_line_positions:
        return text
    start = numbered_line_positions[0]
    end = start
    for position in numbered_line_positions[1:]:
        if position == end + 1:
            end = position
            continue
        break
    numbered_block = lines[start : end + 1]
    canonical_lines = _formatted_presented_option_lines(session, rendered_options)
    actual_indices = []
    for line in numbered_block:
        match = re.match(r"^\s*(\d+)\.\s+\S+", line)
        if match:
            actual_indices.append(int(match.group(1)))
    expected_indices = [int(option.get("index", 0)) for option in rendered_options]
    if actual_indices != expected_indices[: len(actual_indices)] or numbered_block != canonical_lines[: len(numbered_block)]:
        normalized_lines = lines[:start] + canonical_lines + lines[end + 1 :]
        return "\n".join(normalized_lines).strip()
    normalized_lines = lines[:start] + canonical_lines + lines[end + 1 :]
    return "\n".join(normalized_lines).strip()


def sanitize_interface_reply(session, reply: object) -> str:
    from agnostic.interface.presenter import (
        _extract_action_marker_from_reply,
        build_unmapped_analysis_reply,
    )

    text = "" if reply is None else str(reply).strip()
    if not text or text.lower() == "none":
        return build_unmapped_analysis_reply(session)
    clean_text, _ = _extract_action_marker_from_reply(text)
    return _align_reply_numbering_with_presented_options(session, clean_text)


def _mixed_format_warnings_from_result_context(result_context: str) -> list[str]:
    try:
        payload = json.loads(result_context)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []

    operational_summary = payload.get("operational_summary")
    if not isinstance(operational_summary, dict):
        raw_result = payload.get("raw_result")
        if isinstance(raw_result, dict):
            operational_summary = raw_result.get("operational_summary")
    if not isinstance(operational_summary, dict):
        return []

    mixed_format_columns = operational_summary.get("mixed_format_columns")
    if not isinstance(mixed_format_columns, list) or not mixed_format_columns:
        return []

    warnings: list[str] = []
    for item in mixed_format_columns:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column", "")).strip()
        dominant_pattern = str(item.get("dominant_pattern", "")).strip()
        secondary_pattern = str(item.get("secondary_pattern", "")).strip()
        if not column or not dominant_pattern or not secondary_pattern:
            continue
        example_dominant = str(item.get("example_dominant", "")).strip()
        example_secondary = str(item.get("example_secondary", "")).strip()
        detail = (
            f"ex.: {example_dominant} ({dominant_pattern}) e {example_secondary} ({secondary_pattern})"
            if example_dominant and example_secondary
            else f"padrões {dominant_pattern} e {secondary_pattern}"
        )
        warnings.append(
            f"A coluna {column} mistura formatos estruturais distintos ({detail})."
        )
    return warnings


def _sanitize_interface_payload(payload: object) -> object:
    if isinstance(payload, list):
        return [_sanitize_interface_payload(item) for item in payload]
    if not isinstance(payload, dict):
        return payload
    sanitized: dict[str, object] = {}
    for key, value in payload.items():
        normalized_key = str(key)
        if normalized_key in {"cache_key", "source_node_id", "status"}:
            continue
        if normalized_key == "id" and isinstance(value, str) and value.startswith("req_"):
            continue
        sanitized[normalized_key] = _sanitize_interface_payload(value)
    return sanitized


def _compress_layer1_metrics_for_context(metrics: dict[str, object]) -> dict[str, object]:
    compressed: dict[str, object] = {}
    for key, value in metrics.items():
        if value is None or value == 0.0:
            continue
        if key == "frequency" and isinstance(value, dict):
            frequency = {
                nested_key: nested_value
                for nested_key, nested_value in value.items()
                if nested_key != "counts" and nested_value is not None and nested_value != 0.0
            }
            if frequency:
                compressed[key] = frequency
            continue
        if isinstance(value, dict):
            nested = _compress_layer1_metrics_for_context(value)
            if nested:
                compressed[key] = nested
            continue
        compressed[key] = value
    return compressed


def _compress_column_profile_for_context(profile: dict[str, object]) -> dict[str, object]:
    compressed: dict[str, object] = {}
    for key, value in profile.items():
        if key == "top_values" and isinstance(value, list):
            compressed[key] = value[:_INTERFACE_CONTEXT_MAX_TOP_VALUES]
            continue
        if key == "heuristics" and isinstance(value, list):
            compressed[key] = [
                item
                for item in value
                if isinstance(item, dict) and item.get("triggered") is True
            ]
            continue
        if key == "layer1_metrics" and isinstance(value, dict):
            layer1 = _compress_layer1_metrics_for_context(value)
            if layer1:
                compressed[key] = layer1
            continue
        if key == "frequency" and isinstance(value, dict):
            frequency = {
                nested_key: nested_value
                for nested_key, nested_value in value.items()
                if nested_key != "counts" and nested_value is not None and nested_value != 0.0
            }
            if frequency:
                compressed[key] = frequency
            continue
        compressed[key] = value
    return compressed


def _compress_column_profiles_for_context(profiles: dict[str, object]) -> dict[str, object]:
    return {
        column_name: _compress_column_profile_for_context(column_profile)
        if isinstance(column_profile, dict)
        else column_profile
        for column_name, column_profile in profiles.items()
    }


def _deep_compress_frequency_counts_in_payload(payload: object) -> object:
    if isinstance(payload, list):
        return [_deep_compress_frequency_counts_in_payload(item) for item in payload]
    if not isinstance(payload, dict):
        return payload
    compressed: dict[str, object] = {}
    for key, value in payload.items():
        if key == "frequency" and isinstance(value, dict):
            frequency = {
                nested_key: nested_value
                for nested_key, nested_value in value.items()
                if nested_key != "counts" and nested_value is not None and nested_value != 0.0
            }
            if frequency:
                compressed[key] = frequency
            continue
        if key == "layer1_metrics" and isinstance(value, dict):
            layer1 = _compress_layer1_metrics_for_context(value)
            if layer1:
                compressed[key] = layer1
            continue
        if isinstance(value, (dict, list)):
            compressed[key] = _deep_compress_frequency_counts_in_payload(value)
            continue
        compressed[key] = value
    return compressed


def _compress_raw_result_for_interface_context(
    payload: dict[str, object],
) -> tuple[dict[str, object], bool, int | None]:
    sanitized = _sanitize_interface_payload(payload)
    if not isinstance(sanitized, dict):
        return {}, False, None
    deep_compressed = _deep_compress_frequency_counts_in_payload(sanitized)
    if not isinstance(deep_compressed, dict):
        return {}, False, None
    compressed = dict(deep_compressed)
    rows = compressed.get("rows")
    if isinstance(rows, list):
        compressed["rows"] = rows[:_INTERFACE_CONTEXT_MAX_SAMPLE_ROWS]

    has_more_columns = False
    total_columns: int | None = None
    operational_summary = compressed.get("operational_summary")
    if isinstance(operational_summary, dict):
        operational_summary = dict(operational_summary)
        column_profiles = operational_summary.get("column_profiles")
        if isinstance(column_profiles, dict) and column_profiles:
            operational_summary["column_profiles"] = _compress_column_profiles_for_context(column_profiles)
        operational_summary.pop("distinct_values_by_column", None)
        compressed["operational_summary"] = operational_summary
    return compressed, has_more_columns, total_columns


def _compress_interface_result_payload(payload: dict[str, object]) -> dict[str, object]:
    mode = str(payload.get("mode", "")).strip()
    if mode == "result_first":
        compressed = dict(payload)
        raw_result = compressed.get("raw_result")
        if isinstance(raw_result, dict):
            compressed_raw, has_more_columns, total_columns = _compress_raw_result_for_interface_context(raw_result)
            compressed["raw_result"] = compressed_raw
            if has_more_columns and total_columns is not None:
                compressed["has_more_columns"] = True
                compressed["total_columns"] = total_columns
        operational_summary = compressed.get("operational_summary")
        if isinstance(operational_summary, dict):
            compressed["operational_summary"] = {
                key: value
                for key, value in operational_summary.items()
                if key in _RESULT_FIRST_OPERATIONAL_SUMMARY_KEYS
            }
        return compressed
    if mode == "opening":
        compressed = dict(payload)
        raw_result = compressed.get("raw_result")
        if isinstance(raw_result, dict):
            sanitized_raw = _sanitize_interface_payload(raw_result)
            if isinstance(sanitized_raw, dict):
                compressed["raw_result"] = sanitized_raw
        return compressed
    if "operational_summary" in payload or "column_profiles" in payload:
        compressed_raw, has_more_columns, total_columns = _compress_raw_result_for_interface_context(payload)
        if has_more_columns and total_columns is not None:
            compressed_raw["has_more_columns"] = True
            compressed_raw["total_columns"] = total_columns
        return compressed_raw
    return payload


def _compress_interface_available_result(result_context: str) -> str:
    stripped = str(result_context or "").strip()
    if not stripped:
        return ""
    try:
        payload = json.loads(stripped)
    except Exception:
        return compress_assistant_message(stripped, limit=500)
    if not isinstance(payload, dict):
        return stripped
    compressed = _compress_interface_result_payload(payload)
    return json.dumps(compressed, ensure_ascii=False)


_HISTORY_FULL_TURNS_FOR_MODEL = 3


def _strip_raw_result_from_history_content(content: str) -> str:
    stripped = str(content or "").strip()
    if not stripped.startswith("{"):
        return str(content or "")
    try:
        payload = json.loads(stripped)
    except Exception:
        return str(content or "")
    if not isinstance(payload, dict) or "raw_result" not in payload:
        return str(content or "")
    slim = {key: value for key, value in payload.items() if key != "raw_result"}
    summary = slim.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    mode = str(slim.get("mode", "")).strip()
    if mode:
        return f"{mode}: resultado anterior (sem raw_result)"
    return compress_assistant_message(json.dumps(slim, ensure_ascii=False), limit=150)


def _history_turn_groups(history: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    turns: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    for turn in history or []:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role", "")).strip() or "unknown"
        content = str(turn.get("content", ""))
        if role == "user" and current:
            turns.append(current)
            current = []
        current.append({"role": role, "content": content})
    if current:
        turns.append(current)
    return turns


def _one_line_history_summary(*, role: str, content: str) -> str:
    cleaned = _strip_raw_result_from_history_content(content)
    normalized = " ".join(cleaned.split())
    prefix = "Usuário: " if role == "user" else "Interface: " if role == "assistant" else f"{role}: "
    return compress_assistant_message(prefix + normalized, limit=150)


def compress_history_for_model(history: list[dict[str, str]]) -> list[dict[str, str]]:
    turns = _history_turn_groups(history)
    if len(turns) <= _HISTORY_FULL_TURNS_FOR_MODEL:
        return [
            {
                "role": message["role"],
                "content": _strip_raw_result_from_history_content(message["content"]),
            }
            for turn in turns
            for message in turn
        ]
    compressed: list[dict[str, str]] = []
    for turn in turns[:-_HISTORY_FULL_TURNS_FOR_MODEL]:
        for message in turn:
            compressed.append(
                {
                    "role": message["role"],
                    "content": _one_line_history_summary(role=message["role"], content=message["content"]),
                }
            )
    for turn in turns[-_HISTORY_FULL_TURNS_FOR_MODEL:]:
        for message in turn:
            compressed.append(
                {
                    "role": message["role"],
                    "content": _strip_raw_result_from_history_content(message["content"]),
                }
            )
    return compressed


def compress_assistant_message(text: str, limit: int | None = None) -> str:
    normalized = " ".join(_strip_raw_result_from_history_content(text).split())
    if limit is None:
        return normalized
    if len(normalized) <= limit:
        return normalized
    if limit <= 3:
        return normalized[:limit]
    return normalized[: limit - 3].rstrip() + "..."


def _canonical_action_signature(action_payload: dict[str, object] | None) -> str:
    if not isinstance(action_payload, dict):
        return ""
    normalized = {
        str(key): value
        for key, value in action_payload.items()
        if str(key) not in {"__requirement_id", "_source_requirement_id"}
    }
    action_name = str(normalized.get("action", "")).strip()
    sql_identity = ""
    if action_name == "request_new_query":
        raw_sql = normalized.get("suggested_sql")
        if not isinstance(raw_sql, str) or not raw_sql.strip():
            raw_sql = normalized.get("sql")
        if isinstance(raw_sql, str) and raw_sql.strip():
            sql_identity = raw_sql.strip().lower()
    aliases = {
        "unit": normalized.get("unit_name") or normalized.get("unit"),
        "table": normalized.get("table"),
        "unit_a": normalized.get("unit_a"),
        "unit_b": normalized.get("unit_b"),
        "query_id": normalized.get("query_id"),
        "template_id": normalized.get("template_id"),
        "description": normalized.get("description"),
        "sql": sql_identity,
        "depth": normalized.get("depth"),
        "key": "" if action_name == "request_new_query" and sql_identity else normalized.get("key") or normalized.get("cache_key"),
    }
    compact = {"action": action_name}
    compact.update({key: value for key, value in aliases.items() if value not in (None, "", [])})
    return json.dumps(compact, ensure_ascii=False, sort_keys=True, default=str)


def _executed_action_signatures(execution_log: list[dict[str, object]] | None) -> set[str]:
    signatures: set[str] = set()
    for entry in execution_log or []:
        if not isinstance(entry, dict):
            continue
        signatures.add(_canonical_action_signature(entry))
    return {signature for signature in signatures if signature}


def _action_already_executed(
    action_payload: dict[str, object] | None,
    execution_log: list[dict[str, object]] | None,
) -> bool:
    if not isinstance(action_payload, dict):
        return False
    action_name = str(action_payload.get("action", "")).strip()
    if action_name == "analyze_horizontal":
        unit_a = str(action_payload.get("unit_a", "")).strip()
        unit_b = str(action_payload.get("unit_b", "")).strip()
        for entry in execution_log or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("action", "")).strip() != "analyze_horizontal":
                continue
            if str(entry.get("unit_a", "")).strip() == unit_a and str(entry.get("unit_b", "")).strip() == unit_b:
                return True
        return False
    signature = _canonical_action_signature(action_payload)
    return bool(signature) and signature in _executed_action_signatures(execution_log)


def _visible_presented_options(
    presented_options: list[dict[str, object]] | None,
    *,
    execution_log: list[dict[str, object]] | None = None,
    just_executed_action: dict[str, object] | None = None,
    limit: int | None = None,
) -> tuple[list[dict[str, object]], bool]:
    seen_signatures: set[str] = set()
    executed_signatures = _executed_action_signatures(execution_log)
    just_executed_signature = _canonical_action_signature(just_executed_action)
    filtered: list[dict[str, object]] = []
    overflow = False

    for option in presented_options or []:
        if not isinstance(option, dict):
            continue
        action_payload = option.get("action_payload")
        if not isinstance(action_payload, dict):
            continue
        if str(action_payload.get("action", "")).strip() == "recall":
            continue
        signature = _canonical_action_signature(action_payload)
        if not signature:
            continue
        if _action_already_executed(action_payload, execution_log):
            continue
        if signature == just_executed_signature:
            continue
        if signature in executed_signatures:
            continue
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        if limit is not None and len(filtered) >= limit:
            overflow = True
            continue
        item = dict(option)
        item["status"] = "active"
        filtered.append(item)

    for index, option in enumerate(filtered, start=1):
        option["index"] = index
    return filtered, overflow
