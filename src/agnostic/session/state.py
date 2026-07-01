"""Session state dataclasses for the Cartographer Session Manager."""

from __future__ import annotations

from dataclasses import dataclass, field

from agnostic.domain.knowledge import KnowledgeGraph
from agnostic.session.focus import FocusState


@dataclass
class SourceContext:
    source_path: str
    source_type: str
    units: list[str]


@dataclass
class SchemaContext:
    units: dict[str, dict[str, object]]


@dataclass
class ConversationContext:
    turns: list[dict[str, str]]
    last_user_intent: dict[str, object] | None = None
    last_assistant_suggestion: dict[str, object] | None = None
    presented_context: list[dict[str, object]] = field(default_factory=list)


@dataclass
class ExecutionContext:
    executed_actions: list[dict[str, object]] = field(default_factory=list)
    failed_actions: list[dict[str, object]] = field(default_factory=list)


@dataclass
class PlannerState:
    pending_action: dict[str, object] | None = None
    pending_requirements: list[dict[str, object]] = field(default_factory=list)


@dataclass
class SessionContext:
    source: SourceContext
    schema: SchemaContext
    conversation: ConversationContext
    execution: ExecutionContext
    graph: KnowledgeGraph
    focus: FocusState
    planner: PlannerState


@dataclass
class SessionState:
    """Point-in-time snapshot of session-owned mutable state."""

    history: list[dict[str, str]]
    analysis_by_unit: dict[str, object]
    knowledge_graph: KnowledgeGraph
    user_goal: str
    last_presented_options: list[dict[str, object]]
    execution_log: list[dict[str, str]]
    core_cache: dict[str, object]
    focus_state: FocusState
    session_context: SessionContext | None
    presented_context_turn_id: int
