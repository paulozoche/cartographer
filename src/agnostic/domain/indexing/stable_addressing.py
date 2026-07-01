from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any, Protocol

from agnostic.application.planning.entity_resolution import normalize_text
from agnostic.domain.indexing.dataset_hash import (
    build_internal_id,
    get_dataset_hash,
    sanitize_value_identifier,
)


class _UnitLike(Protocol):
    unit_name: str

    def get_structure(self) -> Any: ...


def _sorted_names(names: list[str]) -> list[str]:
    cleaned = [str(name).strip() for name in names if str(name).strip()]
    return sorted(cleaned, key=str.lower)


def build_table_index_map(unit_names: list[str]) -> dict[str, int]:
    """Mapeamento determinístico unit_name → índice (1..N), ordem alfabética case-insensitive."""
    sorted_names = _sorted_names(unit_names)
    return {name: index for index, name in enumerate(sorted_names, start=1)}


def build_column_index_map(column_names: list[str]) -> dict[str, int]:
    """Mapeamento determinístico column_name → índice (1..N), ordem alfabética case-insensitive."""
    sorted_names = _sorted_names(column_names)
    return {name: index for index, name in enumerate(sorted_names, start=1)}


def _normalize_join_record(table_a: str, table_b: str, join_keys: list[str]) -> tuple[str, str, tuple[str, ...]]:
    keys = tuple(sorted({str(key).strip() for key in join_keys if str(key).strip()}, key=str.lower))
    if table_a.lower() <= table_b.lower():
        return table_a, table_b, keys
    return table_b, table_a, keys


def build_relationship_index_map(
    table_index_map: dict[str, int],
    detected_joins: list[tuple[str, str, list[str]]],
    *,
    confidence_by_pair: dict[tuple[str, str], str] | None = None,
) -> dict[str, dict[str, object]]:
    """Índices estáveis para relacionamentos (joins) detectados."""
    confidence_by_pair = confidence_by_pair or {}
    normalized_joins = sorted(
        {_normalize_join_record(table_a, table_b, join_keys) for table_a, table_b, join_keys in detected_joins},
        key=lambda item: (item[0].lower(), item[1].lower(), item[2]),
    )
    relationships: dict[str, dict[str, object]] = {}
    for index, (table_a, table_b, join_keys) in enumerate(normalized_joins, start=1):
        address = format_relationship_address("join", index)
        pair_key = (table_a, table_b) if table_a.lower() <= table_b.lower() else (table_b, table_a)
        relationships[address] = {
            "index": index,
            "address": address,
            "relationship_type": "join",
            "table_a": table_a,
            "table_a_index": table_index_map.get(table_a),
            "table_b": table_b,
            "table_b_index": table_index_map.get(table_b),
            "join_keys": list(join_keys),
            "confidence": confidence_by_pair.get(pair_key, "high"),
        }
    return relationships


def build_slice_index_map(
    table_index_map: dict[str, int],
    column_index_map: dict[str, dict[str, int]],
    detected_values: dict[tuple[str, str], list[tuple[str, int]]],
) -> dict[str, dict[str, object]]:
    """Índices estáveis para recortes (valores observados em colunas)."""
    slices: dict[str, dict[str, object]] = {}
    index = 1
    for table, column in sorted(detected_values, key=lambda item: (item[0].lower(), item[1].lower())):
        values = detected_values[(table, column)]
        for value, row_count in sorted(values, key=lambda item: str(item[0]).lower()):
            value_text = str(value).strip()
            if not value_text:
                continue
            address = format_slice_address(table, column, value_text, index)
            slices[address] = {
                "index": index,
                "address": address,
                "slice_type": "filter",
                "table": table,
                "table_index": table_index_map.get(table),
                "column": column,
                "column_index": column_index_map.get(table, {}).get(column),
                "operator": "=",
                "value": value_text,
                "row_count": int(row_count),
            }
            index += 1
    return slices


def format_db_address(source_name: str, *, index: int = 1) -> str:
    return f"db:{source_name}:i{index}"


def format_table_address(table_name: str, index: int) -> str:
    return f"tbl:{table_name}:i{index}"


def format_column_address(table_name: str, column_name: str, index: int) -> str:
    return f"col:{table_name}.{column_name}:i{index}"


def format_relationship_address(rel_type: str, index: int) -> str:
    return f"rel:{rel_type}:i{index}"


def format_slice_address(table_name: str, column_name: str, value: str, index: int) -> str:
    return f"slice:{table_name}.{column_name}={value}:i{index}"


@dataclass(frozen=True, slots=True)
class IndexedEntity:
    level: int
    kind: str
    name: str
    index: int
    address: str


@dataclass
class SessionIndexRegistry:
    """Endereçamento estável da sessão. Apenas referência e navegação — nunca análise."""

    source_path: str
    source_name: str
    dataset_hash: str
    db_address: str
    table_index_by_name: dict[str, int] = field(default_factory=dict)
    table_name_by_index: dict[int, str] = field(default_factory=dict)
    column_index_by_table: dict[str, dict[str, int]] = field(default_factory=dict)
    column_name_by_table: dict[str, dict[int, str]] = field(default_factory=dict)
    relationship_index_map: dict[str, dict[str, object]] = field(default_factory=dict)
    slice_index_map: dict[str, dict[str, object]] = field(default_factory=dict)
    _internal_id_cache: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_units(cls, source_path: str, units: list[_UnitLike]) -> SessionIndexRegistry:
        resolved_path = str(Path(str(source_path)).expanduser().resolve())
        source_name = Path(resolved_path).name or "source"
        dataset_hash = get_dataset_hash(resolved_path)
        unit_names = [str(getattr(unit, "unit_name", "")).strip() for unit in units]
        table_map = build_table_index_map(unit_names)
        table_name_by_index = {index: name for name, index in table_map.items()}

        column_index_by_table: dict[str, dict[str, int]] = {}
        column_name_by_table: dict[str, dict[int, str]] = {}
        for unit in units:
            unit_name = str(getattr(unit, "unit_name", "")).strip()
            if not unit_name:
                continue
            get_structure = getattr(unit, "get_structure", None)
            structure = get_structure() if callable(get_structure) else None
            column_names = [
                str(getattr(column, "name", "")).strip()
                for column in getattr(structure, "columns", ()) or ()
                if str(getattr(column, "name", "")).strip()
            ]
            column_map = build_column_index_map(column_names)
            column_index_by_table[unit_name] = column_map
            column_name_by_table[unit_name] = {index: name for name, index in column_map.items()}

        registry = cls(
            source_path=resolved_path,
            source_name=source_name,
            dataset_hash=dataset_hash,
            db_address=format_db_address(source_name),
            table_index_by_name=table_map,
            table_name_by_index=table_name_by_index,
            column_index_by_table=column_index_by_table,
            column_name_by_table=column_name_by_table,
        )
        registry._rebuild_internal_id_cache()
        return registry

    def get_table_internal_id(self, table_name: str, index: int) -> str:
        return build_internal_id(self.dataset_hash, "t", index)

    def get_column_internal_id(self, table_index: int, column_index: int) -> str:
        return build_internal_id(self.dataset_hash, "c", f"{table_index}.{column_index}")

    def get_value_internal_id(self, value: str) -> str:
        return build_internal_id(self.dataset_hash, "v", sanitize_value_identifier(value))

    def get_relationship_internal_id(self, index: int) -> str:
        return build_internal_id(self.dataset_hash, "r", index)


    def resolve_user_reference(self, user_input: str) -> str | None:
        """Resolve entrada numérica do usuário para ID interno de tabela."""
        table_name = resolve_table_reference(user_input, self)
        if not table_name:
            return None
        index = self.table_index_by_name.get(table_name)
        if index is None:
            return None
        return self.get_table_internal_id(table_name, index)

    def resolve_internal_id(self, internal_id: str) -> str | None:
        """Resolve ID interno para nome externo (tabela)."""
        return self._internal_id_cache.get(internal_id)

    def _rebuild_internal_id_cache(self) -> None:
        cache: dict[str, str] = {}
        for table_name, index in self.table_index_by_name.items():
            cache[self.get_table_internal_id(table_name, index)] = table_name
        self._internal_id_cache = cache

    def refresh_relationships(
        self,
        detected_joins: list[tuple[str, str, list[str]]],
        *,
        confidence_by_pair: dict[tuple[str, str], str] | None = None,
    ) -> None:
        self.relationship_index_map = build_relationship_index_map(
            self.table_index_by_name,
            detected_joins,
            confidence_by_pair=confidence_by_pair,
        )
        for relationship in self.relationship_index_map.values():
            rel_index = int(relationship.get("index", 0) or 0)
            relationship["internal_id"] = self.get_relationship_internal_id(rel_index)

    def refresh_slices(self, detected_values: dict[tuple[str, str], list[tuple[str, int]]]) -> None:
        self.slice_index_map = build_slice_index_map(
            self.table_index_by_name,
            self.column_index_by_table,
            detected_values,
        )
        for slice_info in self.slice_index_map.values():
            value = str(slice_info.get("value", "")).strip()
            if value:
                value_internal_id = self.get_value_internal_id(value)
                slice_info["internal_id"] = value_internal_id
                slice_info["value_internal_id"] = value_internal_id

    def table_address_for(self, table_name: str) -> str | None:
        index = self.table_index_by_name.get(table_name)
        if index is None:
            return None
        return format_table_address(table_name, index)

    def column_address_for(self, table_name: str, column_name: str) -> str | None:
        column_map = self.column_index_by_table.get(table_name, {})
        index = column_map.get(column_name)
        if index is None:
            return None
        return format_column_address(table_name, column_name, index)

    def resolve_table_index(self, requested_index: int) -> str | None:
        return self.table_name_by_index.get(requested_index)

    def resolve_column_index(self, table_name: str, requested_index: int) -> str | None:
        return self.column_name_by_table.get(table_name, {}).get(requested_index)

    def indexed_tables(self) -> list[IndexedEntity]:
        return [
            IndexedEntity(
                level=1,
                kind="tbl",
                name=table_name,
                index=index,
                address=format_table_address(table_name, index),
            )
            for table_name, index in sorted(self.table_index_by_name.items(), key=lambda item: item[1])
        ]

    def summary_for_prompt(self) -> dict[str, object]:
        return {
            "dataset_hash": self.dataset_hash,
            "db_address": self.db_address,
            "tables": [
                {
                    "internal_id": self.get_table_internal_id(entity.name, entity.index),
                    "display_index": entity.index,
                    "display_name": entity.name,
                    "index": entity.index,
                    "name": entity.name,
                    "address": entity.address,
                }
                for entity in self.indexed_tables()
            ],
            "relationships": [
                {
                    "internal_id": rel.get("internal_id"),
                    "index": rel.get("index"),
                    "display_index": rel.get("index"),
                    "address": rel.get("address"),
                    "table_a": rel.get("table_a"),
                    "table_a_index": rel.get("table_a_index"),
                    "table_b": rel.get("table_b"),
                    "table_b_index": rel.get("table_b_index"),
                    "join_keys": rel.get("join_keys"),
                }
                for rel in sorted(
                    self.relationship_index_map.values(),
                    key=lambda item: int(item.get("index", 0) or 0),
                )
            ],
            "slices": [
                {
                    "internal_id": slice_info.get("internal_id"),
                    "value_internal_id": slice_info.get("value_internal_id"),
                    "index": slice_info.get("index"),
                    "display_index": slice_info.get("index"),
                    "address": slice_info.get("address"),
                    "table": slice_info.get("table"),
                    "table_index": slice_info.get("table_index"),
                    "column": slice_info.get("column"),
                    "column_index": slice_info.get("column_index"),
                    "value": slice_info.get("value"),
                }
                for slice_info in sorted(
                    self.slice_index_map.values(),
                    key=lambda item: int(item.get("index", 0) or 0),
                )
            ],
        }

    def resolve(self, user_input: str, *, context_table_index: int | None = None) -> dict[str, object] | None:
        """Resolve referência por índice: tabela, relacionamento, recorte ou coluna."""
        column_ref = resolve_column_reference(user_input, self)
        if column_ref:
            table, column = column_ref
            table_index = int(self.table_index_by_name.get(table, 0) or 0)
            column_index = int(self.column_index_by_table.get(table, {}).get(column, 0) or 0)
            return {
                "type": "column",
                "table": table,
                "column": column,
                "table_index": table_index,
                "column_index": column_index,
                "internal_id": self.get_column_internal_id(table_index, column_index),
                "address": self.column_address_for(table, column),
            }

        relationship = resolve_relationship_reference(user_input, self.relationship_index_map)
        if relationship:
            return {"type": "relationship", **relationship}

        slice_info = resolve_slice_reference(user_input, self.slice_index_map, context_table_index)
        if slice_info:
            return {"type": "slice", **slice_info}

        table_name = resolve_table_reference(user_input, self)
        if table_name:
            index = self.table_index_by_name.get(table_name)
            return {
                "type": "table",
                "name": table_name,
                "index": index,
                "internal_id": self.get_table_internal_id(table_name, int(index or 0)),
                "address": self.table_address_for(table_name),
            }
        return None


def parse_table_index_reference(user_text: str) -> int | None:
    normalized = normalize_text(user_text)
    if not normalized:
        return None
    table_match = re.search(r"\btabela\s+(\d+)\b", normalized)
    if table_match:
        return int(table_match.group(1))
    if re.fullmatch(r"\d+", normalized):
        return int(normalized)
    return None


def parse_table_pair_index_reference(user_text: str) -> tuple[int, int] | None:
    normalized = normalize_text(user_text)
    if not normalized:
        return None
    match = re.search(r"\btabela\s+(\d+)\b.*?\btabela\s+(\d+)\b", normalized)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def parse_column_table_reference(user_text: str) -> tuple[int | None, int | None]:
    normalized = normalize_text(user_text)
    if not normalized:
        return None, None
    match = re.search(r"\bcoluna\s+(\d+)\s+da\s+tabela\s+(\d+)\b", normalized)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def parse_relationship_index_reference(user_text: str) -> int | None:
    normalized = normalize_text(user_text)
    if not normalized:
        return None
    patterns = (
        r"\b(?:relacionamento|relacao|join|cruzamento)\s+(\d+)\b",
        r"\brel[.:](\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def parse_slice_index_reference(user_text: str) -> int | None:
    normalized = normalize_text(user_text)
    if not normalized:
        return None
    patterns = (
        r"\b(?:recorte|slice|filtro)\s+(\d+)\b",
        r"\bslice[.:](\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def resolve_table_reference(user_text: str, registry: SessionIndexRegistry) -> str | None:
    requested_index = parse_table_index_reference(user_text)
    if requested_index is None:
        return None
    return registry.resolve_table_index(requested_index)


def resolve_column_reference(user_text: str, registry: SessionIndexRegistry) -> tuple[str, str] | None:
    column_index, table_index = parse_column_table_reference(user_text)
    if column_index is None or table_index is None:
        return None
    table_name = registry.resolve_table_index(table_index)
    if not table_name:
        return None
    column_name = registry.resolve_column_index(table_name, column_index)
    if not column_name:
        return None
    return table_name, column_name


def resolve_relationship_reference(
    user_input: str,
    relationship_index_map: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    requested_index = parse_relationship_index_reference(user_input)
    if requested_index is None:
        return None
    for relationship in relationship_index_map.values():
        if int(relationship.get("index", -1)) == requested_index:
            return dict(relationship)
    return None


def resolve_slice_reference(
    user_input: str,
    slice_index_map: dict[str, dict[str, object]],
    context_table_index: int | None = None,
) -> dict[str, object] | None:
    requested_index = parse_slice_index_reference(user_input)
    if requested_index is None:
        return None
    for slice_info in slice_index_map.values():
        if int(slice_info.get("index", -1)) != requested_index:
            continue
        if context_table_index is not None and int(slice_info.get("table_index", -1)) != context_table_index:
            continue
        return dict(slice_info)
    return None
