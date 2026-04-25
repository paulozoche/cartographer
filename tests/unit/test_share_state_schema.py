from __future__ import annotations

from datetime import datetime
import pytest
from pydantic import ValidationError

from agnostic.interfaces.api.schemas import ShareLinkEnvelopeResponse
from agnostic.interfaces.api.schemas import ShareStateSnapshotResponse


def _base_recorte_state() -> dict:
    return {
        "schema_version": "share-state.v1",
        "kind": "recorte",
        "anchor": {
            "source_fingerprint": "src-fp-001",
            "unit_name": "events",
            "column_name": "event_id",
            "recorte_id": "rc::events::event_id::dominancia::A",
        },
        "path": [
            {"layer": "origem", "node_id": "src::csv::events", "label": "origem"},
            {"layer": "tabela", "node_id": "tb::events", "label": "events"},
            {"layer": "coluna", "node_id": "col::events::event_id", "label": "event_id"},
            {
                "layer": "recorte",
                "node_id": "rc::events::event_id::dominancia::A",
                "label": "dominancia A",
            },
        ],
        "evidencia": {
            "descricao": "Valor dominante observado na coluna.",
            "camada_origem": "coluna",
            "sinais": ["mode_frequency"],
            "amostra": ["A", "B"],
        },
        "transicoes_permitidas": [
            {
                "destino": "valor_celula",
                "alvo_id": "vl::events::event_id::A",
                "motivo": "abrir valor dominante",
            }
        ],
        "source_result_ref": "/tmp/results/events.json",
        "generated_at": datetime.now().isoformat(),
    }


def test_share_state_schema_accepts_recorte_state() -> None:
    payload = _base_recorte_state()

    state = ShareStateSnapshotResponse.model_validate(payload)

    assert state.kind == "recorte"
    assert state.anchor.recorte_id == "rc::events::event_id::dominancia::A"


def test_share_state_schema_rejects_missing_anchor_target() -> None:
    payload = _base_recorte_state()
    payload["anchor"]["recorte_id"] = None

    with pytest.raises(ValidationError):
        ShareStateSnapshotResponse.model_validate(payload)


def test_share_state_schema_rejects_subconjunto_without_recorte_origin() -> None:
    payload = _base_recorte_state()
    payload["kind"] = "subconjunto"
    payload["anchor"]["subconjunto_id"] = "sb::events::event_id::ausencia"
    payload["anchor"]["recorte_id"] = None

    with pytest.raises(ValidationError):
        ShareStateSnapshotResponse.model_validate(payload)


def test_share_state_schema_accepts_subconjunto_with_recorte_origin() -> None:
    payload = _base_recorte_state()
    payload["kind"] = "subconjunto"
    payload["anchor"]["subconjunto_id"] = "sb::events::event_id::ausencia"
    payload["path"].append(
        {
            "layer": "subconjunto",
            "node_id": "sb::events::event_id::ausencia",
            "label": "ausencias",
        }
    )

    state = ShareStateSnapshotResponse.model_validate(payload)

    assert state.kind == "subconjunto"
    assert state.anchor.subconjunto_id == "sb::events::event_id::ausencia"


def test_share_link_envelope_wraps_state_contract() -> None:
    payload = {
        "format_version": "agnostic-share.v1",
        "share_id": "sh_0123456789abcdefABCDEF",
        "scope": "unlisted",
        "expires_at": "2026-12-31T23:59:59Z",
        "state_hash": "c5d2af3f01ab",
        "state": _base_recorte_state(),
        "signature": {
            "version": "hmac-sha256.v1",
            "key_id": "k1",
            "value": "a" * 64,
        },
    }

    envelope = ShareLinkEnvelopeResponse.model_validate(payload)

    assert envelope.format_version == "agnostic-share.v1"
    assert envelope.state.schema_version == "share-state.v1"


def test_share_link_envelope_rejects_non_canonical_share_id() -> None:
    payload = {
        "format_version": "agnostic-share.v1",
        "share_id": "sh_01HXYZABCD",
        "scope": "unlisted",
        "expires_at": "2026-12-31T23:59:59Z",
        "state_hash": "c5d2af3f01ab",
        "state": _base_recorte_state(),
        "signature": {
            "version": "hmac-sha256.v1",
            "key_id": "k1",
            "value": "a" * 64,
        },
    }

    with pytest.raises(ValidationError):
        ShareLinkEnvelopeResponse.model_validate(payload)


def test_share_link_envelope_rejects_expires_at_without_timezone() -> None:
    payload = {
        "format_version": "agnostic-share.v1",
        "share_id": "sh_0123456789abcdefABCDEF",
        "scope": "unlisted",
        "expires_at": "2026-12-31T23:59:59",
        "state_hash": "c5d2af3f01ab",
        "state": _base_recorte_state(),
        "signature": {
            "version": "hmac-sha256.v1",
            "key_id": "k1",
            "value": "a" * 64,
        },
    }

    with pytest.raises(ValidationError):
        ShareLinkEnvelopeResponse.model_validate(payload)


def test_share_link_envelope_rejects_missing_signature() -> None:
    payload = {
        "format_version": "agnostic-share.v1",
        "share_id": "sh_0123456789abcdefABCDEF",
        "scope": "unlisted",
        "expires_at": "2026-12-31T23:59:59Z",
        "state_hash": "c5d2af3f01ab",
        "state": _base_recorte_state(),
    }

    with pytest.raises(ValidationError):
        ShareLinkEnvelopeResponse.model_validate(payload)
