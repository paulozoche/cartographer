from __future__ import annotations

from datetime import datetime, timezone
import pytest

from agnostic.application import build_share_link_envelope_v1
from agnostic.application import build_share_state_v1
from agnostic.application import canonicalize_share_state_v1
from agnostic.application import compute_share_state_hash_v1


def _state_payload() -> dict:
    return build_share_state_v1(
        kind="recorte",
        source_fingerprint="src-fp-001",
        unit_name="events",
        source_result_ref="/tmp/results/events.json",
        evidencia={
            "descricao": "Valor dominante observado na coluna.",
            "camada_origem": "coluna",
            "sinais": ["mode_frequency"],
            "amostra": ["A", "B"],
        },
        transicoes_permitidas=[
            {
                "destino": "valor_celula",
                "alvo_id": "vl::events::event_id::A",
                "motivo": "abrir valor dominante",
            }
        ],
        path=[
            {"layer": "origem", "node_id": "src::csv::events", "label": "origem"},
            {"layer": "tabela", "node_id": "tb::events", "label": "events"},
            {"layer": "coluna", "node_id": "col::events::event_id", "label": "event_id"},
            {"layer": "recorte", "node_id": "rc::events::event_id::dominancia::A", "label": "dominancia A"},
        ],
        recorte_id="rc::events::event_id::dominancia::A",
        generated_at=datetime(2026, 4, 17, 14, 0, tzinfo=timezone.utc),
    )


def test_build_share_link_envelope_v1_generates_envelope_with_hash() -> None:
    state = _state_payload()

    envelope = build_share_link_envelope_v1(
        share_id="sh_0123456789abcdefABCDEF",
        scope="unlisted",
        state=state,
        expires_at="2026-12-31T23:59:59Z",
    )

    assert envelope["format_version"] == "agnostic-share.v1"
    assert envelope["share_id"] == "sh_0123456789abcdefABCDEF"
    assert envelope["scope"] == "unlisted"
    assert envelope["expires_at"] == "2026-12-31T23:59:59Z"
    assert envelope["state_hash"] == compute_share_state_hash_v1(state)


def test_compute_share_state_hash_v1_is_deterministic_for_same_state() -> None:
    state_a = _state_payload()
    state_b = dict(state_a)
    state_b["anchor"] = dict(state_a["anchor"])

    assert compute_share_state_hash_v1(state_a) == compute_share_state_hash_v1(state_b)


def test_build_share_link_envelope_v1_rejects_invalid_scope() -> None:
    with pytest.raises(ValueError):
        build_share_link_envelope_v1(
            share_id="sh_0123456789abcdefABCDEF",
            scope="public",  # type: ignore[arg-type]
            state=_state_payload(),
            expires_at="2026-12-31T23:59:59Z",
        )


def test_build_share_link_envelope_v1_rejects_invalid_state_schema() -> None:
    state = _state_payload()
    state["schema_version"] = "share-state.v0"

    with pytest.raises(ValueError):
        build_share_link_envelope_v1(
            share_id="sh_0123456789abcdefABCDEF",
            scope="unlisted",
            state=state,
            expires_at="2026-12-31T23:59:59Z",
        )


def test_build_share_link_envelope_v1_generates_unpredictable_share_id_when_missing() -> None:
    envelope = build_share_link_envelope_v1(
        state=_state_payload(),
        scope="unlisted",
    )

    assert envelope["share_id"].startswith("sh_")
    assert len(envelope["share_id"]) >= 25


def test_build_share_link_envelope_v1_rejects_non_canonical_share_id() -> None:
    with pytest.raises(ValueError):
        build_share_link_envelope_v1(
            share_id="sh_01HXYZABCD",
            scope="unlisted",
            state=_state_payload(),
        )


def test_build_share_link_envelope_v1_rejects_expires_at_without_timezone() -> None:
    with pytest.raises(ValueError):
        build_share_link_envelope_v1(
            state=_state_payload(),
            scope="unlisted",
            expires_at="2026-12-31T23:59:59",
        )


def test_compute_share_state_hash_v1_ignores_optional_null_fields() -> None:
    state = _state_payload()
    state_with_nulls = dict(state)
    state_with_nulls["anchor"] = dict(state["anchor"])
    state_with_nulls["anchor"]["column_name"] = None
    state_with_nulls["anchor"]["subconjunto_id"] = None
    state_with_nulls["anchor"]["criterio_estrutural"] = None

    assert compute_share_state_hash_v1(state) == compute_share_state_hash_v1(state_with_nulls)


def test_compute_share_state_hash_v1_normalizes_generated_at_utc_notation() -> None:
    state_plus = _state_payload()
    state_z = dict(state_plus)
    state_z["generated_at"] = str(state_plus["generated_at"]).replace("+00:00", "Z")

    assert canonicalize_share_state_v1(state_plus)["generated_at"].endswith("Z")
    assert canonicalize_share_state_v1(state_z)["generated_at"].endswith("Z")
    assert compute_share_state_hash_v1(state_plus) == compute_share_state_hash_v1(state_z)
