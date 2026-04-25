from __future__ import annotations

from datetime import datetime, timezone
import pytest

from agnostic.application import build_share_state_v1


def _base_path() -> list[dict[str, str]]:
    return [
        {"layer": "origem", "node_id": "src::csv::events", "label": "origem"},
        {"layer": "tabela", "node_id": "tb::events", "label": "events"},
        {"layer": "coluna", "node_id": "col::events::event_id", "label": "event_id"},
        {
            "layer": "recorte",
            "node_id": "rc::events::event_id::dominancia::A",
            "label": "dominancia A",
        },
    ]


def _base_evidence() -> dict:
    return {
        "descricao": "Valor dominante observado na coluna.",
        "camada_origem": "coluna",
        "sinais": ["mode_frequency"],
        "amostra": ["A", "B"],
    }


def _base_transitions() -> list[dict]:
    return [
        {
            "destino": "valor_celula",
            "alvo_id": "vl::events::event_id::A",
            "motivo": "abrir valor dominante",
        }
    ]


def test_build_share_state_v1_generates_recorte_payload() -> None:
    when = datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc)
    payload = build_share_state_v1(
        kind="recorte",
        source_fingerprint="src-fp-001",
        unit_name="events",
        source_result_ref="/tmp/results/events.json",
        evidencia=_base_evidence(),
        transicoes_permitidas=_base_transitions(),
        path=_base_path(),
        column_name="event_id",
        recorte_id="rc::events::event_id::dominancia::A",
        generated_at=when,
    )

    assert payload["schema_version"] == "share-state.v1"
    assert payload["kind"] == "recorte"
    assert payload["anchor"]["recorte_id"] == "rc::events::event_id::dominancia::A"
    assert payload["generated_at"] == when.isoformat()


def test_build_share_state_v1_rejects_missing_anchor_target() -> None:
    with pytest.raises(ValueError):
        build_share_state_v1(
            kind="recorte",
            source_fingerprint="src-fp-001",
            unit_name="events",
            source_result_ref="/tmp/results/events.json",
            evidencia=_base_evidence(),
            transicoes_permitidas=_base_transitions(),
            path=_base_path(),
        )


def test_build_share_state_v1_requires_subconjunto_id_for_subconjunto_kind() -> None:
    with pytest.raises(ValueError):
        build_share_state_v1(
            kind="subconjunto",
            source_fingerprint="src-fp-001",
            unit_name="events",
            source_result_ref="/tmp/results/events.json",
            evidencia=_base_evidence(),
            transicoes_permitidas=_base_transitions(),
            path=_base_path(),
            recorte_id="rc::events::event_id::ausencia::null-empty",
        )


def test_build_share_state_v1_requires_recorte_for_subconjunto_rastreabilidade() -> None:
    with pytest.raises(ValueError):
        build_share_state_v1(
            kind="subconjunto",
            source_fingerprint="src-fp-001",
            unit_name="events",
            source_result_ref="/tmp/results/events.json",
            evidencia=_base_evidence(),
            transicoes_permitidas=_base_transitions(),
            path=_base_path(),
            subconjunto_id="sb::events::event_id::ausencia",
        )


def test_build_share_state_v1_rejects_invalid_path_layer() -> None:
    invalid_path = _base_path()
    invalid_path[0]["layer"] = "foo"
    with pytest.raises(ValueError):
        build_share_state_v1(
            kind="recorte",
            source_fingerprint="src-fp-001",
            unit_name="events",
            source_result_ref="/tmp/results/events.json",
            evidencia=_base_evidence(),
            transicoes_permitidas=_base_transitions(),
            path=invalid_path,
            recorte_id="rc::events::event_id::dominancia::A",
        )
