"""Cache layer for runtime analysis operations.

Provides LRU-like caching with deepcopy semantics for runtime analysis payloads
and their results. Maximum 50 cached items.
"""

import hashlib
import json
from collections import OrderedDict
from copy import deepcopy
from typing import Any

_CACHE = OrderedDict()
_MAX_CACHE = 50


def _make_cache_key(payload: dict) -> str:
    """Generate SHA256 cache key from payload dict (sorted JSON)."""
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Retrieve cached result by payload, moving key to end (LRU).
    
    Returns deepcopy of cached result or None if not found.
    """
    key = _make_cache_key(payload)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return deepcopy(_CACHE[key])
    return None


def _cache_set(payload: dict[str, Any], result: dict[str, Any]) -> None:
    """Store result with LRU eviction.
    
    - Stores deepcopy of result
    - Moves key to end (most recent)
    - Evicts oldest entry if cache exceeds _MAX_CACHE
    """
    key = _make_cache_key(payload)
    _CACHE[key] = deepcopy(result)
    _CACHE.move_to_end(key)
    if len(_CACHE) > _MAX_CACHE:
        _CACHE.popitem(last=False)
