from __future__ import annotations

from pathlib import Path

from agnostic.config import DEFAULT_GROQ_MODEL, DEFAULT_RESULTS_DIR, load_app_config


def test_load_app_config_uses_defaults_when_env_is_empty(monkeypatch) -> None:
    monkeypatch.delenv("AGNOSTIC_AI_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    monkeypatch.delenv("GROQ_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AGNOSTIC_DATA_ANALYSER_RESULTS_DIR", raising=False)
    monkeypatch.delenv("AGNOSTIC_CANONICAL_RESULT_MAX_BYTES", raising=False)
    monkeypatch.delenv("AGNOSTIC_RAW_PAYLOAD_PREVIEW_MAX_BYTES", raising=False)
    monkeypatch.delenv("AGNOSTIC_REVOCATION_STORE", raising=False)
    monkeypatch.delenv("AGNOSTIC_REDIS_URL", raising=False)
    monkeypatch.delenv("AGNOSTIC_SERVER_HOST", raising=False)
    monkeypatch.delenv("AGNOSTIC_SERVER_PORT", raising=False)
    monkeypatch.delenv("AGNOSTIC_SERVER_ACCESS_LOG", raising=False)
    monkeypatch.delenv("AGNOSTIC_ANALYSIS_MAX_ROWS_PER_UNIT", raising=False)
    monkeypatch.delenv("AGNOSTIC_ANALYSIS_MAX_UNITS_PER_SOURCE", raising=False)

    config = load_app_config()

    assert config.ai.provider == "auto"
    assert config.ai.groq_api_key == ""
    assert config.ai.groq_model == DEFAULT_GROQ_MODEL
    assert config.ai.groq_base_url == "https://api.groq.com/openai/v1"
    assert config.ai.groq_timeout_seconds == 30.0
    assert config.storage.results_dir == DEFAULT_RESULTS_DIR
    assert config.storage.canonical_result_max_bytes == 1_000_000
    assert config.storage.raw_payload_preview_max_bytes == 200_000
    assert config.revocation.backend == "memory"
    assert config.revocation.redis_url == ""
    assert config.server.host == "127.0.0.1"
    assert config.server.port == 8000
    assert config.server.access_log is False
    assert config.analysis.max_rows_per_unit == 100_000
    assert config.analysis.max_units_per_source == 5


def test_load_app_config_reads_environment(monkeypatch) -> None:
    monkeypatch.setenv("AGNOSTIC_AI_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "secret")
    monkeypatch.setenv("GROQ_MODEL", "test-model")
    monkeypatch.setenv("GROQ_BASE_URL", "https://example.test/api")
    monkeypatch.setenv("GROQ_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("AGNOSTIC_DATA_ANALYSER_RESULTS_DIR", "/tmp/custom-results")
    monkeypatch.setenv("AGNOSTIC_CANONICAL_RESULT_MAX_BYTES", "4096")
    monkeypatch.setenv("AGNOSTIC_RAW_PAYLOAD_PREVIEW_MAX_BYTES", "2048")
    monkeypatch.setenv("AGNOSTIC_REVOCATION_STORE", "redis")
    monkeypatch.setenv("AGNOSTIC_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("AGNOSTIC_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("AGNOSTIC_SERVER_PORT", "9001")
    monkeypatch.setenv("AGNOSTIC_SERVER_ACCESS_LOG", "true")
    monkeypatch.setenv("AGNOSTIC_ANALYSIS_MAX_ROWS_PER_UNIT", "250000")
    monkeypatch.setenv("AGNOSTIC_ANALYSIS_MAX_UNITS_PER_SOURCE", "0")

    config = load_app_config()

    assert config.ai.provider == "groq"
    assert config.ai.groq_api_key == "secret"
    assert config.ai.groq_model == "test-model"
    assert config.ai.groq_base_url == "https://example.test/api"
    assert config.ai.groq_timeout_seconds == 12.5
    assert config.storage.results_dir == Path("/tmp/custom-results")
    assert config.storage.canonical_result_max_bytes == 4096
    assert config.storage.raw_payload_preview_max_bytes == 2048
    assert config.revocation.backend == "redis"
    assert config.revocation.redis_url == "redis://localhost:6379/0"
    assert config.server.host == "0.0.0.0"
    assert config.server.port == 9001
    assert config.server.access_log is True
    assert config.analysis.max_rows_per_unit == 250_000
    assert config.analysis.max_units_per_source is None


def test_load_app_config_persist_enabled_default(monkeypatch) -> None:
    monkeypatch.delenv("AGNOSTIC_PERSIST_CANONICAL_RESULT", raising=False)
    monkeypatch.delenv("AGNOSTIC_MAX_FILES_PER_USER", raising=False)
    monkeypatch.delenv("AGNOSTIC_QUOTA_BYTES_PER_USER", raising=False)

    config = load_app_config()

    assert config.storage.persist_enabled is True
    assert config.storage.max_files_per_user == 50
    assert config.storage.quota_bytes_per_user is None


def test_load_app_config_persist_disabled_via_env(monkeypatch) -> None:
    monkeypatch.setenv("AGNOSTIC_PERSIST_CANONICAL_RESULT", "false")
    monkeypatch.setenv("AGNOSTIC_MAX_FILES_PER_USER", "10")
    monkeypatch.setenv("AGNOSTIC_QUOTA_BYTES_PER_USER", "5000000")

    config = load_app_config()

    assert config.storage.persist_enabled is False
    assert config.storage.max_files_per_user == 10
    assert config.storage.quota_bytes_per_user == 5_000_000
