from __future__ import annotations

from agnostic.domain.metrics.alpha_ratio import alpha_ratio
from agnostic.domain.metrics.numeric_ratio import numeric_ratio
from agnostic.domain.metrics.spaces_ratio import spaces_ratio
from agnostic.domain.metrics.uppercase_ratio import uppercase_ratio


LAYER2_METRICS = {
    "numeric_ratio": numeric_ratio,
    "alpha_ratio": alpha_ratio,
    "spaces_ratio": spaces_ratio,
    "uppercase_ratio": uppercase_ratio,
}
