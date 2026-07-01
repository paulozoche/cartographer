from __future__ import annotations

import re

from agnostic.application.planning.planning_context import PlanningContext

__all__ = [
    "normalize_text",
    "normalize_identifier",
    "normalize_entity_name",
    "extract_observed_candidates_from_sample_entities",
    "extract_observed_candidates_from_cache",
    "value_forms",
    "find_mentioned_unit_approximate",
    "recent_or_plausible_units",
    "resolve_target_unit",
    "normalize_dimension_phrase",
    "resolve_dimension_column",
    "rank_search_terms_for_filtering",
    "select_independent_filter_terms",
    "search_terms_from_free_text",
    "column_names_from_structure",
    "infer_join_keys",
    "find_compatible_units",
]


def normalize_text(text: str) -> str:
    normalized = text.strip().lower()
    replacements = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return " ".join(normalized.split())


def extract_observed_candidates_from_sample_entities(context: PlanningContext) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for node in context.recent_nodes:
        unit = str(node.get("unit", "")).strip()
        for entity in node.get("sample_entities", []) or []:
            if not isinstance(entity, str):
                continue
            for part in entity.split(","):
                if "=" not in part:
                    continue
                column, value = part.split("=", 1)
                column = column.strip()
                value = value.strip()
                if column and value:
                    candidates.append({"unit": unit, "column": column, "value": value})
    return candidates


def extract_observed_candidates_from_cache(context: PlanningContext) -> list[dict[str, str]]:
    return list(context.known_entities)


def value_forms(value: str) -> list[str]:
    normalized = normalize_text(value)
    forms = [normalized]
    if len(normalized) > 3 and normalized.endswith("s"):
        singular = normalized[:-1].strip()
        if singular and singular not in forms:
            forms.append(singular)
    return forms


def _normalize_for_unit_matching(text: str) -> str:
    normalized = normalize_text(text)
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _tokenize_for_unit_matching(text: str) -> list[str]:
    return [token for token in _normalize_for_unit_matching(text).split() if token]


def _longest_common_subsequence(a: str, b: str) -> int:
    if not a or not b:
        return 0
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, char_a in enumerate(a, start=1):
        for j, char_b in enumerate(b, start=1):
            if char_a == char_b:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = dp[i - 1][j] if dp[i - 1][j] >= dp[i][j - 1] else dp[i][j - 1]
    return dp[-1][-1]


def _is_similar_unit_token(text_token: str, unit_token: str) -> bool:
    if not text_token or not unit_token:
        return False
    if min(len(text_token), len(unit_token)) < 3:
        return text_token == unit_token
    if text_token == unit_token or text_token in unit_token or unit_token in text_token:
        return True
    if text_token.endswith("s") and text_token[:-1] == unit_token:
        return True
    if unit_token.endswith("s") and unit_token[:-1] == text_token:
        return True
    lcs = _longest_common_subsequence(text_token, unit_token)
    return lcs >= min(len(text_token), len(unit_token)) - 1


def _unit_token_match_score(text_token: str, unit_token: str) -> int:
    if not text_token or not unit_token:
        return 0
    if len(text_token) < 3:
        return 4 if text_token == unit_token else 0
    if text_token == unit_token:
        return 4
    if text_token in unit_token or unit_token in text_token:
        return 3
    if text_token.endswith("s") and text_token[:-1] == unit_token:
        return 3
    if unit_token.endswith("s") and unit_token[:-1] == text_token:
        return 3
    return 1 if _is_similar_unit_token(text_token, unit_token) else 0


def find_mentioned_unit_approximate(text: str, unit_names: list[str]) -> str | None:
    normalized_text = _normalize_for_unit_matching(text)
    if not normalized_text:
        return None
    for unit_name in sorted(unit_names, key=len, reverse=True):
        normalized_unit = _normalize_for_unit_matching(unit_name)
        if normalized_unit and normalized_unit in normalized_text:
            return unit_name
    text_tokens = _tokenize_for_unit_matching(text)
    if not text_tokens:
        return None
    candidates: list[tuple[int, int, int, str]] = []
    for unit_name in unit_names:
        unit_tokens = _tokenize_for_unit_matching(unit_name)
        score = 0
        matched_tokens = 0
        for text_token in text_tokens:
            for unit_token in unit_tokens:
                token_score = _unit_token_match_score(text_token, unit_token)
                if token_score > 0:
                    score += token_score
                    matched_tokens += 1
                    break
        if score <= 0:
            continue
        if matched_tokens == 1 and score < 3 and len(unit_tokens) > 1:
            continue
        candidates.append((score, matched_tokens, len(unit_tokens), unit_name))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
    if len(candidates) > 1 and candidates[0][:2] == candidates[1][:2]:
        return None
    return candidates[0][3]


def _has_contextual_unit_evidence(context: PlanningContext) -> bool:
    if context.focus_state.active_focus:
        return True
    return bool(context.recent_nodes)


def _unit_summary_map(context: PlanningContext) -> dict[str, dict[str, object]]:
    summaries: dict[str, dict[str, object]] = {}
    for summary in context.unit_summaries:
        unit_name = str(summary.get("unit_name", "")).strip()
        if unit_name:
            summaries[unit_name] = summary
    for unit_name in context.available_units:
        summaries.setdefault(unit_name, {"unit_name": unit_name, "row_count": None, "columns": context.unit_columns.get(unit_name, [])})
    return summaries


def _unit_has_candidate_identifier(columns: list[str]) -> bool:
    normalized_columns = {normalize_text(column).replace(" ", "_") for column in columns}
    return any(
        column == "id"
        or column.endswith("_id")
        or column.endswith("_key")
        or column in {"code", "uuid", "identifier"}
        for column in normalized_columns
    )


def _unit_structural_score(unit_name: str) -> int:
    normalized = normalize_text(unit_name).replace(" ", "_")
    positive_terms = ("main", "root", "base", "core", "master", "catalog", "index")
    negative_suffixes = ("_dc", "_dict", "_lookup", "_ref", "_type", "_status")
    negative_tokens = ("dict", "lookup", "ref", "reference", "type", "status", "dimension", "dictionary")
    score = 0
    if any(term in normalized.split("_") or normalized.endswith(f"_{term}") or normalized.startswith(f"{term}_") for term in positive_terms):
        score += 3
    if any(normalized.endswith(suffix) for suffix in negative_suffixes):
        score -= 4
    if any(token in normalized.split("_") for token in negative_tokens):
        score -= 2
    return score


def _normalize_row_count(value: object) -> int | None:
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        normalized = int(value.strip())
        return normalized if normalized >= 0 else None
    return None


def _unit_looks_like_reference(unit_name: str) -> bool:
    return _unit_structural_score(unit_name) < 0


def _unit_fact_score(unit_name: str, columns: list[str]) -> int:
    normalized_unit = normalize_text(unit_name).replace(" ", "_")
    normalized_columns = [normalize_text(column).replace(" ", "_") for column in columns]
    unit_tokens = {token for token in normalized_unit.split("_") if token}
    score = 0
    if _unit_has_candidate_identifier(columns):
        score += 2
    if any(column == "id" for column in normalized_columns):
        score += 1
    repeated_foreign_keys = 0
    for column in normalized_columns:
        if not column.endswith("_id") or column == "id":
            continue
        base_token = column[:-3]
        if base_token and base_token not in unit_tokens:
            repeated_foreign_keys += 1
    score -= repeated_foreign_keys
    return score


def _recent_unit_ranks(context: PlanningContext) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for index, node in enumerate(context.recent_nodes):
        unit_name = str(node.get("unit", "")).strip()
        if unit_name and unit_name not in ranks:
            ranks[unit_name] = index
    return ranks


def _select_principal_unit(context: PlanningContext) -> str | None:
    summaries = _unit_summary_map(context)
    if not summaries:
        return None
    recent_ranks = _recent_unit_ranks(context)
    known_row_counts = [
        normalized
        for summary in summaries.values()
        if (normalized := _normalize_row_count(summary.get("row_count"))) is not None
    ]
    max_row_count = max(known_row_counts) if known_row_counts else None
    candidates: list[tuple[tuple[int, int, int, int, int, str], str]] = []
    for unit_name, summary in summaries.items():
        columns = [str(column).strip() for column in summary.get("columns", []) if str(column).strip()]
        normalized_row_count = _normalize_row_count(summary.get("row_count"))
        structural_score = _unit_structural_score(unit_name)
        fact_score = _unit_fact_score(unit_name, columns)
        row_count_score = normalized_row_count if normalized_row_count is not None else -1
        if max_row_count is not None and normalized_row_count is not None and normalized_row_count == max_row_count and _unit_looks_like_reference(unit_name):
            row_count_score = -1
        recency_score = 0
        recent_rank = recent_ranks.get(unit_name)
        if recent_rank is not None:
            recency_score = max(0, 2 - recent_rank)
            if _unit_looks_like_reference(unit_name):
                recency_score = 0
        score = (structural_score, fact_score, row_count_score, recency_score, len(columns), unit_name)
        candidates.append((score, unit_name))
    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return None
    if len(candidates) > 1 and candidates[0][0][:-1] == candidates[1][0][:-1]:
        return None
    return candidates[0][1]


def recent_or_plausible_units(context: PlanningContext) -> list[str]:
    ordered: list[str] = []
    active_focus = context.focus_state.active_focus
    if isinstance(active_focus, dict):
        for unit in active_focus.get("units", []):
            if isinstance(unit, str) and unit.strip() and unit not in ordered:
                ordered.append(unit)
    for node in context.recent_nodes:
        unit = str(node.get("unit", "")).strip()
        if unit and unit not in ordered:
            ordered.append(unit)
    for unit_name in context.available_units:
        if isinstance(unit_name, str) and unit_name.strip() and unit_name not in ordered:
            ordered.append(unit_name)
    return ordered


def resolve_target_unit(context: PlanningContext, user_text: str) -> str | None:
    plausible_units = recent_or_plausible_units(context)
    if not plausible_units:
        return None
    target_unit = find_mentioned_unit_approximate(user_text, plausible_units)
    if target_unit is not None:
        normalized_text = _normalize_for_unit_matching(user_text)
        normalized_target = _normalize_for_unit_matching(target_unit)
        explicit_unit_keywords = {"tabela", "table", "unit", "unidade"}
        has_explicit_unit_keyword = any(token in explicit_unit_keywords for token in _tokenize_for_unit_matching(user_text))
        if _unit_looks_like_reference(target_unit) and normalized_target not in normalized_text and not has_explicit_unit_keyword:
            target_unit = None
        else:
            return target_unit
    if len(plausible_units) == 1:
        return plausible_units[0]
    principal_unit = _select_principal_unit(context)
    if principal_unit is not None:
        return principal_unit
    if _has_contextual_unit_evidence(context):
        return plausible_units[0]
    return None


def _column_tokens(text: str) -> list[str]:
    normalized = normalize_text(str(text).replace("_", " "))
    return [token for token in re.sub(r"[^a-z0-9]+", " ", normalized).split() if token]


def _singularize_token(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


_PREFERRED_DIMENSION_COLUMN_TOKENS: dict[str, tuple[str, ...]] = {
    "tipo": ("type", "tipo", "kind", "category"),
    "categoria": ("category", "type", "kind"),
}


def normalize_dimension_phrase(text: str) -> str:
    normalized = normalize_text(text).strip(" ,.:!?")
    return re.sub(r"\s+", " ", normalized)


def _columns_for_unit(context: PlanningContext, unit_name: str) -> list[str]:
    return [str(column).strip() for column in context.unit_columns.get(unit_name, []) if str(column).strip()]


def _shared_prefix_length(a: str, b: str) -> int:
    length = 0
    for char_a, char_b in zip(a, b):
        if char_a != char_b:
            break
        length += 1
    return length


def resolve_dimension_column(context: PlanningContext, unit_name: str, dimension_text: str) -> str | None:
    columns = _columns_for_unit(context, unit_name)
    if not columns:
        return None
    phrase = normalize_dimension_phrase(dimension_text)
    if not phrase:
        return None
    phrase_tokens = [_singularize_token(token) for token in _column_tokens(phrase)]
    if not phrase_tokens:
        return None
    canonical_phrase = "".join(phrase_tokens)
    candidates: list[tuple[int, int, int, int, str]] = []
    for column in columns:
        column_tokens = [_singularize_token(token) for token in _column_tokens(column)]
        if not column_tokens:
            continue
        canonical_column = "".join(column_tokens)
        score = 0
        matched_tokens = 0
        prefix_length = 0
        if canonical_phrase == canonical_column:
            score = 100
            matched_tokens = len(phrase_tokens)
        elif canonical_phrase in canonical_column or canonical_column in canonical_phrase:
            score = 90
            matched_tokens = len(phrase_tokens)
        else:
            prefix_length = _shared_prefix_length(canonical_phrase, canonical_column)
            if prefix_length >= 2:
                score = 50 + prefix_length
                matched_tokens = max(matched_tokens, 1)
            for phrase_token in phrase_tokens:
                for column_token in column_tokens:
                    if _is_similar_unit_token(phrase_token, column_token):
                        matched_tokens += 1
                        break
            if matched_tokens == len(phrase_tokens):
                token_score = 60 + matched_tokens
                if token_score > score:
                    score = token_score
            elif len(phrase_tokens) == 1 and matched_tokens == 1:
                if 40 > score:
                    score = 40
            if score <= 0:
                phrase_lcs = _longest_common_subsequence(canonical_phrase, canonical_column)
                min_length = min(len(canonical_phrase), len(canonical_column))
                if min_length >= 5 and phrase_lcs >= max(4, min_length - 2):
                    score = 55
                    matched_tokens = max(matched_tokens, 1)
        if any(
            phrase_token in _PREFERRED_DIMENSION_COLUMN_TOKENS
            and column_token in _PREFERRED_DIMENSION_COLUMN_TOKENS[phrase_token]
            for phrase_token in phrase_tokens
            for column_token in column_tokens
        ):
            score = max(score, 120)
            matched_tokens = len(phrase_tokens)
        if score > 0:
            candidates.append((score, matched_tokens, prefix_length, len(column_tokens), column))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3], item[4]))
    if len(candidates) > 1 and (
        candidates[0][:3] == candidates[1][:3]
        or (
            candidates[0][0] != candidates[1][0]
            and candidates[0][1] == len(phrase_tokens)
            and candidates[1][1] == len(phrase_tokens)
            and candidates[0][2] == candidates[1][2]
        )
    ):
        return None
    return candidates[0][4]


def rank_search_terms_for_filtering(search_terms: list[str]) -> list[str]:
    if not search_terms:
        return []
    singular_candidates: list[str] = []
    for term in search_terms:
        if " " not in term and term.endswith("s") and term[:-1] in search_terms:
            singular_candidates.append(term[:-1])
    ranked: list[str] = []
    seen: set[str] = set()
    for term in search_terms:
        if term in singular_candidates and term not in seen:
            ranked.append(term)
            seen.add(term)
    best_phrase: str | None = None
    for term in search_terms:
        words = term.split()
        if len(words) == 2 and term not in seen:
            plural_count = sum(1 for word in words if word.endswith("s"))
            if best_phrase is None:
                best_phrase = term
            else:
                existing_plural_count = sum(1 for word in best_phrase.split() if word.endswith("s"))
                if plural_count < existing_plural_count:
                    best_phrase = term
    if best_phrase is not None and best_phrase not in seen:
        ranked.append(best_phrase)
        seen.add(best_phrase)
    for term in search_terms:
        if term not in seen and " " not in term:
            ranked.append(term)
            seen.add(term)
    for term in search_terms:
        if term not in seen and len(term.split()) == 2:
            ranked.append(term)
            seen.add(term)
    for term in search_terms:
        if term not in seen:
            ranked.append(term)
    return ranked


def select_independent_filter_terms(ranked_terms: list[str]) -> list[str]:
    selected: list[str] = []
    used_tokens: set[str] = set()
    for term in ranked_terms:
        term_tokens = {
            token[:-1] if len(token) > 3 and token.endswith("s") else token
            for token in term.split()
        }
        if not term_tokens & used_tokens:
            selected.append(term)
            used_tokens.update(term_tokens)
    return selected


def search_terms_from_free_text(user_text: str) -> list[str]:
    normalized = normalize_text(user_text)
    words = [word for word in normalized.split() if word]
    terms: list[str] = []
    for size in (3, 2, 1):
        for index in range(len(words) - size + 1):
            term = " ".join(words[index : index + size]).strip()
            if term and term not in terms:
                terms.append(term)
                if len(term) > 3 and term.endswith("s"):
                    singular = term[:-1].strip()
                    if singular and singular not in terms:
                        terms.append(singular)
    return terms


def normalize_identifier(value: str) -> str:
    normalized = value.strip().lower()
    for suffix in ("_id", "_key", "_code"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def normalize_entity_name(value: str) -> str:
    normalized = normalize_identifier(value)
    if normalized.endswith("ies") and len(normalized) > 3:
        return f"{normalized[:-3]}y"
    if normalized.endswith("s") and not normalized.endswith("ss") and len(normalized) > 1:
        return normalized[:-1]
    return normalized


def column_names_from_structure(structure: object) -> list[str]:
    return [str(getattr(column, "name", "")).strip() for column in getattr(structure, "columns", ()) if str(getattr(column, "name", "")).strip()]


def infer_join_keys(unit_a: str, structure_a: object, unit_b: str, structure_b: object) -> list[str]:
    columns_a = {column.name for column in getattr(structure_a, "columns", ())}
    columns_b = {column.name for column in getattr(structure_b, "columns", ())}
    candidates: list[tuple[str, str]] = []
    for same_name in sorted(columns_a & columns_b):
        normalized = normalize_identifier(same_name)
        if normalized.endswith("id") or normalized.endswith("key") or normalized.endswith("code") or normalized.endswith("ssn"):
            candidates.append((f"{unit_a}.{same_name}", f"{unit_b}.{same_name}"))
    for column_name in sorted(columns_a):
        if not column_name.endswith("_id"):
            continue
        prefix = column_name[:-3]
        if "id" in columns_b and normalize_entity_name(unit_b) == normalize_entity_name(prefix):
            candidates.append((f"{unit_a}.{column_name}", f"{unit_b}.id"))
    for column_name in sorted(columns_b):
        if not column_name.endswith("_id"):
            continue
        prefix = column_name[:-3]
        if "id" in columns_a and normalize_entity_name(unit_a) == normalize_entity_name(prefix):
            candidates.append((f"{unit_b}.{column_name}", f"{unit_a}.id"))
    for same_name in sorted(columns_a & columns_b):
        if same_name in {"id"}:
            continue
        candidates.append((f"{unit_a}.{same_name}", f"{unit_b}.{same_name}"))
    unique = []
    seen = set()
    for left, right in candidates:
        key = f"{left}={right}"
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def find_compatible_units(unit_name: str, columns: list[str], units: list[object]) -> list[str]:
    compatible: list[str] = []
    normalized_columns = {normalize_identifier(column) for column in columns}
    for unit in units:
        if unit.unit_name == unit_name:
            continue
        try:
            structure = unit.get_structure()
        except Exception:
            continue
        other_columns = column_names_from_structure(structure)
        overlap = normalized_columns & {normalize_identifier(column) for column in other_columns}
        if overlap:
            compatible.append(unit.unit_name)
    return compatible
