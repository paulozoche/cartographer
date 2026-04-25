from __future__ import annotations

import pytest
from pydantic import ValidationError

from agnostic.interfaces.api.schemas import RecorteInternoResponse


def _base_payload() -> dict:
    return {
        "id": "rc::events::event_id::dominancia::A",
        "tipo": "dominancia",
        "evidencia": {
            "descricao": "Valor dominante observado na coluna.",
            "camada_origem": "coluna",
            "sinais": ["mode_frequency", "frequency_uniformity"],
            "amostra": ["A", "B", "C"],
        },
        "prioridade": "alta",
        "estado_estrutural": "ativo",
        "transicoes_permitidas": [
            {
                "destino": "valor_celula",
                "alvo_id": "vl::events::event_id::A",
                "motivo": "valor dominante",
            }
        ],
    }


def test_recorte_schema_accepts_active_with_transitions() -> None:
    payload = _base_payload()

    recorte = RecorteInternoResponse.model_validate(payload)

    assert recorte.estado_estrutural == "ativo"
    assert len(recorte.transicoes_permitidas) == 1


def test_recorte_schema_rejects_esgotado_with_transitions() -> None:
    payload = _base_payload()
    payload["estado_estrutural"] = "esgotado"

    with pytest.raises(ValidationError):
        RecorteInternoResponse.model_validate(payload)


def test_recorte_schema_rejects_active_without_transitions() -> None:
    payload = _base_payload()
    payload["transicoes_permitidas"] = []

    with pytest.raises(ValidationError):
        RecorteInternoResponse.model_validate(payload)


def test_recorte_schema_accepts_esgotado_without_transitions() -> None:
    payload = _base_payload()
    payload["estado_estrutural"] = "esgotado"
    payload["transicoes_permitidas"] = []

    recorte = RecorteInternoResponse.model_validate(payload)

    assert recorte.estado_estrutural == "esgotado"
    assert recorte.transicoes_permitidas == []


def test_recorte_schema_rejects_transition_outside_canonical_matrix_without_override() -> None:
    payload = _base_payload()
    payload["transicoes_permitidas"] = [
        {
            "destino": "subconjunto",
            "alvo_id": "sb::events::event_id::dominancia",
            "motivo": "subconjunto para dominancia",
        },
        {
            "destino": "caractere",
            "alvo_id": "ch::events::event_id::A::0",
            "motivo": "aprofundar para caractere",
        },
    ]

    with pytest.raises(ValidationError):
        RecorteInternoResponse.model_validate(payload)


def test_recorte_schema_accepts_transition_outside_canonical_matrix_with_override_and_justification() -> None:
    payload = _base_payload()
    payload["transicoes_permitidas"] = [
        {
            "destino": "caractere",
            "alvo_id": "ch::events::event_id::A::0",
            "motivo": "validacao estrutural pontual",
        }
    ]
    payload["desvio_matriz_transicoes"] = True
    payload["justificativa_desvio_transicoes"] = "evidencia estrutural adicional"

    recorte = RecorteInternoResponse.model_validate(payload)

    assert recorte.desvio_matriz_transicoes is True
    assert recorte.justificativa_desvio_transicoes == "evidencia estrutural adicional"


def test_recorte_schema_rejects_override_without_structural_justification() -> None:
    payload = _base_payload()
    payload["transicoes_permitidas"] = [
        {
            "destino": "caractere",
            "alvo_id": "ch::events::event_id::A::0",
            "motivo": "validacao estrutural pontual",
        }
    ]
    payload["desvio_matriz_transicoes"] = True
    payload["justificativa_desvio_transicoes"] = "curta"

    with pytest.raises(ValidationError):
        RecorteInternoResponse.model_validate(payload)
