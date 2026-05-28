from __future__ import annotations


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
        from orchestrator import validate_select_sql_text

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
    text_columns: list[str] | None = None,
    categorical_columns: list[str] | None = None,
    quote_sql_literal,
) -> str | None:
    quoted_value = quote_sql_literal(value)
    if column:
        return f"SELECT {select_clause} FROM {unit_name} WHERE LOWER(CAST({column} AS TEXT)) = LOWER({quoted_value}) LIMIT 50"
    text_columns = text_columns or []
    categorical_columns = categorical_columns or []
    fallback_columns: list[str] = []
    for candidate in categorical_columns + text_columns:
        if candidate not in fallback_columns:
            fallback_columns.append(candidate)
    if not fallback_columns:
        return None
    clauses = [f"LOWER(CAST({candidate} AS TEXT)) = LOWER({quoted_value})" for candidate in fallback_columns[:4]]
    escaped_value = value.replace("'", "''")
    like_clauses = [f"LOWER(CAST({candidate} AS TEXT)) LIKE LOWER('%{escaped_value}%')" for candidate in text_columns[:2]]
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
