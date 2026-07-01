"""Session Manager — sole owner of Cartographer session state."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

from agnostic.domain.analysis.analyze_tabular_unit import TabularUnitAnalysis
from agnostic.domain.knowledge import KnowledgeGraph
from agnostic.session.focus import FocusState, get_session_focus_state, set_session_active_focus
from agnostic.session.state import (
    ConversationContext,
    ExecutionContext,
    PlannerState,
    SessionContext,
    SessionState,
    SourceContext,
    SchemaContext,
)

TabularAnalysis = TabularUnitAnalysis


def _option_identifier(turn_id: int, index: int) -> str:
    return f"turn-{turn_id}-option-{index}"


def _build_presented_option(
    *,
    index: int,
    label: str,
    kind: str,
    source: str,
    turn_id: int | None = None,
    status: str = "pending",
    action_payload: dict[str, object] | None = None,
    reason: str = "",
) -> dict[str, object]:
    option = {
        "index": index,
        "label": label,
        "text": label,
        "display_text": label,
        "kind": kind,
        "source": source,
        "status": "active" if status == "pending" else status,
        "reason": str(reason).strip(),
    }
    if turn_id is not None:
        option["turn_id"] = turn_id
    if isinstance(action_payload, dict):
        option["action_payload"] = dict(action_payload)
        option["suggested_action"] = dict(action_payload)
    return option


def _detect_analysis_intent(user_text: str) -> str:
    normalized = user_text.strip().lower()
    horizontal_keywords = (
        "entre ",
        "relação",
        "relacao",
        "cruz",
        "juntar",
        "ligação",
        "ligacao",
        "comparar",
        "conectar",
    )
    vertical_keywords = (
        "entender",
        "explorar",
        "analisar",
        "investigar",
        "aprofundar",
        "essa tabela",
        "esta tabela",
        "descobrir",
        "resolver",
        "encontrar",
    )
    if any(keyword in normalized for keyword in horizontal_keywords):
        return "horizontal"
    if any(keyword in normalized for keyword in vertical_keywords):
        return "vertical"
    return "unknown"


def _is_internal_recall_option(option: object) -> bool:
    if not isinstance(option, dict):
        return False
    action_payload = option.get("action_payload")
    action_name = str(action_payload.get("action", "")).strip().lower() if isinstance(action_payload, dict) else ""
    option_id = str(option.get("id", "") or option.get("option_id", "")).strip().lower()
    label = str(option.get("label", "") or option.get("display_text", "") or option.get("text", "")).strip().lower()
    reason = str(option.get("reason", "")).strip().lower()
    if "recall" in option_id:
        return True
    if action_name == "recall":
        return True
    if "recuperar detalhes operacionais" in label:
        return True
    return "recuperar detalhes operacionais" in reason


class SessionManager:
    """Guardian of session state — no flow coordination, decisions, or execution."""

    def __init__(self) -> None:
        self.history: list[dict[str, str]] = []
        self.analysis_by_unit: dict[str, object] = {}
        self.knowledge_graph = KnowledgeGraph()
        self.user_goal: str = ""
        self._last_presented_options: list[dict[str, object]] = []
        self._execution_log: list[dict[str, str]] = []
        self._core_cache: dict[str, object] = {}
        self._focus_state = FocusState()
        self._presented_context_turn_id = 0
        self.session_context: SessionContext | None = None

    def initialize_context(
        self,
        *,
        source: SourceContext,
        schema: SchemaContext,
    ) -> SessionContext:
        self.session_context = SessionContext(
            source=source,
            schema=schema,
            conversation=ConversationContext(turns=self.history),
            execution=ExecutionContext(),
            graph=self.knowledge_graph,
            focus=self._focus_state,
            planner=PlannerState(),
        )
        return self.session_context

    def get_history(self) -> list[dict]:
        return self.history

    def get_analysis_by_unit(self, unit_name: str) -> TabularAnalysis | None:
        analysis = self.analysis_by_unit.get(unit_name)
        return analysis if isinstance(analysis, TabularUnitAnalysis) else None

    def get_knowledge_graph(self) -> KnowledgeGraph:
        return self.knowledge_graph

    def get_user_goal(self) -> str:
        return self.user_goal

    def get_last_presented_options(self) -> list[dict]:
        return list(self._last_presented_options)

    def get_execution_log(self) -> list[dict]:
        return list(self._execution_log)

    def get_core_cache(self, key: str) -> Any | None:
        return self._core_cache.get(key)

    def get_focus_state(self) -> FocusState:
        return self._focus_state

    def get_state(self) -> SessionState:
        return SessionState(
            history=list(self.history),
            analysis_by_unit=dict(self.analysis_by_unit),
            knowledge_graph=self.knowledge_graph,
            user_goal=self.user_goal,
            last_presented_options=list(self._last_presented_options),
            execution_log=list(self._execution_log),
            core_cache=dict(self._core_cache),
            focus_state=self._focus_state,
            session_context=self.session_context,
            presented_context_turn_id=self._presented_context_turn_id,
        )

    def add_history_turn(self, role: str, content: str) -> None:
        if not isinstance(role, str) or not role.strip():
            raise ValueError("role must be a non-empty string")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        turn = {"role": role.strip(), "content": content}
        self.history.append(turn)
        if self.session_context is not None:
            self.session_context.conversation.turns = self.history

    def set_analysis_by_unit(self, unit_name: str, analysis: TabularAnalysis) -> None:
        normalized_unit_name = str(unit_name).strip()
        if not normalized_unit_name:
            raise ValueError("unit_name must be a non-empty string")
        if analysis is None:
            raise ValueError("analysis must not be None")
        self.analysis_by_unit[normalized_unit_name] = analysis

    def set_user_goal(self, goal: str) -> None:
        if not isinstance(goal, str):
            raise ValueError("goal must be a string")
        self.user_goal = goal

    def set_last_presented_options(self, options: list[dict]) -> None:
        if not isinstance(options, list):
            raise ValueError("options must be a list")
        self._last_presented_options = [dict(option) for option in options if isinstance(option, dict)]
        if self.session_context is not None:
            self.session_context.conversation.presented_context = list(self._last_presented_options)

    def add_to_execution_log(self, entry: dict) -> None:
        if not isinstance(entry, dict):
            raise ValueError("entry must be a dict")
        normalized = {str(key): str(value) for key, value in entry.items()}
        self._execution_log.append(normalized)
        if len(self._execution_log) > 25:
            self._execution_log[:] = self._execution_log[-25:]
        if self.session_context is not None:
            self.session_context.execution.executed_actions.append(dict(entry))
            if len(self.session_context.execution.executed_actions) > 25:
                self.session_context.execution.executed_actions = self.session_context.execution.executed_actions[-25:]

    def set_core_cache(self, key: str, value: Any) -> None:
        normalized_key = str(key).strip()
        if not normalized_key:
            raise ValueError("key must be a non-empty string")
        self._core_cache[normalized_key] = value

    def set_focus_state(self, state: FocusState) -> None:
        if not isinstance(state, FocusState):
            raise ValueError("state must be a FocusState instance")
        self._focus_state = state
        if self.session_context is not None:
            self.session_context.focus = state

    def register_presented_options(self, options: list[dict]) -> None:
        if not isinstance(options, list):
            raise ValueError("options must be a list")
        logger.info("register_presented_options: recebidas %d opções", len(options))
        self._presented_context_turn_id = int(self._presented_context_turn_id) + 1
        turn_id = self._presented_context_turn_id
        normalized: list[dict[str, object]] = []
        for index, option in enumerate(options, start=1):
            if not isinstance(option, dict):
                logger.warning("opção %d não é dict: %r", index, option)
                continue
            item = dict(option)
            if _is_internal_recall_option(item):
                logger.info("opção %d filtrada por internal_recall", index)
                continue
            item["index"] = index
            item["turn_id"] = turn_id
            item["option_id"] = str(item.get("option_id") or _option_identifier(turn_id, index))
            item["status"] = "active" if str(item.get("status", "")).strip() in {"", "pending"} else str(item.get("status"))
            if "display_text" not in item:
                item["display_text"] = str(item.get("text") or item.get("label") or "").strip()
            if "text" not in item:
                item["text"] = str(item.get("display_text") or item.get("label") or "").strip()
            normalized.append(item)
            logger.info("opção %d registrada: %s", index, item.get("label"))
        for index, item in enumerate(normalized, start=1):
            item["index"] = index
            item["option_id"] = str(item.get("option_id") or _option_identifier(turn_id, index))
        self._last_presented_options = normalized
        logger.info("total de opções registradas: %d", len(self._last_presented_options))
        if self.session_context is not None:
            self.session_context.conversation.presented_context = list(self._last_presented_options)

    def update_knowledge_graph(self, result: dict[str, object], *, action: str, host: Any) -> None:
        graph = self.knowledge_graph
        node = host._knowledge_node_from_result(result, action=action)
        if any(existing.unit == node.unit and existing.label == node.label for existing in graph.nodes):
            return
        graph.nodes.append(node)
        heuristic_edge = host._heuristic_knowledge_edge(node)
        if heuristic_edge is not None:
            graph.edges.append(heuristic_edge)
            host.refresh_index_extensions()
            return
        edge = host._curate_knowledge_edge(node)
        if edge is not None:
            graph.edges.append(edge)
        host.refresh_index_extensions()

    def sync_active_focus_from_session(self, session: object) -> None:
        focus_state = get_session_focus_state(session)
        self._focus_state = focus_state
        if self.session_context is not None:
            self.session_context.focus = focus_state

    def apply_active_focus_to_session(self, session: object, value: dict[str, object] | None) -> None:
        set_session_active_focus(session, value)
        self.sync_active_focus_from_session(session)

    def sync_session_context(
        self,
        *,
        source_units: list[str] | None = None,
        schema_units: dict[str, dict[str, object]] | None = None,
        pending_requirements: list[dict[str, object]] | None = None,
    ) -> None:
        if self.session_context is None:
            return
        if source_units is not None:
            self.session_context.source.units = list(source_units)
        if schema_units is not None:
            self.session_context.schema.units = dict(schema_units)
        self.session_context.conversation.turns = self.history
        self.session_context.conversation.presented_context = list(self._last_presented_options)
        self.session_context.graph = self.knowledge_graph
        self.session_context.focus = self._focus_state
        if pending_requirements is not None:
            self.session_context.planner.pending_requirements = list(pending_requirements)

    def _goal_score(self, option: dict[str, object], *, goal_tokens: set[str]) -> int:
        from agnostic.planner.explicit import _robust_normalize

        option_text = _robust_normalize(
            str(option.get("label", "")) + " " + str(option.get("reason", ""))
        )
        score = sum(1 for token in goal_tokens if token in option_text)
        logger.debug("[goal_sort] option=%r score=%d", option.get("label", ""), score)
        return score

    def _has_individual_followup_execution(
        self,
        unit_name: str,
        *,
        execution_log: list[dict[str, str]],
    ) -> bool:
        normalized_unit = str(unit_name).strip()
        if not normalized_unit:
            return False
        for entry in execution_log:
            if not isinstance(entry, dict):
                continue
            action_name = str(entry.get("action", "")).strip()
            if action_name not in {"analyze_unit", "query", "request_new_query", "analyze_vertical"}:
                continue
            target_unit = str(
                entry.get("unit_name")
                or entry.get("table")
                or entry.get("unit")
                or ""
            ).strip()
            if not target_unit and action_name in {"query", "request_new_query"}:
                target_unit = str(entry.get("query_id", "")).strip()
            if target_unit == normalized_unit:
                return True
            sql_text = str(entry.get("sql", "") or entry.get("suggested_sql", "")).strip().lower()
            if sql_text and f"from {normalized_unit.lower()}" in sql_text:
                return True
        return False

    def _visible_presented_options(
        self,
        options: list[dict[str, object]],
        *,
        execution_log: list[dict[str, str]],
        just_executed_action: dict[str, object] | None,
    ) -> tuple[list[dict[str, object]], bool]:
        from agnostic.interface.formatter import _visible_presented_options

        return _visible_presented_options(
            options,
            execution_log=execution_log,
            just_executed_action=just_executed_action,
        )

    def update_presented_options(self, session: object | None = None) -> None:
        """Atualiza as opções acionáveis visíveis com base no knowledge_graph."""
        host = session
        existing_pending_action = None
        if host is not None and hasattr(host, "session_context"):
            existing_pending_action = host.session_context.planner.pending_action
        elif self.session_context is not None:
            existing_pending_action = self.session_context.planner.pending_action
        if isinstance(existing_pending_action, dict) and existing_pending_action.get("action"):
            from agnostic.interface.formatter import _canonical_action_signature

            presented_options = list(
                getattr(host, "_last_presented_options", []) or []
                if host is not None
                else self._last_presented_options
            )
            last_executed = (
                getattr(host, "_last_executed_action_payload", None)
                if host is not None
                else getattr(self, "_last_executed_action_payload", None)
            )
            pending_signature = _canonical_action_signature(existing_pending_action)
            preserve_options = False
            if len(presented_options) == 1:
                single_option = presented_options[0]
                if isinstance(single_option, dict):
                    single_payload = single_option.get("action_payload") or single_option.get("suggested_action")
                    if _canonical_action_signature(single_payload) == pending_signature:
                        preserve_options = True
            if (
                not preserve_options
                and isinstance(last_executed, dict)
                and _canonical_action_signature(last_executed) == pending_signature
            ):
                preserve_options = True
            if preserve_options:
                logger.info(
                    "update_presented_options skipped: pending_action=%s options_preserved=%d",
                    existing_pending_action.get("action"),
                    len(presented_options),
                )
                return

        history = list(getattr(host, "history", []) or []) if host is not None else self.history
        latest_user_text = ""
        for turn in reversed(history):
            if isinstance(turn, dict) and str(turn.get("role", "")).strip() == "user":
                latest_user_text = str(turn.get("content", "")).strip()
                break

        user_goal = str(getattr(host, "user_goal", "") or "") if host is not None else self.user_goal
        intent_text = f"{user_goal} {latest_user_text}".lower()
        column_analysis_triggers = [
            "por região", "por regiao", "por coluna", "por tipo", "assinatura por",
            "distribuição por", "distribuicao por", "padrões por", "padroes por",
            "agrupar por", "por categoria", "por local", "por período", "por periodo",
            "por data", "por grupo",
        ]
        if host is not None and any(trigger in intent_text for trigger in column_analysis_triggers):
            last_analyzed = host._last_analyzed_unit()
            if last_analyzed:
                analysis = getattr(host, "analysis_by_unit", {}).get(last_analyzed)
                relevant_columns = host._relevant_columns_for_region_analysis(analysis)
                if relevant_columns:
                    column_options = []
                    for idx, col in enumerate(relevant_columns, start=1):
                        sql = host._build_column_distribution_sql(col)
                        column_options.append(
                            _build_presented_option(
                                index=idx,
                                label=f"Analisar padrões por '{col}'",
                                kind="executable",
                                source="column_analysis",
                                action_payload={
                                    "action": "request_new_query",
                                    "description": f"padrões por {col}",
                                    "suggested_sql": sql,
                                },
                                reason=f"coluna {idx} de {len(relevant_columns)}",
                            )
                        )
                    if hasattr(host, "register_presented_options"):
                        host.register_presented_options(column_options)
                    else:
                        self.register_presented_options(column_options)
                    return

        graph = getattr(host, "knowledge_graph", None) if host is not None else self.knowledge_graph
        if graph is None:
            if host is not None:
                host._last_presented_options = []
                if hasattr(host, "set_pending_action"):
                    host.set_pending_action(None)
            else:
                self._last_presented_options = []
            return

        pending_reqs = graph.pending_requirements() if callable(graph.pending_requirements) else []
        explicit_horizontal_intent = _detect_analysis_intent(latest_user_text) == "horizontal"
        execution_log = list(getattr(host, "_execution_log", []) or []) if host is not None else list(self._execution_log)

        actionable: list[dict[str, object]] = []
        for req in pending_reqs:
            if not isinstance(req, dict):
                continue
            suggested = req.get("suggested_action", {})
            if not isinstance(suggested, dict):
                continue
            action = suggested.get("action")
            if action not in ("analyze_unit", "analyze_horizontal", "request_new_query", "analyze_vertical", "schema"):
                continue
            if action == "analyze_horizontal" and not explicit_horizontal_intent:
                unit_a = str(suggested.get("unit_a", "")).strip()
                unit_b = str(suggested.get("unit_b", "")).strip()
                if not self._has_individual_followup_execution(unit_a, execution_log=execution_log) and not self._has_individual_followup_execution(unit_b, execution_log=execution_log):
                    continue
            description = str(req.get("description", req.get("id", ""))).strip()
            if not description:
                continue
            actionable.append(
                _build_presented_option(
                    index=len(actionable) + 1,
                    label=description,
                    kind="executable",
                    source="core_result",
                    action_payload=dict(suggested),
                    reason=str(req.get("reason", "")).strip(),
                )
            )

        user_goal = str(getattr(host, "user_goal", "") or "") if host is not None else self.user_goal
        if user_goal:
            from agnostic.planner.explicit import _robust_normalize

            goal_tokens = {token for token in _robust_normalize(user_goal).split() if len(token) >= 3}
            logger.debug("[goal_sort] user_goal=%r → goal_tokens=%r", user_goal, goal_tokens)
            if goal_tokens:
                actionable.sort(key=lambda option: self._goal_score(option, goal_tokens=goal_tokens), reverse=True)

        actionable, _ = self._visible_presented_options(
            actionable,
            execution_log=execution_log,
            just_executed_action=None,
        )

        if host is not None and hasattr(host, "session_context"):
            host.session_context.planner.pending_requirements = list(pending_reqs)
        elif self.session_context is not None:
            self.session_context.planner.pending_requirements = list(pending_reqs)

        if host is not None and hasattr(host, "register_presented_options"):
            host.register_presented_options(actionable)
        elif host is not None:
            host._last_presented_options = actionable
        else:
            self.register_presented_options(actionable)
