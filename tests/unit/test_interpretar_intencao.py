from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "windmill" / "f" / "cartographer" / "interpretar_intencao.py"


def _load_module():
    wmill_mock = MagicMock()
    wmill_mock.get_variable.return_value = "http://core-api.test"
    sys.modules["wmill"] = wmill_mock

    spec = importlib.util.spec_from_file_location("interpretar_intencao", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["interpretar_intencao"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def intent_module(monkeypatch: pytest.MonkeyPatch):
    module = _load_module()
    wmill = MagicMock()
    wmill.get_variable.return_value = "http://core-api.test"
    monkeypatch.setitem(sys.modules, "wmill", wmill)
    monkeypatch.setattr(module, "wmill", wmill)
    return module


UNITS = [
    "crime_scene_report",
    "drivers_license",
    "person",
    "interview",
    "facebook_event_checkin",
]


def test_main_analyze_unit_via_llm(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        intent_module,
        "_llm_interpret_intent",
        lambda *_args, **_kwargs: {
            "action": "analyze_unit",
            "unit_name": "facebook_event_checkin",
        },
    )

    result = intent_module.main("quero ver a tabela do facebook", "sess-1")
    assert result == {
        "action": "analyze_unit",
        "unit_name": "facebook_event_checkin",
        "session_id": "sess-1",
    }


def test_main_analyze_vertical_via_llm(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        intent_module,
        "_llm_interpret_intent",
        lambda *_args, **_kwargs: {
            "action": "analyze_vertical",
            "unit_name": "person",
            "column": "cord_id",
            "depth": "layer2",
        },
    )

    result = intent_module.main("me mostra a coluna cord_id em person", "sess-1")
    assert result == {
        "action": "analyze_vertical",
        "unit_name": "person",
        "column": "cord_id",
        "depth": "layer2",
        "session_id": "sess-1",
    }


FITNESS_UNITS = [
    "get_fit_now_member",
    "gym_location",
    "person",
]


def test_llm_semantic_unit_match(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: FITNESS_UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")

    def fake_llm(message, units, api_key, **kwargs):
        assert api_key == "test-key"
        assert message == "analise a tabela da academia"
        assert kwargs.get("history") == []
        return {
            "action": "analyze_unit",
            "unit_name": "get_fit_now_member",
        }

    monkeypatch.setattr(intent_module, "_llm_interpret_intent", fake_llm)

    result = intent_module.main("analise a tabela da academia", "sess-1")
    assert result == {
        "action": "analyze_unit",
        "unit_name": "get_fit_now_member",
        "session_id": "sess-1",
    }


def test_llm_fallback_without_analysis_keyword(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: FITNESS_UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        intent_module,
        "_llm_interpret_intent",
        lambda *_args, **_kwargs: {
            "action": "analyze_unit",
            "unit_name": "get_fit_now_member",
        },
    )

    result = intent_module.main("a tabela da academia", "sess-1")
    assert result["action"] == "analyze_unit"
    assert result["unit_name"] == "get_fit_now_member"


def test_llm_clarify_on_ambiguity(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: FITNESS_UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")

    def fake_llm(*_args, **_kwargs):
        raise ValueError("Você quer analisar get_fit_now_member ou gym_location?")

    monkeypatch.setattr(intent_module, "_llm_interpret_intent", fake_llm)

    with pytest.raises(ValueError, match="get_fit_now_member ou gym_location"):
        intent_module.main("analise fitness", "sess-1")


def test_llm_pending_action(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: FITNESS_UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        intent_module,
        "_llm_interpret_intent",
        lambda *_args, **_kwargs: {
            "action": "pending",
            "suggested_action": {"action": "analyze_unit", "unit_name": "get_fit_now_member"},
            "suggestion": "Deseja analisar get_fit_now_member?",
            "response": "Deseja analisar get_fit_now_member?",
        },
    )

    result = intent_module.main("talvez a academia", "sess-1", history=[{"role": "user", "content": "oi"}])

    assert result["action"] == "pending"
    assert result["suggested_action"]["unit_name"] == "get_fit_now_member"
    assert "Deseja analisar" in result["suggestion"]


def test_confirmation_executes_pending_action(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        intent_module,
        "_llm_interpret_intent",
        lambda *_args, **_kwargs: {"action": "confirm"},
    )
    pending = {"action": "analyze_unit", "unit_name": "person"}

    result = intent_module.main("sim", "sess-1", pending_action=pending)

    assert result == {
        "action": "analyze_unit",
        "unit_name": "person",
        "session_id": "sess-1",
    }


def test_confirmation_without_pending_returns_clarify(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        intent_module,
        "_llm_interpret_intent",
        lambda *_args, **_kwargs: {"action": "confirm"},
    )

    result = intent_module.main("sim", "sess-1")

    assert result == {
        "action": "clarify",
        "response": "Não há ação pendente.",
        "session_id": "sess-1",
    }


def test_confirmation_ignores_last_action_without_pending(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        intent_module,
        "_llm_interpret_intent",
        lambda *_args, **_kwargs: {"action": "confirm"},
    )
    last_action = {"action": "analyze_unit", "unit_name": "facebook_event_checkin"}

    result = intent_module.main("ok", "sess-1", last_action=last_action)

    assert result == {
        "action": "clarify",
        "response": "Não há ação pendente.",
        "session_id": "sess-1",
    }


SQL_MURDER_UNITS = [
    "crime_scene_report",
    "drivers_license",
    "person",
    "interview",
    "get_fit_now_member",
    "gym",
    "facebook_event_checkin",
    "income",
    "solution",
]

SQL_MURDER_LIST_HISTORY = [
    {
        "role": "assistant",
        "content": (
            "1. crime_scene_report\n"
            "2. drivers_license\n"
            "3. person\n"
            "4. interview\n"
            "5. get_fit_now_member\n"
            "6. gym\n"
            "7. facebook_event_checkin\n"
            "8. income\n"
            "9. solution"
        ),
    }
]


def test_numeric_selection_from_numbered_list(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: SQL_MURDER_UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")

    result = intent_module.main("2", "sess-1", history=SQL_MURDER_LIST_HISTORY)

    assert result == {
        "action": "analyze_unit",
        "unit_name": "drivers_license",
        "session_id": "sess-1",
    }


def test_numeric_selection_with_trailing_punctuation(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: SQL_MURDER_UNITS)

    result = intent_module.main("2.", "sess-1", history=SQL_MURDER_LIST_HISTORY)

    assert result == {
        "action": "analyze_unit",
        "unit_name": "drivers_license",
        "session_id": "sess-1",
    }


def test_invalid_numeric_selection_falls_back_to_llm(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: SQL_MURDER_UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")

    llm_called = False

    def fake_llm(*_args, **_kwargs):
        nonlocal llm_called
        llm_called = True
        return {
            "action": "pending",
            "suggested_action": None,
            "suggestion": "Qual unidade deseja analisar?",
            "response": "Qual unidade deseja analisar?",
        }

    monkeypatch.setattr(intent_module, "_llm_interpret_intent", fake_llm)

    result = intent_module.main("99", "sess-1", history=SQL_MURDER_LIST_HISTORY)

    assert llm_called is True
    assert result["action"] == "pending"
    assert result["session_id"] == "sess-1"


@pytest.mark.parametrize(
    "message",
    ["confirma.", "okay!", "beleza?", "claro."],
)
def test_confirmation_with_punctuation_and_variants(
    intent_module,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(
        intent_module,
        "_llm_interpret_intent",
        lambda *_args, **_kwargs: {"action": "confirm"},
    )
    pending = {"action": "analyze_unit", "unit_name": "person"}

    result = intent_module.main(message, "sess-1", pending_action=pending)

    assert result == {
        "action": "analyze_unit",
        "unit_name": "person",
        "session_id": "sess-1",
    }


def test_main_requires_api_key(intent_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intent_module, "_fetch_units", lambda *_args, **_kwargs: UNITS)
    monkeypatch.setattr(intent_module, "_get_api_key", lambda: None)

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        intent_module.main("quero ver os dados", "sess-1")
