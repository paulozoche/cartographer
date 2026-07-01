from __future__ import annotations

from agnostic.domain.metrics.average_length import average_length
from agnostic.domain.metrics.cardinality import cardinality
from agnostic.domain.metrics.completeness_ratio import completeness_ratio
from agnostic.domain.metrics.empty_string_ratio import empty_string_ratio
from agnostic.domain.metrics.frequency import frequency
from agnostic.domain.metrics.length_range import length_range
from agnostic.domain.metrics.length_variance import length_variance
from agnostic.domain.metrics.mode_frequency import mode_frequency
from agnostic.domain.metrics.null_ratio import null_ratio
from agnostic.domain.metrics.unique_ratio import unique_ratio


LAYER1_METRICS = {
    "cardinality": cardinality,
    "null_ratio": null_ratio,
    "unique_ratio": unique_ratio,
    "frequency": frequency,
    "mode_frequency": mode_frequency,
    "average_length": average_length,
    "length_range": length_range,
    "length_variance": length_variance,
    "empty_string_ratio": empty_string_ratio,
    "completeness_ratio": completeness_ratio,
}
