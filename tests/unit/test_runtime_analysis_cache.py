"""Unit tests for runtime analysis cache module."""

from __future__ import annotations

import pytest

from agnostic.application.cache.runtime_analysis_cache import (
    _CACHE,
    _MAX_CACHE,
    _cache_get,
    _cache_set,
    _make_cache_key,
)


def setup_function() -> None:
    """Clear cache before each test."""
    _CACHE.clear()


def test_make_cache_key_is_deterministic() -> None:
    """Same payload produces same key."""
    payload = {"kind": "source", "path": "/test"}
    key1 = _make_cache_key(payload)
    key2 = _make_cache_key(payload)
    assert key1 == key2


def test_make_cache_key_order_independent() -> None:
    """Key is same regardless of dict insertion order (due to sort_keys)."""
    payload1 = {"a": 1, "b": 2}
    payload2 = {"b": 2, "a": 1}
    assert _make_cache_key(payload1) == _make_cache_key(payload2)


def test_cache_get_returns_none_when_empty() -> None:
    """Get on empty cache returns None."""
    payload = {"kind": "source"}
    result = _cache_get(payload)
    assert result is None


def test_cache_set_and_get() -> None:
    """Set and get work together."""
    payload = {"kind": "source", "path": "/test"}
    data = {"result": "test_data"}
    
    _cache_set(payload, data)
    retrieved = _cache_get(payload)
    
    assert retrieved == data


def test_cache_get_returns_deepcopy() -> None:
    """Get returns deepcopy, not original reference."""
    payload = {"kind": "source"}
    data = {"nested": {"value": 42}}
    
    _cache_set(payload, data)
    retrieved = _cache_get(payload)
    
    # Modify retrieved value
    retrieved["nested"]["value"] = 999  # type: ignore
    
    # Original in cache should be unchanged
    retrieved_again = _cache_get(payload)
    assert retrieved_again["nested"]["value"] == 42  # type: ignore


def test_cache_set_stores_deepcopy() -> None:
    """Set stores deepcopy, so mutation of input doesn't affect cache."""
    payload = {"kind": "source"}
    data = {"nested": {"value": 42}}
    
    _cache_set(payload, data)
    
    # Mutate input data
    data["nested"]["value"] = 999  # type: ignore
    
    # Cache should be unchanged
    retrieved = _cache_get(payload)
    assert retrieved["nested"]["value"] == 42  # type: ignore


def test_cache_get_moves_to_end_lru() -> None:
    """Cache.get moves accessed key to end (LRU pattern)."""
    payload1 = {"id": 1}
    payload2 = {"id": 2}
    
    _cache_set(payload1, {"data": "one"})
    _cache_set(payload2, {"data": "two"})
    
    # Access payload1 to move it to end
    _cache_get(payload1)
    
    # Keys should be ordered: payload2, payload1
    keys = list(_CACHE.keys())
    assert keys[0] == _make_cache_key(payload2)
    assert keys[1] == _make_cache_key(payload1)


def test_cache_set_moves_new_item_to_end() -> None:
    """Cache.set moves item to end."""
    payload1 = {"id": 1}
    payload2 = {"id": 2}
    
    _cache_set(payload1, {"data": "one"})
    _cache_set(payload2, {"data": "two"})
    
    # Last key should be payload2
    last_key = list(_CACHE.keys())[-1]
    assert last_key == _make_cache_key(payload2)


def test_cache_eviction_when_exceeds_max() -> None:
    """Cache evicts oldest (first) item when exceeding _MAX_CACHE."""
    # Fill cache beyond limit
    for i in range(_MAX_CACHE + 5):
        payload = {"id": i}
        _cache_set(payload, {"data": f"item_{i}"})
    
    # Should only have _MAX_CACHE items
    assert len(_CACHE) == _MAX_CACHE
    
    # Oldest items (0-4) should be evicted
    for i in range(5):
        payload = {"id": i}
        assert _cache_get(payload) is None
    
    # Recent items should exist
    payload = {"id": _MAX_CACHE + 4}
    assert _cache_get(payload) is not None


def test_cache_with_complex_payload() -> None:
    """Cache works with complex nested payloads."""
    payload = {
        "kind": "source",
        "source_type": "csv",
        "source_path": "/data/file.csv",
        "analyze_units": True,
        "unit_limit": 10,
    }
    data = {
        "origem": {"display_name": "File", "unit_count": 5},
        "tabelas": [
            {"name": "table1", "signal": 0.8},
            {"name": "table2", "signal": 0.6},
        ],
    }
    
    _cache_set(payload, data)
    retrieved = _cache_get(payload)
    
    assert retrieved == data
    assert retrieved["origem"]["display_name"] == "File"
    assert len(retrieved["tabelas"]) == 2


def test_cache_different_payloads_are_independent() -> None:
    """Different payloads get different cache entries."""
    payload1 = {"kind": "source", "id": 1}
    payload2 = {"kind": "source", "id": 2}
    
    _cache_set(payload1, {"data": "one"})
    _cache_set(payload2, {"data": "two"})
    
    assert _cache_get(payload1) == {"data": "one"}
    assert _cache_get(payload2) == {"data": "two"}


def test_cache_with_none_values_in_payload() -> None:
    """Cache handles None values in payload."""
    payload = {"kind": "source", "unit_name": None, "unit_limit": None}
    data = {"result": "test"}
    
    _cache_set(payload, data)
    retrieved = _cache_get(payload)
    
    assert retrieved == data
