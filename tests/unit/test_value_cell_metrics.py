from __future__ import annotations

from agnostic.domain.analysis.compute_value_cell_metrics import (
    build_value_cell_analysis_payload,
    compute_value_cell_metrics,
)


def test_none_value_keeps_null_distinct_from_empty_string() -> None:
    metrics = compute_value_cell_metrics(value=None, total_rows=10, frequency=0)

    assert metrics["is_null"] is True
    assert metrics["is_empty_string"] is False
    assert metrics["char_count"] == 0
    assert metrics["frequency"] == 0
    assert metrics["frequency_ratio"] == 0.0


def test_empty_string_is_not_null() -> None:
    metrics = compute_value_cell_metrics(value="", total_rows=10, frequency=1)

    assert metrics["is_null"] is False
    assert metrics["is_empty_string"] is True
    assert metrics["char_count"] == 0


def test_numeric_string_metrics() -> None:
    metrics = compute_value_cell_metrics(value="12345", total_rows=10, frequency=2)

    assert metrics["digit_count"] == 5
    assert metrics["alpha_count"] == 0
    assert metrics["has_digits"] is True
    assert metrics["has_alpha"] is False
    assert metrics["digit_ratio"] == 1.0


def test_alpha_string_metrics() -> None:
    metrics = compute_value_cell_metrics(value="AbCd", total_rows=8, frequency=2)

    assert metrics["alpha_count"] == 4
    assert metrics["uppercase_count"] == 2
    assert metrics["lowercase_count"] == 2
    assert metrics["digit_count"] == 0
    assert metrics["has_alpha"] is True


def test_alphanumeric_string_metrics() -> None:
    metrics = compute_value_cell_metrics(value="A1b2", total_rows=20, frequency=4)

    assert metrics["alpha_count"] == 2
    assert metrics["digit_count"] == 2
    assert metrics["has_alpha"] is True
    assert metrics["has_digits"] is True


def test_string_with_spaces_metrics() -> None:
    metrics = compute_value_cell_metrics(value="A B", total_rows=10, frequency=1)

    assert metrics["space_count"] == 1
    assert metrics["has_space"] is True
    assert metrics["space_ratio"] == (1 / 3)


def test_string_with_punctuation_metrics() -> None:
    metrics = compute_value_cell_metrics(value="a,b.", total_rows=10, frequency=1)

    assert metrics["punctuation_count"] == 2
    assert metrics["has_punctuation"] is True
    assert metrics["symbol_count"] == 0


def test_string_with_symbols_metrics() -> None:
    metrics = compute_value_cell_metrics(value="$€", total_rows=10, frequency=1)

    assert metrics["symbol_count"] == 2
    assert metrics["has_symbol"] is True
    assert metrics["punctuation_count"] == 0


def test_string_with_diacritic_metrics() -> None:
    metrics = compute_value_cell_metrics(value="ação", total_rows=10, frequency=1)

    assert metrics["has_diacritic"] is True
    assert metrics["has_non_ascii"] is True


def test_string_with_non_ascii_without_diacritic() -> None:
    metrics = compute_value_cell_metrics(value="漢字", total_rows=10, frequency=1)

    assert metrics["has_non_ascii"] is True
    assert metrics["has_diacritic"] is False


def test_mixed_value_with_separators() -> None:
    metrics = compute_value_cell_metrics(value="12-AB/34", total_rows=10, frequency=2)

    assert metrics["has_separator"] is True
    assert metrics["digit_count"] == 4
    assert metrics["alpha_count"] == 2
    assert metrics["punctuation_count"] >= 2


def test_frequency_and_ratio_are_deterministic() -> None:
    metrics = compute_value_cell_metrics(value="X", total_rows=25, frequency=5)

    assert metrics["frequency"] == 5
    assert metrics["frequency_ratio"] == 0.2


def test_value_payload_contract_shape() -> None:
    payload = build_value_cell_analysis_payload(
        table="person",
        column="ssn",
        decision="Exceção",
        value="111-22-3333",
        total_rows=100,
        frequency=3,
    )

    assert payload["type"] == "value"
    assert payload["table"] == "person"
    assert payload["column"] == "ssn"
    assert payload["decision"] == "Exceção"
    assert payload["value"] == "111-22-3333"
    assert payload["impact"]["count"] == 3
    assert payload["impact"]["ratio"] == 0.03
    assert isinstance(payload["metrics"], dict)


def test_value_payload_includes_single_associated_row() -> None:
    payload = build_value_cell_analysis_payload(
        table="person",
        column="code",
        decision="Conflito",
        value="A",
        total_rows=3,
        frequency=1,
        standardized_columns={
            "code": ["A", "B", "C"],
            "name": ["Ann", "Bob", "Cid"],
        },
        column_order=["code", "name"],
    )

    assert payload["associated_rows_total"] == 1
    assert payload["associated_rows_displayed"] == 1
    assert payload["associated_rows_hidden"] == 0
    assert payload["associated_rows_are_identical"] is True
    assert payload["associated_rows"][0]["values"] == {"code": "A", "name": "Ann"}


def test_value_payload_collapses_identical_associated_rows() -> None:
    payload = build_value_cell_analysis_payload(
        table="person",
        column="code",
        decision="Conflito",
        value="A",
        total_rows=3,
        frequency=2,
        standardized_columns={
            "code": ["A", "A", "B"],
            "name": ["Ann", "Ann", "Bob"],
        },
        column_order=["code", "name"],
    )

    assert payload["associated_rows_total"] == 2
    assert payload["associated_rows_displayed"] == 1
    assert payload["associated_rows_hidden"] == 1
    assert payload["associated_rows_are_identical"] is True
    assert payload["representative_row"]["values"] == {"code": "A", "name": "Ann"}


def test_value_payload_samples_different_associated_rows_and_preserves_empty_distinct_from_none() -> None:
    payload = build_value_cell_analysis_payload(
        table="person",
        column="code",
        decision="Conflito",
        value="A",
        total_rows=4,
        frequency=3,
        associated_rows_limit=2,
        standardized_columns={
            "code": ["A", "A", "A", None],
            "name": ["Ann", "", None, "Missing"],
        },
        column_order=["code", "name"],
    )

    assert payload["associated_rows_total"] == 3
    assert payload["associated_rows_displayed"] == 2
    assert payload["associated_rows_hidden"] == 1
    assert payload["associated_rows_are_identical"] is False
    assert payload["associated_rows"][0]["values"]["name"] == "Ann"
    assert payload["associated_rows"][1]["values"]["name"] == ""
