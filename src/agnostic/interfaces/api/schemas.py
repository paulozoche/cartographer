from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from pydantic import ConfigDict
from pydantic import model_validator
from typing import Literal
from typing import Any

from agnostic.navigation.transitions.recorte_transition_policy import validate_recorte_transition_destinations
from agnostic.sharing.policies.share_id_policy import is_valid_share_id


class AIConsultRequest(BaseModel):
    prompt: str = Field(min_length=1)
    system_prompt: str | None = None


class AIConsultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    model: str
    content: str
    call_number: int
    remaining_calls: int
    quota_per_hour: int
    simulated: bool


class TabularAnalysisRequest(BaseModel):
    unit_name: str = Field(min_length=1)
    columns: list[str] = Field(min_length=1)
    rows: list[list[Any]] = Field(default_factory=list)
    max_rows: int | None = Field(default=None, ge=0)


class SourceInspectionRequest(BaseModel):
    source_type: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    analyze_units: bool = True
    unit_limit: int | None = Field(default=None, ge=0)
    max_rows_per_unit: int | None = Field(default=None, ge=0)
    unit_name: str | None = None


class UnitMetadataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    unit_name: str
    source_unit_identifier: str
    row_count: int | None = None
    raw_attributes: dict[str, Any]


class ColumnStructureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    position: int
    raw_type: str | None = None
    raw_attributes: dict[str, Any]


class UnitStructureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    unit_name: str
    columns: tuple[ColumnStructureResponse, ...]
    raw_attributes: dict[str, Any]


class HeuristicResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    triggered: bool
    score: float
    evidence: dict[str, Any]
    metadata: dict[str, Any]


RecorteTipo = Literal[
    "dominancia",
    "excecao",
    "conflito",
    "padrao",
    "ausencia",
    "identidade_estrutural",
]

RecortePrioridade = Literal["alta", "media", "baixa"]

RecorteEstadoEstrutural = Literal["ativo", "estavel", "ambiguo", "esgotado"]

RecorteDestinoTransicao = Literal["recorte", "valor_celula", "caractere", "subconjunto"]
SignatureType = Literal["dominance", "exception", "conflict", "relation", "absence"]


class RecorteEvidenciaResponse(BaseModel):
    descricao: str = Field(min_length=1)
    camada_origem: Literal["coluna", "recortes"]
    sinais: list[str] = Field(default_factory=list)
    amostra: list[str] = Field(default_factory=list)


class RecorteTransicaoResponse(BaseModel):
    destino: RecorteDestinoTransicao
    alvo_id: str = Field(min_length=1)
    motivo: str = Field(min_length=1)


class RecortePreviewItemResponse(BaseModel):
    value: str
    frequency: int = Field(ge=0)
    value_id: str | None = None


class RecorteValueItemResponse(BaseModel):
    value_id: str = Field(min_length=1)
    value: str
    count: int = Field(ge=0)
    ratio: float = Field(ge=0.0)
    actions: list[str] = Field(default_factory=list)
    transicoes_permitidas: list[RecorteTransicaoResponse] = Field(default_factory=list)


class RecorteInternoResponse(BaseModel):
    id: str = Field(min_length=1)
    tipo: RecorteTipo
    evidencia: RecorteEvidenciaResponse
    prioridade: RecortePrioridade
    estado_estrutural: RecorteEstadoEstrutural
    transicoes_permitidas: list[RecorteTransicaoResponse] = Field(default_factory=list)
    preview: list[RecortePreviewItemResponse] = Field(default_factory=list)
    values: list[RecorteValueItemResponse] = Field(default_factory=list)
    type: SignatureType | str | None = None
    description: str | None = None
    paths: list[str] = Field(default_factory=list)
    impact: float | None = Field(default=None, ge=0.0)
    slice_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    desvio_matriz_transicoes: bool = False
    justificativa_desvio_transicoes: str | None = None

    @model_validator(mode="after")
    def validate_transitions_by_state(self) -> "RecorteInternoResponse":
        if self.estado_estrutural == "esgotado" and self.transicoes_permitidas:
            raise ValueError("Recorte esgotado não pode declarar transições permitidas.")
        if self.estado_estrutural != "esgotado" and not self.transicoes_permitidas:
            raise ValueError("Recorte ativo/estavel/ambiguo deve possuir ao menos uma transição permitida.")
        validate_recorte_transition_destinations(
            recorte_type=self.tipo,
            destinos=(transition.destino for transition in self.transicoes_permitidas),
            override_allowed=self.desvio_matriz_transicoes,
            override_justification=self.justificativa_desvio_transicoes,
        )
        return self


class ColumnAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str = "column"
    name: str = ""
    column_name: str
    signal: float = Field(ge=0.0)
    exploration_score: float = Field(ge=0.0, le=1.0)
    consistency_score: float = Field(ge=0.0)
    explanation: str = ""
    suggested_actions: list[str] = Field(default_factory=list)
    layer1_metrics: dict[str, Any]
    layer2_metrics: dict[str, float]
    heuristics: list[HeuristicResultResponse]
    recortes_internos: list[RecorteInternoResponse] = Field(default_factory=list)


class StandardizedTabularUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tabela_nome: str
    row_count: int
    column_count: int
    column_order: tuple[str, ...]


class TabularAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str = "table"
    name: str = ""
    tabela_nome: str
    signal: float = Field(ge=0.0)
    explanation: str = ""
    suggested_actions: list[str] = Field(default_factory=list)
    summary: str
    metrics_summary: list[str]
    persisted_to: str | None = None
    metadata: UnitMetadataResponse
    structure: UnitStructureResponse
    standardized: StandardizedTabularUnitResponse
    columns: dict[str, ColumnAnalysisResponse]
    ranked_units: list[dict[str, Any]] = Field(default_factory=list)


class SourceMetadataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_type: str
    display_name: str
    source_identifier: str
    fingerprint: str | None = None
    connector_name: str | None = None
    connector_version: str | None = None
    unit_count: int | None = None
    raw_attributes: dict[str, Any]


class SourceUnitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str = "table"
    name: str = ""
    tabela_nome: str
    signal: float = Field(ge=0.0)
    explanation: str = ""
    suggested_actions: list[str] = Field(default_factory=list)
    summary: str
    metrics_summary: list[str]
    persisted_to: str | None = None
    metadata: UnitMetadataResponse
    structure: UnitStructureResponse
    standardized: StandardizedTabularUnitResponse
    columns: dict[str, ColumnAnalysisResponse]
    ranked_units: list[dict[str, Any]] = Field(default_factory=list)


class SourceUnitPreviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tabela_nome: str
    description: str
    row_count: int | None = None
    column_count: int | None = None
    columns_preview: list[str] = Field(default_factory=list)


class SourceInspectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    origem: SourceMetadataResponse
    summary: str
    persisted_to: str | None = None
    tabela_nomes: list[str]
    tabela_previas: list[SourceUnitPreviewResponse] = Field(default_factory=list)
    tabelas: list[SourceUnitResponse]


ShareStateKind = Literal["recorte", "subconjunto"]
ShareScope = Literal["private", "unlisted"]
SharePathLayer = Literal["origem", "tabela", "coluna", "recorte", "subconjunto", "valor_celula", "caractere"]


class ShareStateAnchorResponse(BaseModel):
    source_fingerprint: str = Field(min_length=1)
    unit_name: str = Field(min_length=1)
    column_name: str | None = None
    recorte_id: str | None = None
    subconjunto_id: str | None = None
    criterio_estrutural: str | None = None

    @model_validator(mode="after")
    def validate_anchor_target(self) -> "ShareStateAnchorResponse":
        if not self.recorte_id and not self.subconjunto_id:
            raise ValueError("Estado compartilhável deve referenciar recorte_id ou subconjunto_id.")
        if self.subconjunto_id and not self.recorte_id:
            raise ValueError("subconjunto_id exige recorte_id de origem para rastreabilidade.")
        return self


class ShareStatePathNodeResponse(BaseModel):
    layer: SharePathLayer
    node_id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class ShareStateSnapshotResponse(BaseModel):
    schema_version: Literal["share-state.v1"] = "share-state.v1"
    kind: ShareStateKind
    anchor: ShareStateAnchorResponse
    path: list[ShareStatePathNodeResponse] = Field(default_factory=list, min_length=1)
    evidencia: RecorteEvidenciaResponse
    transicoes_permitidas: list[RecorteTransicaoResponse] = Field(default_factory=list)
    source_result_ref: str = Field(min_length=1)
    generated_at: datetime

    @model_validator(mode="after")
    def validate_state_kind_and_anchor(self) -> "ShareStateSnapshotResponse":
        if self.kind == "recorte" and not self.anchor.recorte_id:
            raise ValueError("Estado do tipo recorte exige anchor.recorte_id.")
        if self.kind == "subconjunto" and not self.anchor.subconjunto_id:
            raise ValueError("Estado do tipo subconjunto exige anchor.subconjunto_id.")
        return self


class ShareLinkSignatureResponse(BaseModel):
    version: Literal["hmac-sha256.v1"] = "hmac-sha256.v1"
    key_id: str = Field(min_length=1)
    value: str = Field(min_length=32)


class ShareLinkEnvelopeResponse(BaseModel):
    format_version: Literal["agnostic-share.v1"] = "agnostic-share.v1"
    share_id: str = Field(min_length=1, max_length=128)
    scope: ShareScope = "unlisted"
    expires_at: datetime
    state_hash: str = Field(min_length=12)
    state: ShareStateSnapshotResponse
    signature: ShareLinkSignatureResponse

    @model_validator(mode="after")
    def validate_share_id_contract(self) -> "ShareLinkEnvelopeResponse":
        if not is_valid_share_id(self.share_id):
            raise ValueError(
                "share_id inválido. Use formato `sh_` + token imprevisível "
                "(22 a 64 caracteres com [A-Za-z0-9_-])."
            )
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at deve incluir timezone explícito.")
        return self
