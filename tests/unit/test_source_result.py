from __future__ import annotations

from dataclasses import dataclass

import pytest

from agnostic.application.cache.runtime_analysis_cache import _CACHE
from agnostic.application.use_cases.source_result import build_source_result


@dataclass(frozen=True)
class _SourceMetadata:
    display_name: str
    unit_count: int | None


class _Unit:
    def __init__(self, unit_name: str) -> None:
        self.unit_name = unit_name


class _Source:
    def __init__(self, units: list[_Unit]) -> None:
        self._units = units

    def get_metadata(self) -> _SourceMetadata:
        return _SourceMetadata(display_name="demo-source", unit_count=len(self._units))

    def list_units(self) -> list[_Unit]:
        return list(self._units)


@pytest.fixture(autouse=True)
def _clear_runtime_analysis_cache() -> None:
    _CACHE.clear()


def _resolve_source_fn(_: str, __: str) -> _Source:
    return _Source([_Unit("users"), _Unit("orders"), _Unit("events")])


def _preview_source_unit_fn(unit: _Unit) -> dict[str, str]:
    return {"tabela_nome": unit.unit_name}


def _ordered_unit_names_fn(unit_names: list[str], _: list[dict[str, str]]) -> list[str]:
    return list(reversed(unit_names))


def _attach_internal_cuts_fn(payload: dict[str, object]) -> dict[str, object]:
    return payload


def _source_summary_text_fn(display_name: str, unit_count: int | None, ordered_unit_names: list[str]) -> str:
    return f"{display_name}|{unit_count}|{','.join(ordered_unit_names)}"


def _resolve_optional_limit_fn(requested: int | None, default: int | None) -> int | None:
    return requested if requested is not None else default


def _unit_importance_score_fn(_: dict[str, object]) -> float:
    return 0.0


def test_build_source_result_without_analysis_returns_expected_shape() -> None:
    result = build_source_result(
        "sqlite",
        "/tmp/demo.db",
        analyze_units=False,
        resolve_source_fn=_resolve_source_fn,
        preview_source_unit_fn=_preview_source_unit_fn,
        ordered_unit_names_fn=_ordered_unit_names_fn,
        attach_internal_cuts_fn=_attach_internal_cuts_fn,
        source_summary_text_fn=_source_summary_text_fn,
        resolve_optional_limit_fn=_resolve_optional_limit_fn,
        unit_importance_score_fn=_unit_importance_score_fn,
    )

    assert result == {
        "origem": {"display_name": "demo-source", "unit_count": 3},
        "summary": "demo-source|3|events,orders,users",
        "persisted_to": None,
        "tabela_nomes": ["events", "orders", "users"],
        "tabela_previas": [
            {"tabela_nome": "users"},
            {"tabela_nome": "orders"},
            {"tabela_nome": "events"},
        ],
        "tabelas": [],
    }


def test_build_source_result_raises_for_missing_unit_name() -> None:
    with pytest.raises(ValueError, match=r"^Unit not found: missing$"):
        build_source_result(
            "sqlite",
            "/tmp/demo.db",
            analyze_units=True,
            resolve_source_fn=_resolve_source_fn,
            preview_source_unit_fn=_preview_source_unit_fn,
            ordered_unit_names_fn=_ordered_unit_names_fn,
            attach_internal_cuts_fn=_attach_internal_cuts_fn,
            source_summary_text_fn=_source_summary_text_fn,
            resolve_optional_limit_fn=_resolve_optional_limit_fn,
            unit_importance_score_fn=_unit_importance_score_fn,
            unit_name="missing",
        )


def test_build_source_result_prioritizes_existing_unit_name(monkeypatch: pytest.MonkeyPatch) -> None:
    analyzed_units: list[str] = []

    @dataclass
    class _Analysis:
        unit_name: str
        type: str
        name: str
        signal: float
        standardized: dict[str, str]

    def _fake_analyze_tabular_unit(unit: _Unit, max_rows: int | None = None) -> _Analysis:
        del max_rows
        analyzed_units.append(unit.unit_name)
        return _Analysis(
            unit_name=unit.unit_name,
            type="table",
            name=unit.unit_name,
            signal=1.0,
            standardized={"unit_name": unit.unit_name},
        )

    monkeypatch.setattr("agnostic.application.use_cases.source_result.analyze_tabular_unit", _fake_analyze_tabular_unit)
    monkeypatch.setattr("agnostic.application.use_cases.source_result.summarize_tabular_analysis", lambda analysis: f"summary:{analysis.unit_name}")
    monkeypatch.setattr("agnostic.application.use_cases.source_result.summarize_unit_metrics", lambda analysis: [f"metrics:{analysis.unit_name}"])
    monkeypatch.setattr("agnostic.application.use_cases.source_result.persist_canonical_result", lambda *args: f"/tmp/{args[1].unit_name}.json")

    result = build_source_result(
        "sqlite",
        "/tmp/demo.db",
        analyze_units=True,
        resolve_source_fn=_resolve_source_fn,
        preview_source_unit_fn=_preview_source_unit_fn,
        ordered_unit_names_fn=_ordered_unit_names_fn,
        attach_internal_cuts_fn=_attach_internal_cuts_fn,
        source_summary_text_fn=_source_summary_text_fn,
        resolve_optional_limit_fn=_resolve_optional_limit_fn,
        unit_importance_score_fn=_unit_importance_score_fn,
        unit_name="orders",
        unit_limit=2,
        store=object(),
    )

    assert analyzed_units == ["orders", "users"]
    assert result["persisted_to"] == "/tmp/orders.json"
    assert result["summary"].startswith("Fonte demo-source: 3 unidades detectadas.\nUnidade selecionada: orders.")
    assert result["tabela_nomes"] == ["events", "orders", "users"]
    assert result["tabela_previas"] == [
        {"tabela_nome": "users"},
        {"tabela_nome": "orders"},
        {"tabela_nome": "events"},
    ]
    assert [table["tabela_nome"] for table in result["tabelas"]] == ["orders", "users"]
