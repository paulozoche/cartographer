from __future__ import annotations

from agnostic.domain.metrics.alpha_ratio import alpha_ratio
from agnostic.domain.metrics.cardinality import cardinality
from agnostic.domain.metrics.average_length import average_length
from agnostic.domain.metrics.empty_string_ratio import empty_string_ratio
from agnostic.domain.metrics.entropy import entropy
from agnostic.domain.metrics.frequency import frequency
from agnostic.domain.metrics.frequency_uniformity import frequency_uniformity
from agnostic.domain.metrics.length_range import length_range
from agnostic.domain.metrics.length_variance import length_variance
from agnostic.domain.metrics.mode_frequency import mode_frequency
from agnostic.domain.metrics.numeric_ratio import numeric_ratio
from agnostic.domain.metrics.null_ratio import null_ratio
from agnostic.domain.metrics.spaces_ratio import spaces_ratio
from agnostic.domain.metrics.unique_ratio import unique_ratio
from agnostic.domain.metrics.uppercase_ratio import uppercase_ratio
from agnostic.domain.models.tabular import MetricExecutionPolicy


def test_cardinality_counts_distinct_values_ignoring_none() -> None:
    assert cardinality([1, 1, 2, None, 2, 3]) == 3


def test_cardinality_keeps_empty_string_distinct_from_none() -> None:
    assert cardinality(["", "", None, "A"]) == 2


def test_null_ratio_counts_only_none() -> None:
    assert null_ratio([1, None, 2, None]) == 0.5


def test_null_ratio_does_not_treat_empty_string_as_null() -> None:
    assert null_ratio(["", None, "A", ""]) == 0.25


def test_null_ratio_for_empty_column_is_zero() -> None:
    assert null_ratio([]) == 0.0


def test_unique_ratio_ignores_none() -> None:
    assert unique_ratio([1, 1, 2, None]) == 2 / 3


def test_unique_ratio_keeps_empty_string_distinct() -> None:
    assert unique_ratio(["", "", "A", None]) == 2 / 3


def test_unique_ratio_for_empty_non_null_set_is_zero() -> None:
    assert unique_ratio([None, None]) == 0.0


def test_frequency_counts_non_null_values() -> None:
    result = frequency(["A", "A", None, "B"])
    assert result.counts == {"A": 2, "B": 1}
    assert result.sampled is False
    assert result.sample_size == 4
    assert result.total_size == 4
    assert result.coverage_ratio == 1.0


def test_frequency_supports_explicit_sampling_policy() -> None:
    result = frequency(
        ["A", "A", "B", "C", "D"],
        policy=MetricExecutionPolicy(
            mode="sampled",
            sample_size=3,
            sampling_strategy="deterministic_head",
        ),
    )
    assert result.counts == {"A": 2, "B": 1}
    assert result.sampled is True
    assert result.sample_size == 3
    assert result.total_size == 5
    assert result.coverage_ratio == 3 / 5
    assert result.sampling_strategy == "deterministic_head"


def test_mode_frequency_ignores_none() -> None:
    result = mode_frequency(["A", None, "A", "B"])
    assert result.value == "A"
    assert result.count == 2
    assert result.ratio == 2 / 3


def test_mode_frequency_for_empty_non_null_set_is_zero() -> None:
    result = mode_frequency([None, None])
    assert result.value is None
    assert result.count == 0
    assert result.ratio == 0.0


def test_average_length_ignores_none() -> None:
    assert average_length(["AA", None, "B"]) == 1.5


def test_length_range_ignores_none_and_empty_string() -> None:
    result = length_range(["AAA", "", None, "B"])
    assert result == {"min": 1, "max": 3}


def test_length_range_for_empty_effective_values_is_zeroed() -> None:
    assert length_range(["", None]) == {"min": 0, "max": 0}


def test_length_variance_uses_string_lengths() -> None:
    assert length_variance(["AA", "B", None]) == 0.5


def test_empty_string_ratio_counts_only_empty_string() -> None:
    assert empty_string_ratio(["", " ", None, ""]) == 0.5


def test_empty_string_ratio_for_empty_column_is_zero() -> None:
    assert empty_string_ratio([]) == 0.0


def test_numeric_ratio_accepts_numbers_and_numeric_strings() -> None:
    assert numeric_ratio([1, "2", " 3.5 ", "A", None]) == 3 / 4


def test_numeric_ratio_for_empty_non_null_set_is_zero() -> None:
    assert numeric_ratio([None, None]) == 0.0


def test_alpha_ratio_counts_only_pure_alphabetic_values() -> None:
    assert alpha_ratio(["ABC", "abc", "A1", "", None]) == 2 / 4


def test_alpha_ratio_for_empty_non_null_set_is_zero() -> None:
    assert alpha_ratio([None, None]) == 0.0


def test_spaces_ratio_counts_values_containing_space_character() -> None:
    assert spaces_ratio(["A B", "AB", None, "X Y"]) == 2 / 3


def test_spaces_ratio_for_empty_non_null_set_is_zero() -> None:
    assert spaces_ratio([None, None]) == 0.0


def test_uppercase_ratio_counts_values_with_all_letters_uppercase() -> None:
    assert uppercase_ratio(["ABC", "A-1", "Abc", "123", None]) == 2 / 4


def test_uppercase_ratio_for_empty_non_null_set_is_zero() -> None:
    assert uppercase_ratio([None, None]) == 0.0


def test_entropy_for_constant_column_is_zero() -> None:
    assert entropy(["A", "A", "A"]) == 0.0


def test_entropy_for_balanced_binary_column_is_one() -> None:
    assert entropy(["A", "B", "A", "B"]) == 1.0


def test_frequency_uniformity_for_constant_column_is_one() -> None:
    assert frequency_uniformity(["A", "A", "A"]) == 1.0


def test_frequency_uniformity_for_balanced_distribution_is_one() -> None:
    assert frequency_uniformity(["A", "A", "B", "B"]) == 1.0


def test_frequency_uniformity_decreases_when_distribution_is_concentrated() -> None:
    assert frequency_uniformity(["A", "A", "A", "B"]) < 1.0
