from __future__ import annotations

import json

from agnostic.infrastructure.storage.canonical_result_store import JsonFileCanonicalResultStore


def test_canonical_result_store_persists_full_payload_when_under_limit(tmp_path) -> None:
    store = JsonFileCanonicalResultStore(root_dir=tmp_path, max_bytes=10_000)

    payload = {
        "unit_name": "events",
        "summary": "resumo curto",
        "standardized": {"row_count": 3, "column_count": 2, "column_order": ["id", "name"]},
    }

    path = store.save("tabular", "events", payload)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["payload"] == payload
    assert "payload_truncated" not in saved


def test_canonical_result_store_truncates_payload_when_over_limit(tmp_path) -> None:
    store = JsonFileCanonicalResultStore(root_dir=tmp_path, max_bytes=600)

    payload = {
        "unit_name": "events",
        "summary": "resumo preservado",
        "source": {
            "display_name": "events.csv",
            "source_identifier": "/tmp/events.csv",
            "unit_count": 1,
        },
        "standardized": {
            "row_count": 3,
            "column_count": 2,
            "column_order": ["id", "name"],
        },
        "columns": {
            "blob": {
                "values": ["x" * 2_000],
            }
        },
    }

    path = store.save("tabular", "events", payload)
    saved_text = path.read_text(encoding="utf-8")
    saved = json.loads(saved_text)

    assert len(saved_text.encode("utf-8")) <= 600
    assert saved["payload_truncated"] is True
    assert saved["payload"]["summary"] == "resumo preservado"
    assert saved["payload"]["unit_name"] == "events"
    assert saved["payload"]["standardized"]["row_count"] == 3
    assert "columns" not in saved["payload"]


def test_canonical_result_store_uses_user_dir(tmp_path) -> None:
    store = JsonFileCanonicalResultStore(root_dir=tmp_path, max_bytes=10_000)
    path = store.save("tabular", "events", {"unit_name": "events"}, user_id="user123")
    assert "user123" in str(path)
    assert "tabular" in str(path)


def test_canonical_result_store_persist_disabled_returns_path_without_writing(tmp_path) -> None:
    store = JsonFileCanonicalResultStore(root_dir=tmp_path, max_bytes=10_000, persist_enabled=False)
    path = store.save("tabular", "events", {"unit_name": "events"})
    assert not path.exists()


def test_canonical_result_store_enforces_max_files(tmp_path) -> None:
    store = JsonFileCanonicalResultStore(root_dir=tmp_path, max_bytes=10_000, max_files_per_user=3)
    for i in range(5):
        store.save("tabular", f"unit_{i}", {"unit_name": f"unit_{i}"})
    result_files = [
        f for f in (tmp_path / "anonymous" / "tabular").iterdir()
        if f.is_file() and f.name != "latest.json"
    ]
    assert len(result_files) == 3


def test_canonical_result_store_clear_user_session(tmp_path) -> None:
    store = JsonFileCanonicalResultStore(root_dir=tmp_path, max_bytes=10_000)
    store.save("tabular", "events", {"unit_name": "events"})
    assert (tmp_path / "anonymous").exists()
    store.clear_user_session()
    assert not (tmp_path / "anonymous").exists()


def test_canonical_result_store_quota_blocks_save(tmp_path) -> None:
    store = JsonFileCanonicalResultStore(
        root_dir=tmp_path,
        max_bytes=10_000,
        quota_bytes_per_user=1,  # 1 byte — qualquer payload excede
    )
    path = store.save("tabular", "events", {"unit_name": "events"})
    assert not path.exists()
