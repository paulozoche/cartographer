from __future__ import annotations

from collections import Counter
from html import escape
from typing import Any

from agnostic.interfaces.api.rendering.cards import render_card_header
from agnostic.interfaces.api.rendering.decisions import _collect_column_decisions


def _column_capability_profile(unit_payload: dict[str, Any] | None) -> dict[str, Any]:
    columns = unit_payload.get("columns") if isinstance(unit_payload, dict) else {}
    if not isinstance(columns, dict):
        return {}
    profile: dict[str, Any] = {}
    for column_name, column_payload in columns.items():
        if not isinstance(column_payload, dict):
            continue
        heuristics = column_payload.get("heuristics") or []
        capability = {
            "signals": Counter(),
            "decisions": _collect_column_decisions(column_payload),
        }
        for item in heuristics:
            if not isinstance(item, dict) or not item.get("triggered"):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                capability["signals"][name] += 1
        profile[str(column_name)] = capability
    return profile


def _column_dominant_recorte(profile: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(profile, dict):
        return ("—", "—")
    signals = profile.get("signals")
    if isinstance(signals, Counter) and signals:
        signal_name, _count = signals.most_common(1)[0]
        return (str(signal_name), str(profile.get("dominant") or "—"))
    return (str(profile.get("dominant") or "—"), "—")


def _render_branch_graph(
    *,
    result: dict[str, Any] | None,
    selected_unit: str,
    selected_column: str,
    detail_mode: bool,
    column_mode: bool,
    lang: str,
) -> str:
    if not isinstance(result, dict):
        return ""
    unit_payloads = result.get("tabelas") or []
    if not isinstance(unit_payloads, list):
        return ""
    cards: list[str] = []
    for unit_payload in unit_payloads:
        if not isinstance(unit_payload, dict):
            continue
        unit_name = str(unit_payload.get("tabela_nome") or "—")
        profile = _column_capability_profile(unit_payload)
        dominant_signal, dominant_recorte = _column_dominant_recorte(profile)
        cards.append(
            f"""
            <section class="metric-card{' selected-metric' if unit_name == selected_unit else ''}">
              <div class="metric-body">
                {render_card_header(
                    title=unit_name,
                    occurrences=None,
                    exploration_level=1.0 if unit_name == selected_unit else 0.0,
                    can_add_to_collection=True,
                    can_share=True,
                    can_mark_seen=detail_mode or column_mode,
                    can_star=True,
                )}
                <div class="metric-meta">{escape(str(dominant_signal))}</div>
                <div class="metric-preview">{escape(str(dominant_recorte))}</div>
                <div class="metric-preview">{escape(str(selected_column or '—'))}</div>
              </div>
            </section>
            """
        )
    return "".join(cards)
