from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "windmill" / "f" / "cartographer" / "formatar_resposta.py"


def _load_module():
    wmill_mock = MagicMock()
    wmill_mock.get_variable.return_value = "http://core-api.test"
    sys.modules["wmill"] = wmill_mock

    spec = importlib.util.spec_from_file_location("formatar_resposta", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["formatar_resposta"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def format_module(monkeypatch: pytest.MonkeyPatch):
    module = _load_module()
    wmill = MagicMock()
    wmill.get_variable.side_effect = lambda key: {
        "f/cartographer/CORE_API_URL": "http://core-api.test",
        "f/cartographer/DEEPSEEK_API_KEY": "test-key",
    }[key]
    monkeypatch.setitem(sys.modules, "wmill", wmill)
    monkeypatch.setattr(module, "wmill", wmill)
    return module


def _single_unit_structure(column_count: int = 5) -> dict:
    return {
        "session_id": "sess-1",
        "units": [
            {
                "unit_name": "customers",
                "row_count": 100,
                "column_count": column_count,
                "columns": [
                    {
                        "name": f"col_{index}",
                        "cardinality": 10 + index,
                        "null_ratio": 0.0,
                        "unique_ratio": 0.5,
                        "raw_type": "TEXT" if index % 2 else "INTEGER",
                    }
                    for index in range(column_count)
                ],
            }
        ],
    }


def _multi_unit_structure(unit_count: int = 9) -> dict:
    return {
        "session_id": "sess-1",
        "units": [
            {
                "unit_name": f"table_{index}",
                "row_count": 50 + index,
                "column_count": 4,
                "columns": [
                    {
                        "name": f"col_{col}",
                        "cardinality": 10,
                        "null_ratio": 0.1,
                        "unique_ratio": 0.8,
                        "raw_type": "INTEGER",
                    }
                    for col in range(4)
                ],
            }
            for index in range(unit_count)
        ],
    }


def test_build_list_with_summary_payload(format_module) -> None:
    payload = format_module._build_list_with_summary_payload(_single_unit_structure(15))
    assert payload["unit_name"] == "customers"
    assert payload["column_count"] == 15
    assert len(payload["columns"]) == 15
    assert payload["next_step"]


def test_build_list_truncated_payload(format_module) -> None:
    payload = format_module._build_list_truncated_payload(_single_unit_structure(25))
    assert len(payload["top_columns"]) == 10
    assert payload["additional_column_count"] == 15
    assert payload["next_step"]


def test_build_list_units_payload(format_module) -> None:
    payload = format_module._build_list_units_payload(_multi_unit_structure(9))
    assert payload["unit_count"] == 9
    assert payload["units"][0]["predominant_type"] == "predominantemente numérica"
    assert payload["next_step"]


def test_build_list_units_compact_payload(format_module) -> None:
    payload = format_module._build_list_units_compact_payload(_multi_unit_structure(9))
    assert payload["unit_count"] == 9
    assert set(payload["units"][0]) == {"unit_name", "column_count"}


@patch("formatar_resposta._deepseek_translate")
@patch("formatar_resposta._fetch_structure")
def test_main_deliver_full(mock_fetch, mock_translate, format_module) -> None:
    mock_translate.return_value = "Análise completa traduzida."
    core_result = {
        "unit_name": "customers",
        "summary": "Resumo da unidade.",
        "metrics_summary": [{"column": "id"}],
    }
    result = format_module.main(
        core_result=core_result,
        session_id="sess-1",
        action="analyze_unit",
        delivery_plan={
            "action": "deliver_full",
            "format": "full_analysis",
            "message": "Análise completa entregue.",
            "use_llm": True,
            "trim": {"include_summary": True, "include_metrics_summary": True},
        },
    )
    mock_fetch.assert_not_called()
    mock_translate.assert_called_once()
    assert result["response"] == "Análise completa traduzida."
    assert result["last_result"]["summary"] == "Resumo da unidade."


@patch("formatar_resposta._deepseek_translate")
@patch("formatar_resposta._fetch_structure")
def test_main_list_with_summary(mock_fetch, mock_translate, format_module) -> None:
    mock_fetch.return_value = _single_unit_structure(15)
    mock_translate.return_value = "Lista de colunas traduzida."
    result = format_module.main(
        core_result={"unit_name": "customers"},
        session_id="sess-1",
        action="analyze_unit",
        unit_name="customers",
        delivery_plan={
            "action": "list_with_summary",
            "format": "columns_with_summary",
            "message": "Lista de colunas com resumo.",
            "use_llm": True,
        },
    )
    mock_fetch.assert_called_once()
    assert result["response"] == "Lista de colunas traduzida."
    assert result["last_result"]["column_count"] == 15
    prompt = mock_translate.call_args.args[1]
    assert "delivery_plan" in prompt
    assert "formatted_payload" in prompt


@patch("formatar_resposta._fetch_structure")
def test_main_list_units_without_llm(mock_fetch, format_module) -> None:
    mock_fetch.return_value = _multi_unit_structure(9)
    result = format_module.main(
        core_result={},
        session_id="sess-1",
        action="analyze_unit",
        delivery_plan={
            "action": "list_units",
            "format": "units_with_summary",
            "message": "Lista de unidades com resumo.",
            "use_llm": False,
        },
    )
    assert "table_0" in result["response"]
    assert "Próximo passo" in result["response"]
    assert result["last_result"]["unit_count"] == 9


@patch("formatar_resposta._deepseek_translate")
@patch("formatar_resposta._fetch_structure")
def test_main_analyze_vertical_ignores_list_action(mock_fetch, mock_translate, format_module) -> None:
    mock_translate.return_value = "Análise vertical traduzida."
    core_result = {
        "unit_name": "customers",
        "column": "id",
        "summary": "Coluna id.",
        "layer1_metrics": {"cardinality": 5},
    }
    result = format_module.main(
        core_result=core_result,
        session_id="sess-1",
        action="analyze_vertical",
        delivery_plan={
            "action": "list_units",
            "format": "units_with_summary",
            "use_llm": True,
            "trim": {"include_summary": True, "include_layer1": True},
            "depth": "layer1",
        },
    )
    mock_fetch.assert_not_called()
    assert result["response"] == "Análise vertical traduzida."
