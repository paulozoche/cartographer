from __future__ import annotations

import sqlite3

def validate_select_sql_text(sql: str) -> str:
    normalized = " ".join(sql.strip().split())
    upper = normalized.upper()
    if not upper.startswith("SELECT "):
        raise ValueError("Apenas consultas SELECT são permitidas.")
    forbidden_tokens = [
        " INSERT ",
        " UPDATE ",
        " DELETE ",
        " DROP ",
        " ALTER ",
        " CREATE ",
        " ATTACH ",
        " DETACH ",
        " PRAGMA ",
        " REINDEX ",
        " VACUUM ",
        " TRUNCATE ",
    ]
    if ";" in normalized[:-1]:
        raise ValueError("Apenas uma instrução SELECT é permitida.")
    padded = f" {upper} "
    for token in forbidden_tokens:
        if token in padded:
            raise ValueError("Consulta rejeitada por conter comando não permitido.")
    return normalized


# SQL builders
def build_safe_select_sql(
    unit: str,
    select_columns: list[str],
    conditions: list[str],
    *,
    mode: str = "AND",
    limit: int = 50,
) -> str | None:
    normalized_unit = unit.strip()
    if not normalized_unit:
        return None
    cleaned_columns: list[str] = []
    for column in select_columns:
        normalized_column = str(column).strip()
        if normalized_column and normalized_column not in cleaned_columns:
            cleaned_columns.append(normalized_column)
    select_clause = ", ".join(cleaned_columns) if cleaned_columns else "*"
    cleaned_conditions: list[str] = []
    for condition in conditions:
        normalized_condition = str(condition).strip()
        if normalized_condition and normalized_condition not in cleaned_conditions:
            cleaned_conditions.append(normalized_condition)
    if not cleaned_conditions:
        return None
    joiner = " AND " if mode == "AND" else " OR "
    where_clause = joiner.join(cleaned_conditions)
    if not where_clause.strip():
        return None
    sql = f"SELECT {select_clause} FROM {normalized_unit} WHERE {where_clause} LIMIT {int(limit)}"
    if "SELECT FROM" in sql or "SELECT ," in sql or "WHERE  LIMIT" in sql or "FROM  WHERE" in sql:
        return None
    return sql


# SQL validators
def validate_generated_select_sql(sql: str) -> str | None:
    try:
        normalized = validate_select_sql_text(sql)
    except Exception:
        return None
    upper = normalized.upper()
    if (
        "SELECT FROM" in upper
        or "SELECT ," in upper
        or "WHERE LIMIT" in upper
        or "FROM  WHERE" in upper
        or "GROUP BY ORDER" in upper
        or "; LIMIT" in upper
        or "FROM  GROUP" in upper
    ):
        return None
    if "FROM" not in upper:
        return None
    return normalized


# SQL filter builders
def build_value_filter_sql(
    *,
    unit_name: str,
    column: str | None,
    value: str,
    select_clause: str = "*",
    columns: list[str] | None = None,
    quote_sql_literal,
) -> str | None:
    quoted_value = quote_sql_literal(value)
    if column:
        return f"SELECT {select_clause} FROM {unit_name} WHERE LOWER(CAST({column} AS TEXT)) = LOWER({quoted_value}) LIMIT 50"
    search_columns: list[str] = []
    for candidate in columns or []:
        if candidate not in search_columns:
            search_columns.append(candidate)
    if not search_columns:
        return None
    clauses = [f"LOWER(CAST({candidate} AS TEXT)) = LOWER({quoted_value})" for candidate in search_columns[:4]]
    escaped_value = value.replace("'", "''")
    like_clauses = [f"LOWER(CAST({candidate} AS TEXT)) LIKE LOWER('%{escaped_value}%')" for candidate in search_columns[:2]]
    predicate = " OR ".join(clauses + like_clauses)
    if not predicate:
        return None
    return f"SELECT {select_clause} FROM {unit_name} WHERE {predicate} LIMIT 50"


def build_multi_value_filter_sql(*, unit_name: str, select_clause: str, where_clause: str) -> str:
    return f"SELECT {select_clause} FROM {unit_name} WHERE {where_clause} LIMIT 50"


def build_direct_search_sql(*, unit_name: str, select_clause: str, clauses: list[str]) -> str | None:
    if not clauses:
        return None
    return f"SELECT {select_clause} FROM {unit_name} WHERE {' OR '.join(clauses)} LIMIT 50"


# Template instantiation and execution validation
def build_sql_from_template(template_id: str, params: dict[str, str], templates: dict[str, str] | None = None) -> str:
    templates = templates or {}
    template = templates.get(template_id)
    if not template:
        # fall back to caller-provided template set (e.g., orchestrator analytic templates)
        raise ValueError(f"Template não encontrado: {template_id}")
    return template.format(**params)


def validate_sql_by_execution(db_path: str | sqlite3.Connection, sql: str) -> None:
    test_sql = f"SELECT * FROM ({sql}) AS __cartographer_validation__ LIMIT 0"
    import sqlite3

    try:
        if isinstance(db_path, sqlite3.Connection):
            db_path.execute(test_sql)
            return
        with sqlite3.connect(db_path) as connection:
            connection.execute(test_sql)
    except sqlite3.Error as exc:
        raise ValueError(f"Query rejeitada pelo SQLite: {exc}") from exc


def generate_query_id(description: str, *, existing_ids: set[str]) -> str:
    import re

    base = re.sub(r"[^a-z0-9]+", "_", description.strip().lower()).strip("_")
    if not base:
        base = "session_query"
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate
