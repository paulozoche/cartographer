from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "windmill" / "f" / "cartographer" / "freio_acelerador.py"


def _load_module():
    wmill_mock = MagicMock()
    wmill_mock.get_variable.return_value = "http://core-api.test"
    sys.modules["wmill"] = wmill_mock

    spec = importlib.util.spec_from_file_location("freio_acelerador", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["freio_acelerador"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def brake_module(monkeypatch: pytest.MonkeyPatch):
    module = _load_module()
    wmill = MagicMock()
    wmill.get_variable.return_value = "http://core-api.test"
    monkeypatch.setitem(sys.modules, "wmill", wmill)
    monkeypatch.setattr(module, "wmill", wmill)
    return module


def _small_structure() -> dict:
    return {
        "units": [
            {
                "unit_name": "customers",
                "row_count": 100,
                "column_count": 3,
                "columns": [{"name": "id"}, {"name": "name"}, {"name": "email"}],
            }
        ]
    }


def _large_structure() -> dict:
    return {
        "units": [
            {
                "unit_name": f"table_{index}",
                "row_count": 500_000,
                "column_count": 30,
                "columns": [{"name": f"col_{col}"} for col in range(30)],
            }
            for index in range(8)
        ]
    }


def test_estimate_context_consumed_from_history(brake_module) -> None:
    history = [
        {"role": "user", "content": "analise customers"},
        {"role": "assistant", "content": "Resumo curto da análise."},
    ]
    consumed = brake_module.estimate_context_consumed(history)
    assert consumed > 0


def test_complexity_small_dataset(brake_module) -> None:
    score = brake_module.compute_complexity_score(_small_structure(), unit_name="customers")
    assert score < 0.3


def test_complexity_large_dataset(brake_module) -> None:
    score = brake_module.compute_complexity_score(_large_structure(), unit_name="table_0")
    assert score > 0.5


def _medium_columns_structure(column_count: int = 15) -> dict:
    return {
        "units": [
            {
                "unit_name": "wide_table",
                "row_count": 1000,
                "column_count": column_count,
                "columns": [{"name": f"col_{index}"} for index in range(column_count)],
            }
        ]
    }


def _multi_unit_structure(unit_count: int = 3) -> dict:
    return {
        "units": [
            {
                "unit_name": f"table_{index}",
                "row_count": 100,
                "column_count": 5,
                "columns": [{"name": f"col_{col}"} for col in range(5)],
            }
            for index in range(unit_count)
        ]
    }


def test_decide_acelerador_with_low_consumption(brake_module) -> None:
    plan = brake_module.build_delivery_plan(_small_structure(), context_consumed=500)
    assert plan["mode"] == "acelerador"
    assert plan["depth"] == "full"
    assert plan["use_llm"] is True
    assert plan["trim"]["include_correlations"] is True


def test_decide_freio_with_high_consumption(brake_module) -> None:
    plan = brake_module.build_delivery_plan(
        _large_structure(),
        context_consumed=18_000,
        unit_name="table_0",
    )
    assert plan["mode"] == "freio"
    assert plan["depth"] == "layer1"
    assert plan["trim"]["include_correlations"] is False
    assert plan["trim"]["include_layer2"] is False


def test_trim_analyze_unit_freio(brake_module) -> None:
    core_result = {
        "cache_key": "unit:customers",
        "unit_name": "customers",
        "summary": "Resumo da unidade.",
        "metrics_summary": [{"column": "id"}, {"column": "name"}],
        "correlations": [{"pair": ["id", "name"]}],
    }
    plan = brake_module.build_delivery_plan(_small_structure(), context_consumed=18_000)
    trimmed = brake_module.trim_core_result(core_result, "analyze_unit", plan)
    assert trimmed["summary"] == "Resumo da unidade."
    assert "metrics_summary" not in trimmed
    assert "correlations" not in trimmed


def test_trim_analyze_vertical_layer1(brake_module) -> None:
    core_result = {
        "unit_name": "customers",
        "column": "id",
        "summary": "Coluna id.",
        "layer1_metrics": {"cardinality": 5, "null_ratio": 0.0},
        "layer2_metrics": {"numeric_ratio": 1.0},
        "heuristics": [{"name": "identifier_signal"}],
        "top_values": [{"value": 1, "count": 1}],
        "signal": 1.0,
    }
    plan = brake_module.build_delivery_plan(_small_structure(), context_consumed=18_000)
    trimmed = brake_module.trim_core_result(core_result, "analyze_vertical", plan)
    assert "layer1_metrics" in trimmed
    assert "layer2_metrics" not in trimmed
    assert "heuristics" not in trimmed


def test_format_without_llm_vertical(brake_module) -> None:
    text = brake_module._format_without_llm(
        {
            "unit_name": "customers",
            "column": "id",
            "summary": "Identificador numérico.",
            "layer1_metrics": {"cardinality": 5, "null_ratio": 0.0},
            "signal": 1.0,
        },
        "analyze_vertical",
    )
    assert "customers" in text
    assert "id" in text
    assert "cardinality=5" in text


@pytest.mark.parametrize(
    ("structure_factory", "expected_action", "expected_format"),
    [
        (lambda: _small_structure(), "deliver_full", "full_analysis"),
        (lambda: _medium_columns_structure(15), "list_with_summary", "columns_with_summary"),
        (lambda: _medium_columns_structure(25), "list_truncated", "top_10_columns"),
        (lambda: _multi_unit_structure(3), "list_units", "units_with_summary"),
        (lambda: _large_structure(), "list_units_compact", "units_compact"),
    ],
)
def test_decide_delivery_by_complexity(
    brake_module,
    structure_factory,
    expected_action,
    expected_format,
) -> None:
    decision = brake_module.decide_delivery(structure_factory())
    assert decision["action"] == expected_action
    assert decision["format"] == expected_format
    assert decision["message"]


def test_build_delivery_plan_includes_strategy(brake_module) -> None:
    plan = brake_module.build_delivery_plan(_small_structure(), context_consumed=500)
    assert plan["action"] == "deliver_full"
    assert plan["format"] == "full_analysis"
    assert plan["mode"] == "acelerador"
