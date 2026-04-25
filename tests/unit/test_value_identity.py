from __future__ import annotations

from collections import Counter

from agnostic.interfaces.value_identity import (
    cell_value_identity_token,
    resolve_selected_value_impact,
    stable_value_id,
)


def test_cell_value_identity_token_distinguishes_none_and_empty_string() -> None:
    assert cell_value_identity_token(None) == "__none__"
    assert cell_value_identity_token("") == "__empty__"
    assert cell_value_identity_token(" ") == " "


def test_resolve_selected_value_impact_preserves_spaces_and_punctuation() -> None:
    selected = "  O'Reilly, Inc.  "
    selected_id = stable_value_id(selected)
    active_recorte = {
        "values": [
            {"value": selected, "value_id": selected_id, "count": 7, "ratio": 0.35},
        ]
    }
    resolved = resolve_selected_value_impact(
        selected_value_id=selected_id,
        selected_value=selected,
        active_recorte=active_recorte,
        total_rows=20,
        fallback_counter=Counter(),
    )
    assert resolved["count"] == 7
    assert resolved["ratio"] == 0.35
    assert resolved["source"] == "values_by_id"


def test_resolve_selected_value_impact_simple_alphanumeric() -> None:
    selected = "A1B2"
    selected_id = stable_value_id(selected)
    active_recorte = {"values": [{"value": "A1B2", "value_id": selected_id, "count": 3}]}
    resolved = resolve_selected_value_impact(
        selected_value_id=selected_id,
        selected_value=selected,
        active_recorte=active_recorte,
        total_rows=10,
        fallback_counter=Counter(),
    )
    assert resolved["count"] == 3
    assert resolved["ratio"] == 0.3


def test_resolve_selected_value_impact_none_token_fallback() -> None:
    selected = "__none__"
    resolved = resolve_selected_value_impact(
        selected_value_id="",
        selected_value=selected,
        active_recorte=None,
        total_rows=10,
        fallback_counter=Counter({"__none__": 2, "__empty__": 1}),
    )
    assert resolved["count"] == 2
    assert resolved["ratio"] == 0.2
    assert resolved["source"] == "counter_fallback"


def test_resolve_selected_value_impact_empty_token_fallback() -> None:
    selected = "__empty__"
    resolved = resolve_selected_value_impact(
        selected_value_id="",
        selected_value=selected,
        active_recorte=None,
        total_rows=10,
        fallback_counter=Counter({"__none__": 2, "__empty__": 4}),
    )
    assert resolved["count"] == 4
    assert resolved["ratio"] == 0.4


def test_resolve_selected_value_impact_by_value_id_with_truncated_selected_value() -> None:
    full_value = "123 Long text, with punctuation: O'Reilly & Sons, Ltd."
    selected_id = stable_value_id(full_value)
    active_recorte = {
        "values": [
            {
                "value": full_value,
                "value_id": selected_id,
                "count": 9,
                "ratio": 0.09,
            }
        ]
    }
    resolved = resolve_selected_value_impact(
        selected_value_id=selected_id,
        selected_value="123 Long text",
        active_recorte=active_recorte,
        total_rows=100,
        fallback_counter=Counter(),
    )
    assert resolved["count"] == 9
    assert resolved["ratio"] == 0.09
    assert resolved["resolved_value"] == full_value
    assert resolved["source"] == "values_by_id"


def test_resolve_selected_value_impact_by_value_id_for_navigable_values() -> None:
    cases = [
        "simple",
        "A1B2",
        "123 Long text, with punctuation: O'Reilly & Sons, Ltd.",
        "  value with spaces  ",
        None,
        "",
    ]
    values = [
        {
            "value": value,
            "value_id": stable_value_id(value),
            "count": index + 1,
            "ratio": (index + 1) / 100,
        }
        for index, value in enumerate(cases)
    ]
    active_recorte = {"values": values}

    for item in values:
        resolved = resolve_selected_value_impact(
            selected_value_id=item["value_id"],
            selected_value="display text may be truncated",
            active_recorte=active_recorte,
            total_rows=100,
            fallback_counter=Counter(),
        )

        assert resolved["count"] == item["count"]
        assert resolved["ratio"] == item["ratio"]
        assert resolved["resolved_value"] == item["value"]
        assert resolved["source"] == "values_by_id"


def test_resolve_selected_value_impact_tries_preview_id_before_text_fallback() -> None:
    selected = "Long value, punctuation survives."
    selected_id = stable_value_id(selected)
    active_recorte = {
        "values": [{"value": "display text may be truncated", "value_id": "other", "count": 0}],
        "preview": [{"value": selected, "value_id": selected_id, "frequency": 5}],
    }

    resolved = resolve_selected_value_impact(
        selected_value_id=selected_id,
        selected_value="display text may be truncated",
        active_recorte=active_recorte,
        total_rows=10,
        fallback_counter=Counter({"display text may be truncated": 0}),
    )

    assert resolved["count"] == 5
    assert resolved["ratio"] == 0.5
    assert resolved["resolved_value"] == selected
    assert resolved["source"] == "preview_by_id"


def test_stable_value_id_distinguishes_none_and_empty_string() -> None:
    assert stable_value_id(None) != stable_value_id("")
