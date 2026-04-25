from __future__ import annotations

from collections.abc import Iterable


# Fonte de verdade: docs/FLOW.md -> "Matriz De Caminhos Padrão Por Tipo"
CANONICAL_RECORTE_TRANSITION_MATRIX: dict[str, frozenset[str]] = {
    "dominancia": frozenset({"subconjunto", "recorte", "valor_celula"}),
    "excecao": frozenset({"recorte", "valor_celula"}),
    "conflito": frozenset({"recorte", "valor_celula"}),
    "ausencia": frozenset({"subconjunto", "valor_celula"}),
    "padrao": frozenset({"subconjunto", "recorte", "valor_celula"}),
    "identidade_estrutural": frozenset({"recorte", "valor_celula"}),
}


def allowed_destinations_for_recorte_type(recorte_type: str) -> frozenset[str]:
    return CANONICAL_RECORTE_TRANSITION_MATRIX.get(recorte_type, frozenset())


def validate_recorte_transition_destinations(
    *,
    recorte_type: str,
    destinos: Iterable[str],
    override_allowed: bool,
    override_justification: str | None,
) -> None:
    allowed = allowed_destinations_for_recorte_type(recorte_type)
    declared = set(destinos)

    unexpected = sorted(destination for destination in declared if destination not in allowed)
    if not unexpected:
        return

    if not override_allowed:
        raise ValueError(
            "Transições fora da matriz canônica para o tipo "
            f"'{recorte_type}': {', '.join(unexpected)}. "
            "Defina desvio_matriz_transicoes=true com justificativa estrutural explícita."
        )

    justification = (override_justification or "").strip()
    if len(justification) < 8:
        raise ValueError(
            "Desvio da matriz canônica exige justificativa estrutural explícita "
            "(mínimo de 8 caracteres)."
        )
