from __future__ import annotations

import pytest

from agnostic.navigation.transitions.recorte_transition_policy import CANONICAL_RECORTE_TRANSITION_MATRIX
from agnostic.navigation.transitions.recorte_transition_policy import allowed_destinations_for_recorte_type
from agnostic.navigation.transitions.recorte_transition_policy import validate_recorte_transition_destinations


def test_canonical_transition_matrix_matches_flow_contract() -> None:
    assert CANONICAL_RECORTE_TRANSITION_MATRIX == {
        "dominancia": frozenset({"subconjunto", "recorte", "valor_celula"}),
        "excecao": frozenset({"recorte", "valor_celula"}),
        "conflito": frozenset({"recorte", "valor_celula"}),
        "ausencia": frozenset({"subconjunto", "valor_celula"}),
        "padrao": frozenset({"subconjunto", "recorte", "valor_celula"}),
        "identidade_estrutural": frozenset({"recorte", "valor_celula"}),
    }


def test_allowed_destinations_returns_empty_for_unknown_type() -> None:
    assert allowed_destinations_for_recorte_type("desconhecido") == frozenset()


def test_validate_transitions_accepts_destinations_within_canonical_matrix() -> None:
    validate_recorte_transition_destinations(
        recorte_type="excecao",
        destinos=["recorte", "valor_celula"],
        override_allowed=False,
        override_justification=None,
    )


def test_validate_transitions_rejects_outside_matrix_without_override() -> None:
    with pytest.raises(ValueError):
        validate_recorte_transition_destinations(
            recorte_type="ausencia",
            destinos=["subconjunto", "caractere"],
            override_allowed=False,
            override_justification=None,
        )


def test_validate_transitions_rejects_override_without_explicit_justification() -> None:
    with pytest.raises(ValueError):
        validate_recorte_transition_destinations(
            recorte_type="ausencia",
            destinos=["subconjunto", "caractere"],
            override_allowed=True,
            override_justification="curta",
        )


def test_validate_transitions_accepts_override_with_structural_justification() -> None:
    validate_recorte_transition_destinations(
        recorte_type="ausencia",
        destinos=["subconjunto", "caractere"],
        override_allowed=True,
        override_justification="evidencia estrutural validada",
    )
