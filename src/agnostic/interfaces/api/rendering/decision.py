# interfaces/api/rendering/decision.py
from __future__ import annotations

from collections import Counter
from html import escape
from typing import Any
from urllib.parse import urlencode

from agnostic.interfaces.api.rendering.cards import render_card_header
from agnostic.interfaces.api.rendering.decisions import _collect_column_decisions
from agnostic.interfaces.api.rendering.signatures import _build_synthetic_signatures
from agnostic.interfaces.value_identity import cell_value_identity_token, stable_value_id


def _recorte_decision_kind(recorte_item: dict[str, Any] | None) -> str:
    if not isinstance(recorte_item, dict):
        return ""
    tipo_local = str(recorte_item.get("tipo") or "").strip().lower()
    metadata_local = recorte_item.get("metadata") if isinstance(recorte_item.get("metadata"), dict) else {}
    type_local = str(metadata_local.get("type") or "").strip().lower()
    name_local = str(metadata_local.get("name") or "").strip().lower()
    if tipo_local == "excecao":
        return "exception"
    if tipo_local == "conflito" or type_local == "conflict" or name_local == "conflict_group":
        return "conflict"
    if tipo_local == "dominancia" or type_local == "dominant" or name_local == "dominant_values":
        return "dominance"
    if tipo_local == "ausencia":
        return "missing"
    return ""


def _render_focused_column_values(
    *,
    result: dict[str, Any] | None,
    selected_unit: str,
    selected_column: str | None,
    source_type: str,
    source_path: str,
    columns_text: str,
    rows_text: str,
    prompt: str,
    focus_mode: bool,
    recorte_id: str,
    relation_column: str,
    relation_values_text: str,
    selected_value: str,
    selected_value_id: str,
    slice_mode: str,
    signature_path: str,
    decision_type: str,
    exception_group: str,
    context_filters_text: str,
    action: str,
    lang: str,
) -> str:
    if not result or not selected_column:
        return ""
    units = result.get("tabelas") or []
    if not units:
        return ""
    current = None
    for unit in units:
        if str(unit.get("tabela_nome") or "") == selected_unit:
            current = unit
            break
    if current is None:
        current = units[0]
    columns = current.get("columns") or {}
    column_payload = columns.get(selected_column) if isinstance(columns, dict) else None
    standardized = current.get("standardized") or {}
    values = list((standardized.get("columns") or {}).get(selected_column) or [])
    recortes = _collect_column_decisions(column_payload if isinstance(column_payload, dict) else None)

    standardized_columns = (standardized.get("columns") or {}) if isinstance(standardized, dict) else {}
    synthetic_signatures = _build_synthetic_signatures(
        column_payload=column_payload if isinstance(column_payload, dict) else None,
        values=values,
        selected_column=str(selected_column or ""),
        standardized_columns=standardized_columns if isinstance(standardized_columns, dict) else None,
    )
    if synthetic_signatures:
        recortes.extend(synthetic_signatures)

    full_counter = Counter(cell_value_identity_token(value) for value in values)
    total_rows_full = max(sum(int(count) for count in full_counter.values()), 1)
    ordered_recortes = sorted(
        recortes,
        key=lambda item: (
            {"alta": 0, "media": 1, "baixa": 2}.get(str(item.get("prioridade") or ""), 9),
            str(item.get("tipo") or ""),
        ),
    )[:5]

    has_intermediate_layer = len(ordered_recortes) > 1
    normalized_decision_type = str(decision_type or "").strip().lower()
    active_recorte = None
    if ordered_recortes:
        if has_intermediate_layer:
            active_recorte = next(
                (item for item in ordered_recortes if str(item.get("id") or "") == recorte_id),
                None,
            )
            if active_recorte is None and normalized_decision_type:
                active_recorte = next(
                    (item for item in ordered_recortes if _recorte_decision_kind(item) == normalized_decision_type),
                    None,
                )
        else:
            active_recorte = ordered_recortes[0]

    if has_intermediate_layer and active_recorte is None:
        decision_label_map = {
            "exception": "Exceção",
            "dominance": "Dominância",
            "conflict": "Conflito",
            "missing": "Ausência",
        }
        decision_cards: list[str] = []
        for item in ordered_recortes:
            item_kind = _recorte_decision_kind(item)
            item_label = decision_label_map.get(item_kind, str(item.get("tipo") or "Decisão").title())
            item_description = str(item.get("description") or "")
            item_id = str(item.get("id") or "")
            query = {
                "source_type": source_type,
                "source_path": source_path,
                "unit_name": selected_unit,
                "column_name": selected_column or "",
                "columns": columns_text,
                "rows": rows_text,
                "prompt": prompt,
                "focus": "1" if focus_mode else "0",
                "lang": lang,
                "action": "coluna",
                "signature_path": "valor/celula",
                "decision_type": item_kind,
                "recorte_id": item_id,
            }
            decision_cards.append(
                f"""
                <a class="metric-link" href="{escape(f'/?{urlencode(query)}')}">
                  <article class="focus-stat-card">
                    {render_card_header(
                        title=item_label,
                        occurrences=None,
                        exploration_level=0.0,
                        can_add_to_collection=True,
                        can_share=True,
                        can_mark_seen=True,
                    )}
                    <div class="decision-card-context">{escape(item_description or 'Abrir decisão')}</div>
                    <div class="metric-action">Abrir decisão</div>
                  </article>
                </a>
                """
            )

        return f"""
          <section class="decision-zone">
            <div class='results-title'>DECISIONS</div>
            <div class='focus-stats focus-cards-horizontal'>
              {''.join(decision_cards)}
            </div>
          </section>
        """

    decision_kind = _recorte_decision_kind(active_recorte)
    value_counter = Counter(cell_value_identity_token(value) for value in values)
    total_rows = max(len(values), 1)
    value_limit = 6

    value_candidates: list[tuple[str, int, str]] = []
    recorte_metadata = (
        active_recorte.get("metadata")
        if isinstance(active_recorte, dict) and isinstance(active_recorte.get("metadata"), dict)
        else {}
    )
    recorte_preview = (
        active_recorte.get("preview")
        if isinstance(active_recorte, dict) and isinstance(active_recorte.get("preview"), list)
        else []
    )
    if decision_kind == "conflict":
        conflict_values = recorte_metadata.get("conflict_values")
        if isinstance(conflict_values, list) and conflict_values:
            value_candidates = [
                (str(token), int(value_counter.get(str(token), 0)), stable_value_id(str(token)))
                for token in conflict_values[:value_limit]
                if str(token)
            ]
        elif recorte_preview:
            value_candidates = [
                (
                    str(item.get("value") or ""),
                    int(item.get("frequency") or value_counter.get(str(item.get("value") or ""), 0)),
                    stable_value_id(str(item.get("value") or "")),
                )
                for item in recorte_preview[:value_limit]
                if isinstance(item, dict) and str(item.get("value") or "").strip()
            ]
    elif decision_kind in {"exception", "missing"} and recorte_preview:
        value_candidates = [
            (
                str(item.get("value") or ""),
                int(item.get("frequency") or value_counter.get(str(item.get("value") or ""), 0)),
                stable_value_id(str(item.get("value") or "")),
            )
            for item in recorte_preview[:value_limit]
            if isinstance(item, dict) and str(item.get("value") or "").strip()
        ]
    elif decision_kind == "dominance" and recorte_preview:
        value_candidates = [
            (
                str(item.get("value") or ""),
                int(item.get("frequency") or value_counter.get(str(item.get("value") or ""), 0)),
                stable_value_id(str(item.get("value") or "")),
            )
            for item in recorte_preview[:value_limit]
            if isinstance(item, dict) and str(item.get("value") or "").strip()
        ]

    if not value_candidates:
        value_candidates = [
            (str(token), int(count), stable_value_id(token))
            for token, count in value_counter.most_common(value_limit)
        ]

    decision_label_map = {
        "exception": "Exceção",
        "dominance": "Dominância",
        "conflict": "Conflito",
        "missing": "Ausência",
    }
    decision_slug_map = {
        "exception": "exceção",
        "dominance": "dominância",
        "conflict": "conflito",
        "missing": "ausência",
    }
    decision_label = decision_label_map.get(decision_kind, "Decisão")
    decision_slug = decision_slug_map.get(decision_kind, "decisão")

    value_cards = []
    for rank, (value_label, frequency, value_id) in enumerate(value_candidates, start=1):
        ratio = frequency / total_rows
        is_recommended = rank == 1
        deepen_query = {
            "source_type": source_type,
            "source_path": source_path,
            "unit_name": selected_unit,
            "column_name": selected_column or "",
            "columns": columns_text,
            "rows": rows_text,
            "prompt": prompt,
            "focus": "1" if focus_mode else "0",
            "lang": lang,
            "action": "valor",
            "selected_value": value_label,
            "selected_value_id": value_id,
            "slice_mode": "deepen",
            "signature_path": "valor/celula",
            "decision_type": decision_kind,
            "recorte_id": str((active_recorte or {}).get("id") or recorte_id or ""),
        }
        new_base_query = {**deepen_query, "slice_mode": "new_base", "action": "tabela"}
        value_cards.append(
            f"""
            <article class="focus-stat-card h-card{(' is-recommended' if is_recommended else '')}">
              {render_card_header(
                  title=str(value_label),
                  occurrences=int(frequency),
                  exploration_level=0.0,
                  can_add_to_collection=True,
                  can_share=True,
                  can_mark_seen=True,
              )}
              <div class="small" style="margin-top: 8px;">Impacto: {int(frequency)} registros ({ratio * 100:.2f}%)</div>
              <div class="decision-card-actions card-actions">
                <a class="button secondary mini" href="{escape(f'/?{urlencode(deepen_query)}')}">Aprofundar análise</a>
                <a class="button secondary mini" href="{escape(f'/?{urlencode(new_base_query)}')}">Criar nova base</a>
              </div>
            </article>
            """
        )

    decision_context_block = f"""
      <div class="results-title">Contexto da decisão</div>
      <section class="origin-overview">
        <div class='origin-line'>Caminho: origem / {escape(str(selected_unit or current.get('tabela_nome') or '—'))} / {escape(str(selected_column or '—'))} / {decision_slug}</div>
        <div class='origin-line'>Tabela: {escape(str(selected_unit or current.get('tabela_nome') or '—'))}</div>
        <div class='origin-line'>Coluna: {escape(str(selected_column or '—'))}</div>
        <div class='origin-line'>Decisão: {decision_label}</div>
      </section>
    """

    return f"""
      <section class="decision-zone">
        {decision_context_block if decision_kind else ""}
        <div class='results-title'>VALOR/CÉLULA</div>
        <div class='focus-stats focus-cards-horizontal'>
          {''.join(value_cards)}
        </div>
      </section>
    """
