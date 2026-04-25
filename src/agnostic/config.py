from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


DEFAULT_RESULTS_DIR = Path("/tmp/agnostic-data-analyser/runtime/canonical")
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GROQ_TIMEOUT_SECONDS = 30.0
DEFAULT_CANONICAL_RESULT_MAX_BYTES = 1_000_000
DEFAULT_RAW_PAYLOAD_PREVIEW_MAX_BYTES = 200_000
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 8000
DEFAULT_SERVER_ACCESS_LOG = False
DEFAULT_ANALYSIS_MAX_ROWS_PER_UNIT = 100_000
DEFAULT_ANALYSIS_MAX_UNITS_PER_SOURCE = 5

# Proteções de runtime
# persist_enabled: False desliga persistência automática (seguro para dev)
# max_files_per_user: limite de arquivos por usuário por kind (None = sem limite)
# quota_bytes_per_user: limite total de disco por usuário (None = sem limite)
# Ponto de extensão para planos futuros: trocar None pelo valor do plano do usuário
DEFAULT_PERSIST_ENABLED = True
DEFAULT_MAX_FILES_PER_USER = 50
DEFAULT_QUOTA_BYTES_PER_USER = None  # sem limite por padrão
ANONYMOUS_USER_ID = "anonymous"


@dataclass(frozen=True, slots=True)
class AIConfig:
    provider: str = "auto"
    groq_api_key: str = ""
    groq_model: str = DEFAULT_GROQ_MODEL
    groq_base_url: str = DEFAULT_GROQ_BASE_URL
    groq_timeout_seconds: float = DEFAULT_GROQ_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class StorageConfig:
    results_dir: Path = DEFAULT_RESULTS_DIR
    canonical_result_max_bytes: int = DEFAULT_CANONICAL_RESULT_MAX_BYTES
    raw_payload_preview_max_bytes: int = DEFAULT_RAW_PAYLOAD_PREVIEW_MAX_BYTES
    persist_enabled: bool = DEFAULT_PERSIST_ENABLED
    max_files_per_user: int | None = DEFAULT_MAX_FILES_PER_USER
    quota_bytes_per_user: int | None = DEFAULT_QUOTA_BYTES_PER_USER


@dataclass(frozen=True, slots=True)
class RevocationConfig:
    backend: str = "memory"
    redis_url: str = ""


@dataclass(frozen=True, slots=True)
class ServerConfig:
    host: str = DEFAULT_SERVER_HOST
    port: int = DEFAULT_SERVER_PORT
    access_log: bool = DEFAULT_SERVER_ACCESS_LOG


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    max_rows_per_unit: int | None = DEFAULT_ANALYSIS_MAX_ROWS_PER_UNIT
    max_units_per_source: int | None = DEFAULT_ANALYSIS_MAX_UNITS_PER_SOURCE


@dataclass(frozen=True, slots=True)
class AppConfig:
    ai: AIConfig
    storage: StorageConfig
    revocation: RevocationConfig
    server: ServerConfig
    analysis: AnalysisConfig


def load_app_config() -> AppConfig:
    return AppConfig(
        ai=_load_ai_config(),
        storage=_load_storage_config(),
        revocation=_load_revocation_config(),
        server=_load_server_config(),
        analysis=_load_analysis_config(),
    )


def _load_ai_config() -> AIConfig:
    provider = os.getenv("AGNOSTIC_AI_PROVIDER", "auto").strip().lower() or "auto"
    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    groq_model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL
    groq_base_url = os.getenv("GROQ_BASE_URL", DEFAULT_GROQ_BASE_URL).strip() or DEFAULT_GROQ_BASE_URL
    groq_timeout_seconds = _parse_float(
        os.getenv("GROQ_TIMEOUT_SECONDS", str(DEFAULT_GROQ_TIMEOUT_SECONDS)),
        default=DEFAULT_GROQ_TIMEOUT_SECONDS,
    )
    return AIConfig(
        provider=provider,
        groq_api_key=groq_api_key,
        groq_model=groq_model,
        groq_base_url=groq_base_url,
        groq_timeout_seconds=groq_timeout_seconds,
    )


def _load_storage_config() -> StorageConfig:
    results_dir = os.getenv(
        "AGNOSTIC_DATA_ANALYSER_RESULTS_DIR",
        str(DEFAULT_RESULTS_DIR),
    ).strip() or str(DEFAULT_RESULTS_DIR)
    canonical_result_max_bytes = _parse_int(
        os.getenv("AGNOSTIC_CANONICAL_RESULT_MAX_BYTES", str(DEFAULT_CANONICAL_RESULT_MAX_BYTES)),
        default=DEFAULT_CANONICAL_RESULT_MAX_BYTES,
    )
    raw_payload_preview_max_bytes = _parse_int(
        os.getenv("AGNOSTIC_RAW_PAYLOAD_PREVIEW_MAX_BYTES", str(DEFAULT_RAW_PAYLOAD_PREVIEW_MAX_BYTES)),
        default=DEFAULT_RAW_PAYLOAD_PREVIEW_MAX_BYTES,
    )
    persist_enabled = _parse_bool(
        os.getenv("AGNOSTIC_PERSIST_CANONICAL_RESULT", str(DEFAULT_PERSIST_ENABLED).lower()),
        default=DEFAULT_PERSIST_ENABLED,
    )
    max_files_per_user = _parse_optional_int(
        os.getenv("AGNOSTIC_MAX_FILES_PER_USER", str(DEFAULT_MAX_FILES_PER_USER)),
        default=DEFAULT_MAX_FILES_PER_USER,
    )
    quota_bytes_per_user = _parse_optional_int(
        os.getenv("AGNOSTIC_QUOTA_BYTES_PER_USER", "none"),
        default=DEFAULT_QUOTA_BYTES_PER_USER,
    )
    return StorageConfig(
        results_dir=Path(results_dir),
        canonical_result_max_bytes=max(canonical_result_max_bytes, 1_024),
        raw_payload_preview_max_bytes=max(raw_payload_preview_max_bytes, 1_024),
        persist_enabled=persist_enabled,
        max_files_per_user=max_files_per_user,
        quota_bytes_per_user=quota_bytes_per_user,
    )


def _load_revocation_config() -> RevocationConfig:
    backend = os.getenv("AGNOSTIC_REVOCATION_STORE", "memory").strip().lower() or "memory"
    redis_url = os.getenv("AGNOSTIC_REDIS_URL", "").strip()
    return RevocationConfig(backend=backend, redis_url=redis_url)


def _load_server_config() -> ServerConfig:
    host = os.getenv("AGNOSTIC_SERVER_HOST", DEFAULT_SERVER_HOST).strip() or DEFAULT_SERVER_HOST
    port = _parse_int(
        os.getenv("AGNOSTIC_SERVER_PORT", str(DEFAULT_SERVER_PORT)),
        default=DEFAULT_SERVER_PORT,
    )
    access_log = _parse_bool(
        os.getenv("AGNOSTIC_SERVER_ACCESS_LOG", str(DEFAULT_SERVER_ACCESS_LOG).lower()),
        default=DEFAULT_SERVER_ACCESS_LOG,
    )
    return ServerConfig(
        host=host,
        port=max(port, 1),
        access_log=access_log,
    )


def _load_analysis_config() -> AnalysisConfig:
    max_rows_per_unit = _parse_optional_int(
        os.getenv("AGNOSTIC_ANALYSIS_MAX_ROWS_PER_UNIT", str(DEFAULT_ANALYSIS_MAX_ROWS_PER_UNIT)),
        default=DEFAULT_ANALYSIS_MAX_ROWS_PER_UNIT,
    )
    max_units_per_source = _parse_optional_int(
        os.getenv("AGNOSTIC_ANALYSIS_MAX_UNITS_PER_SOURCE", str(DEFAULT_ANALYSIS_MAX_UNITS_PER_SOURCE)),
        default=DEFAULT_ANALYSIS_MAX_UNITS_PER_SOURCE,
    )
    return AnalysisConfig(
        max_rows_per_unit=max(max_rows_per_unit, 1) if max_rows_per_unit is not None else None,
        max_units_per_source=max(max_units_per_source, 1) if max_units_per_source is not None else None,
    )


def _parse_float(value: str, *, default: float) -> float:
    try:
        return float(value)
    except ValueError:
        return default


def _parse_int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _parse_bool(value: str, *, default: bool) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_optional_int(value: str, *, default: int | None) -> int | None:
    normalized = value.strip().lower()
    if normalized in {"", "none", "null", "unlimited", "inf", "infinite", "0"}:
        return None
    try:
        return int(normalized)
    except ValueError:
        return default
