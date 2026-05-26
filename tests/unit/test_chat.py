from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHAT_PATH = ROOT / "chat.py"
SPEC = importlib.util.spec_from_file_location("chat_module", CHAT_PATH)
assert SPEC is not None and SPEC.loader is not None
chat = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chat)


def test_detect_source_type_by_extension() -> None:
    assert chat.detect_source_type("/tmp/sample.csv") == "csv"
    assert chat.detect_source_type("/tmp/sample.parquet") == "parquet"
    assert chat.detect_source_type("/tmp/sample.sqlite") == "sqlite"


def test_detect_source_type_rejects_unsupported_extension() -> None:
    try:
        chat.detect_source_type("/tmp/sample.json")
    except ValueError as exc:
        assert "Extensão não suportada" in str(exc)
    else:  # pragma: no cover - defensive branch
        raise AssertionError("Era esperado um erro para extensão não suportada.")


def test_build_system_prompt_limits_ai_to_structural_result() -> None:
    analysis = chat.analyze_tabular_unit(
        type(
            "_InlineUnit",
            (),
            {
                "unit_name": "events",
                "get_metadata": lambda self: type(
                    "_Metadata",
                    (),
                    {
                        "unit_name": "events",
                        "source_unit_identifier": "inline::events",
                        "row_count": 2,
                        "raw_attributes": {},
                    },
                )(),
                "get_structure": lambda self: type(
                    "_Structure",
                    (),
                    {
                        "unit_name": "events",
                        "columns": (
                            type("_Column", (), {"name": "event_id", "position": 0, "raw_type": None, "raw_attributes": {}})(),
                            type("_Column", (), {"name": "category", "position": 1, "raw_type": None, "raw_attributes": {}})(),
                        ),
                        "raw_attributes": {},
                    },
                )(),
                "get_rows": lambda self: iter([(1, "A"), (2, "B")]),
            },
        )()
    )

    prompt = chat.build_system_prompt(
        source_path="/tmp/events.csv",
        source_type="csv",
        unit_names=["events"],
        current_unit_name="events",
        analysis=analysis,
    )

    assert "nunca substitui o core determinístico" in prompt
    assert '"unit_name": "events"' in prompt
    assert '"column_order"' in prompt
