from __future__ import annotations

from collections import Counter
from typing import Any

from .decisions import _collect_column_decisions


def _signal_label(signal_name: str) -> str:
    mapping = {
        "identifier_signal": "Identificador",
        "high_cardinality_signal": "Alta cardinalidade",
        "near_unique_conflict": "Conflito near-unique",
        "sequential_signal": "Sequencial",
        "pattern_signal": "Padrão",
    }
    return mapping.get(signal_name, signal_name.replace("_", " ").strip().title())


def _signal_explanation(signal_name: str) -> str:
    explanations = {
        "identifier_signal": "valores quase únicos e estáveis, com perfil de identificador",
        "high_cardinality_signal": "alta diversidade de valores na coluna",
        "near_unique_conflict": "coluna quase única com fuga localizada (duplicado ou nulo pontual)",
        "sequential_signal": "progressão sequencial consistente",
        "pattern_signal": "formato recorrente dominante nos valores",
    }
    return explanations.get(signal_name, "assinatura estrutural detectada")


def _collect_triggered_signal_names(column_payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(column_payload, dict):
        return []
    heuristics = column_payload.get("heuristics") or []
    names: list[str] = []
    for item in heuristics:
        if not isinstance(item, dict) or not item.get("triggered"):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _collect_unit_signals(unit_payload: dict[str, Any] | None) -> Counter[str]:
    counter: Counter[str] = Counter()
    if not isinstance(unit_payload, dict):
        return counter
    columns = unit_payload.get("columns") or {}
    if not isinstance(columns, dict):
        return counter
    for column in columns.values():
        for signal in _collect_triggered_signal_names(column if isinstance(column, dict) else None):
            counter[signal] += 1
    return counter


def _heuristic_by_name(column_payload: dict[str, Any] | None, heuristic_name: str) -> dict[str, Any]:
    if not isinstance(column_payload, dict):
        return {}
    heuristics = column_payload.get("heuristics") or []
    for item in heuristics:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "") == heuristic_name:
            return item
    return {}


def _build_synthetic_signatures(
    *,
    column_payload: dict[str, Any] | None,
    values: list[Any],
    selected_column: str,
    standardized_columns: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(column_payload, dict):
        return []
    normalized = ["∅" if value in (None, "") else str(value) for value in values]
    counter = Counter(normalized)
    total_rows = max(sum(int(count) for count in counter.values()), 1)
    non_null_tokens = [token for token in normalized if token != "∅"]
    non_null_count = len(non_null_tokens)
    non_null_counter = Counter(non_null_tokens)
    distinct_non_null = len(non_null_counter)
    null_rows = int(counter.get("∅", 0))
    empty_string_rows = sum(1 for value in values if value == "")

    layer1 = column_payload.get("layer1_metrics") or {}
    layer2 = column_payload.get("layer2_metrics") or {}
    unique_ratio = float(layer1.get("unique_ratio") or ((distinct_non_null / total_rows) if total_rows else 0.0))
    null_ratio = float(layer1.get("null_ratio") or (null_rows / total_rows))
    numeric_ratio = float(layer2.get("numeric_ratio") or 0.0)
    alpha_ratio = float(layer2.get("alpha_ratio") or 0.0)
    empty_string_ratio = (empty_string_rows / total_rows) if total_rows else 0.0
    triggered = set(_collect_triggered_signal_names(column_payload))

    existing_types = {
        str(item.get("type") or item.get("tipo") or "").strip().lower()
        for item in _collect_column_decisions(column_payload)
        if isinstance(item, dict)
    }
    signatures: list[dict[str, Any]] = []

    def _preview_from_counter(source_counter: Counter[str], *, limit: int = 5, reverse: bool = True) -> list[dict[str, Any]]:
        items = sorted(source_counter.items(), key=lambda kv: (-kv[1], kv[0]) if reverse else (kv[1], kv[0]))
        return [{"value": key, "frequency": int(freq)} for key, freq in items[:limit]]

    def _append(signature: dict[str, Any]) -> None:
        sig_type = str(signature.get("type") or signature.get("tipo") or "").strip().lower()
        if sig_type and sig_type in existing_types:
            return
        if not isinstance(signature.get("evidencia"), dict):
            preview = signature.get("preview") if isinstance(signature.get("preview"), list) else []
            sample = [
                str(item.get("value") or "")
                for item in preview[:5]
                if isinstance(item, dict) and str(item.get("value") or "").strip()
            ]
            signature["evidencia"] = {
                "descricao": str(signature.get("description") or ""),
                "camada_origem": "coluna",
                "sinais": [],
                "amostra": sample,
            }
        if not isinstance(signature.get("transicoes_permitidas"), list):
            path_map = {
                "valor/celula": "valor_celula",
                "novo_recorte": "recorte",
                "create_base_from_slice": "subconjunto",
            }
            paths = signature.get("paths") if isinstance(signature.get("paths"), list) else []
            signature["transicoes_permitidas"] = [
                {"destino": path_map.get(str(path), str(path)), "motivo": "transição estrutural"}
                for path in paths
                if str(path).strip()
            ]
        if sig_type:
            existing_types.add(sig_type)
        signatures.append(signature)

    duplicate_values = [token for token, count in counter.items() if int(count) > 1 and token != "∅"]
    duplicate_rows = sum(int(counter.get(token, 0)) for token in duplicate_values)
    has_escape = duplicate_rows > 0 or null_rows > 0
    if unique_ratio >= 0.98 and has_escape and "conflict" not in existing_types and "conflito" not in existing_types:
        escape_values = sorted(duplicate_values, key=lambda token: (-int(counter.get(token, 0)), token))
        if null_rows > 0:
            escape_values = ["∅", *escape_values]
        preview = [{"value": token, "frequency": int(counter.get(token, 0))} for token in escape_values[:5]]
        _append(
            {
                "id": "conflict_near_unique_escape",
                "tipo": "conflito",
                "type": "conflict",
                "description": "Fuga localizada em coluna near-unique.",
                "prioridade": "alta",
                "preview": preview,
                "paths": ["valor/celula", "novo_recorte"],
                "metadata": {
                    "name": "near_unique_escape",
                    "conflict_values": escape_values,
                    "escape_rows": duplicate_rows + null_rows,
                    "escape_ratio": ((duplicate_rows + null_rows) / total_rows) if total_rows else 0.0,
                },
            }
        )

    if (
        unique_ratio > 0.98
        and null_ratio <= 0.05
        and ("identifier_signal" in triggered or "high_cardinality_signal" in triggered)
    ):
        _append(
            {
                "id": "candidate_key_signature",
                "tipo": "candidate_key",
                "type": "candidate_key",
                "description": "Coluna quase única com comportamento de identificador.",
                "prioridade": "alta",
                "preview": _preview_from_counter(non_null_counter, limit=5, reverse=False),
                "paths": ["valor/celula", "novo_recorte", "create_base_from_slice"],
                "metadata": {
                    "unique_ratio": unique_ratio,
                    "null_ratio": null_ratio,
                    "impact_rows": distinct_non_null,
                    "impact_ratio": (distinct_non_null / total_rows) if total_rows else 0.0,
                    "slice_type": "candidate_key_group",
                },
            }
        )

    pattern_entry = _heuristic_by_name(column_payload, "pattern_signal")
    pattern_evidence = pattern_entry.get("evidence") if isinstance(pattern_entry.get("evidence"), dict) else {}
    pattern_ratio = float(pattern_evidence.get("match_ratio") or 0.0)
    fixed_length = bool(pattern_evidence.get("fixed_length"))
    fixed_length_value = pattern_evidence.get("fixed_length_value")
    if "pattern_signal" in triggered and pattern_ratio >= 0.7:
        if pattern_ratio >= 0.8:
            _append(
                {
                    "id": "format_domain_signature",
                    "tipo": "format_domain",
                    "type": "format_domain",
                    "description": "Formato dominante detectado na coluna.",
                    "prioridade": "media",
                    "preview": _preview_from_counter(non_null_counter, limit=5, reverse=True),
                    "paths": ["valor/celula", "novo_recorte"],
                    "metadata": {
                        "match_ratio": pattern_ratio,
                        "impact_ratio": pattern_ratio,
                        "impact_rows": int(round(non_null_count * pattern_ratio)),
                        "slice_type": "format_domain_group",
                    },
                }
            )
        escape_rows = 0
        escape_preview: list[dict[str, Any]] = []
        if fixed_length and fixed_length_value is not None:
            try:
                expected_length = int(fixed_length_value)
            except (TypeError, ValueError):
                expected_length = None
            mismatch_counter = Counter(
                token
                for token in non_null_tokens
                if expected_length is not None and len(token) != expected_length
            )
            escape_rows = sum(int(freq) for freq in mismatch_counter.values())
            escape_preview = _preview_from_counter(mismatch_counter, limit=5, reverse=True)
        else:
            estimated_escape_rows = int(round(non_null_count * (1.0 - pattern_ratio)))
            if estimated_escape_rows > 0:
                escape_rows = estimated_escape_rows
                escape_preview = _preview_from_counter(non_null_counter, limit=5, reverse=False)
        if escape_rows > 0:
            _append(
                {
                    "id": "format_escape_signature",
                    "tipo": "format_escape",
                    "type": "format_escape",
                    "description": "Valores fora do padrão dominante de formato.",
                    "prioridade": "media",
                    "preview": escape_preview,
                    "paths": ["valor/celula", "novo_recorte", "create_base_from_slice"],
                    "metadata": {
                        "escape_rows": escape_rows,
                        "escape_ratio": (escape_rows / total_rows) if total_rows else 0.0,
                        "slice_type": "format_escape_group",
                    },
                }
            )

    if null_ratio > 0.8 or empty_string_ratio > 0.8:
        non_null_preview = _preview_from_counter(non_null_counter, limit=5, reverse=True)
        _append(
            {
                "id": "sparse_field_signature",
                "tipo": "sparse_field",
                "type": "sparse_field",
                "description": "Predominância de ausência na coluna.",
                "prioridade": "alta",
                "preview": non_null_preview,
                "paths": ["valor/celula", "novo_recorte"],
                "metadata": {
                    "null_ratio": null_ratio,
                    "empty_string_ratio": empty_string_ratio,
                    "impact_ratio": max(null_ratio, empty_string_ratio),
                    "impact_rows": int(round(total_rows * max(null_ratio, empty_string_ratio))),
                    "slice_type": "sparse_field_group",
                },
            }
        )

    max_ratio = max(numeric_ratio, alpha_ratio)
    min_ratio = min(numeric_ratio, alpha_ratio)
    if max_ratio < 0.8 and min_ratio > 0.1:
        _append(
            {
                "id": "mixed_representation_signature",
                "tipo": "mixed_representation",
                "type": "mixed_representation",
                "description": "Representação mista detectada na coluna.",
                "prioridade": "media",
                "preview": _preview_from_counter(non_null_counter, limit=5, reverse=True),
                "paths": ["valor/celula", "novo_recorte"],
                "metadata": {
                    "numeric_ratio": numeric_ratio,
                    "alpha_ratio": alpha_ratio,
                    "impact_ratio": 1.0 - max_ratio,
                    "slice_type": "mixed_representation_group",
                },
            }
        )

    if isinstance(standardized_columns, dict):
        current_set = {token for token in non_null_tokens if token.strip()}
        current_cardinality = max(len(current_set), 1)
        best_match: dict[str, Any] | None = None
        for other_name, other_values in standardized_columns.items():
            if str(other_name) == str(selected_column) or not isinstance(other_values, list):
                continue
            other_set = {str(item) for item in other_values if item not in (None, "") and str(item).strip()}
            if not other_set:
                continue
            shared = current_set & other_set
            if not shared:
                continue
            overlap = len(shared) / max(min(len(current_set), len(other_set)), 1)
            card_ratio = current_cardinality / max(len(other_set), 1)
            if overlap < 0.12 or not (0.5 <= card_ratio <= 2.0):
                continue
            candidate = {
                "other_column": str(other_name),
                "overlap": overlap,
                "card_ratio": card_ratio,
                "values": sorted(shared)[:5],
            }
            if best_match is None or float(candidate["overlap"]) > float(best_match["overlap"]):
                best_match = candidate
        if best_match:
            preview = [{"value": value, "frequency": int(counter.get(value, 1))} for value in best_match["values"]]
            _append(
                {
                    "id": "referential_candidate_signature",
                    "tipo": "referential_candidate",
                    "type": "referential_candidate",
                    "description": "Possível relação estrutural com outra coluna.",
                    "prioridade": "media",
                    "preview": preview,
                    "paths": ["valor/celula", "novo_recorte", "create_base_from_slice"],
                    "metadata": {
                        "target_column": best_match["other_column"],
                        "overlap_ratio": best_match["overlap"],
                        "cardinality_ratio": best_match["card_ratio"],
                        "impact_ratio": best_match["overlap"],
                        "slice_type": "referential_candidate_group",
                    },
                }
            )

    return signatures
