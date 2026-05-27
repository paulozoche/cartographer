# Module Registry

## Status

`ACTIVE`

## Level

`GLOBAL REGISTRY`

## Objective

Registrar os módulos ativos do projeto, suas responsabilidades públicas e seus limites.

Este documento é um mapa de fronteiras.

Ele não substitui contratos formais entre módulos.

Contratos formais devem ser registrados em:

- `docs/IO_REGISTRY.json`
- `docs/IO_REGISTRY.md`
- `src/agnostic/<module>/CONTRACT.md`

---

## Rules

- Cada módulo deve ter responsabilidade explícita.
- Cada módulo deve possuir documentação local própria quando formalizado.
- Comunicação entre módulos deve ocorrer por contratos públicos.
- Implementação interna não é contrato público.
- Reexports públicos podem existir por compatibilidade, mas não definem posse de responsabilidade.
- Diretórios que existem apenas por `__pycache__` não contam como módulos ativos.
- Arquivos marcados como `NEEDS_ARCHITECTURE_DECISION` não devem ser movidos automaticamente.

---

## Active Modules

### `domain`

Path:

`src/agnostic/domain/`

Responsibility:

Produzir análise estrutural determinística.

Owns:

- métricas;
- heurísticas;
- padronização analítica;
- cálculo de `signal`;
- ranking estrutural;
- análise tabular;
- modelos analíticos;
- explicações estruturais;
- sugestões estruturais.

Does not own:

- API;
- UI;
- IA;
- persistência;
- exportação;
- compartilhamento;
- navegação de interface;
- adaptação de fontes externas.

Important subpackages:

- `domain/analysis/`
- `domain/metrics/`
- `domain/heuristics/`
- `domain/models/`

Planned local docs:

- `src/agnostic/domain/CONTRACT_SUMMARY.md`
- `src/agnostic/domain/CONTRACT.md`
- `src/agnostic/domain/AGENT.md`
- `src/agnostic/domain/CONTEXT.md`

---

### `application`

Path:

`src/agnostic/application/`

Responsibility:

Orquestrar casos de uso e coordenar módulos especializados sem assumir suas responsabilidades internas.

Owns:

- casos de uso;
- cache de application;
- porta de resultado canônico;
- coordenação entre domínio, apresentação, infraestrutura, IA, sharing e interfaces.

Does not own:

- cálculo analítico;
- métricas;
- heurísticas;
- assinatura de compartilhamento;
- políticas de recorte;
- integração concreta de IA;
- storage concreto;
- rendering visual.

Active subpackages:

- `application/cache/`
- `application/ports/`
- `application/use_cases/`

Non-active runtime directories:

- `application/policies/` appears only due to `__pycache__`.
- `application/services/` appears only due to `__pycache__`.

Pending decisions:

- `src/agnostic/application/ports/tabular_source.py` is `NEEDS_ARCHITECTURE_DECISION`.

Planned local docs:

- `src/agnostic/application/CONTRACT_SUMMARY.md`
- `src/agnostic/application/CONTRACT.md`
- `src/agnostic/application/AGENT.md`
- `src/agnostic/application/CONTEXT.md`

---

### `ai`

Path:

`src/agnostic/ai/`

Responsibility:

Definir e executar integração de IA pós-core.

Owns:

- contrato de orquestração de IA;
- resposta de IA;
- consulta de IA pós-core.

Does not own:

- análise inicial;
- métricas;
- heurísticas;
- ranking;
- alteração de `signal`;
- persistência;
- UI;
- contrato de compartilhamento.

Important subpackages:

- `ai/ports/`

Important files:

- `ai/consult_ai.py`
- `ai/ports/ai_orchestrator.py`

Planned local docs:

- `src/agnostic/ai/CONTRACT_SUMMARY.md`
- `src/agnostic/ai/CONTRACT.md`
- `src/agnostic/ai/AGENT.md`
- `src/agnostic/ai/CONTEXT.md`

---

### `sharing`

Path:

`src/agnostic/sharing/`

Responsibility:

Gerar, validar, assinar, verificar e revogar estados compartilháveis reproduzíveis.

Owns:

- share state;
- share envelope;
- políticas de share id;
- políticas de chave de assinatura;
- assinatura e verificação de share link;
- porta de revogação;
- contratos de compartilhamento.

Does not own:

- análise;
- métricas;
- heurísticas;
- ranking;
- UI;
- persistência analítica como fonte de verdade;
- navegação estrutural interna.

Important subpackages:

- `sharing/envelope/`
- `sharing/policies/`
- `sharing/ports/`
- `sharing/services/`
- `sharing/state/`

Planned local docs:

- `src/agnostic/sharing/CONTRACT_SUMMARY.md`
- `src/agnostic/sharing/CONTRACT.md`
- `src/agnostic/sharing/AGENT.md`
- `src/agnostic/sharing/CONTEXT.md`

---

### `navigation`

Path:

`src/agnostic/navigation/`

Responsibility:

Representar recortes, slices e transições de navegação estrutural.

Owns:

- slices;
- políticas de transição;
- validação de transições de recorte;
- contratos de navegação.

Does not own:

- análise estrutural;
- métricas;
- heurísticas;
- IA;
- persistência;
- renderização final;
- assinatura de compartilhamento.

Important subpackages:

- `navigation/slices/`
- `navigation/transitions/`

Planned local docs:

- `src/agnostic/navigation/CONTRACT_SUMMARY.md`
- `src/agnostic/navigation/CONTRACT.md`
- `src/agnostic/navigation/AGENT.md`
- `src/agnostic/navigation/CONTEXT.md`

---

### `presentation`

Path:

`src/agnostic/presentation/`

Responsibility:

Transformar resultados estruturais em texto humano, resumo ou Markdown.

Owns:

- summaries;
- Markdown;
- texto pós-core;
- adaptação textual baseada em contratos estruturais.

Does not own:

- análise;
- métricas;
- heurísticas;
- `signal`;
- ranking;
- persistência;
- API;
- IA;
- compartilhamento.

Important subpackages:

- `presentation/markdown/`
- `presentation/summaries/`

Planned local docs:

- `src/agnostic/presentation/CONTRACT_SUMMARY.md`
- `src/agnostic/presentation/CONTRACT.md`
- `src/agnostic/presentation/AGENT.md`
- `src/agnostic/presentation/CONTEXT.md`

---

### `interfaces`

Path:

`src/agnostic/interfaces/`

Responsibility:

Conter helpers mínimos de fronteira sem assumir API, rotas ou rendering.

Owns:

- identidade de valor para fronteiras externas;
- normalização leve de comparação entre valores.

Does not own:

- análise;
- métricas;
- heurísticas;
- ranking;
- API HTTP;
- rotas;
- schemas de request/response;
- rendering visual;
- assets estáticos;
- persistência analítica;
- assinatura de compartilhamento;
- regras internas de domínio.

Important files:

- `interfaces/value_identity.py`

Planned local docs:

- `src/agnostic/interfaces/CONTRACT_SUMMARY.md`
- `src/agnostic/interfaces/CONTRACT.md`
- `src/agnostic/interfaces/AGENT.md`
- `src/agnostic/interfaces/CONTEXT.md`

---

### `infrastructure`

Path:

`src/agnostic/infrastructure/`

Responsibility:

Implementar adaptadores concretos para recursos externos.

Owns:

- clientes externos;
- storage concreto;
- fontes CSV/Parquet/SQLite;
- exportação concreta;
- provedores concretos de IA;
- Redis;
- filesystem.

Does not own:

- comportamento analítico;
- métricas;
- heurísticas;
- ranking;
- regras de domínio;
- contratos de interface pública;
- decisões de navegação.

Important subpackages:

- `infrastructure/ai/`
- `infrastructure/db/`
- `infrastructure/export/`
- `infrastructure/storage/`

Planned local docs:

- `src/agnostic/infrastructure/CONTRACT_SUMMARY.md`
- `src/agnostic/infrastructure/CONTRACT.md`
- `src/agnostic/infrastructure/AGENT.md`
- `src/agnostic/infrastructure/CONTEXT.md`

---

### `core`

Path:

`src/agnostic/core/`

Status:

`TRANSITIONAL`

Responsibility:

Conter utilidades transversais ainda não atribuídas definitivamente a um módulo específico.

Current contents:

- `core/analysis_common.py`
- `core/errors.py`
- `core/internal_cuts.py`

Rules:

- `core` não deve crescer por conveniência.
- Novas responsabilidades não devem ser adicionadas a `core` sem decisão explícita.
- Itens em `core` exigem revisão futura para possível migração.
- `core` não deve ser usado para contornar fronteiras de módulo.

Pending decisions:

- `src/agnostic/core/internal_cuts.py` is `NEEDS_ARCHITECTURE_DECISION`.
- `src/agnostic/core/analysis_common.py` is `NEEDS_ARCHITECTURE_DECISION`.
- `src/agnostic/core/errors.py` is `NEEDS_ARCHITECTURE_DECISION`.

Planned local docs:

- `src/agnostic/core/CONTRACT_SUMMARY.md`
- `src/agnostic/core/CONTRACT.md`
- `src/agnostic/core/AGENT.md`
- `src/agnostic/core/CONTEXT.md`

---

## Current Global Documentation

Active global documentation:

- `docs/DOCUMENTATION_INDEX.md`
- `docs/PROJECT_CONSTITUTION.md`
- `docs/AGENT_GLOBAL_RULES.md`
- `docs/ORCHESTRATOR_PROTOCOL.md`
- `docs/CONTEXT_MANAGER_PROTOCOL.md`
- `docs/GLOBAL_INVARIANTS_SUMMARY.md`
- `docs/MODULE_REGISTRY.md`

Planned global documentation:

- `docs/IO_REGISTRY.md`
- `docs/IO_REGISTRY.json`

---

## Contract Policy

A module entry in this registry does not define complete I/O contracts.

Formal inter-module I/O must be defined in:

- `docs/IO_REGISTRY.json`

Human-readable explanation of the I/O registry must be defined in:

- `docs/IO_REGISTRY.md`

Module-specific contracts must be defined in:

- `src/agnostic/<module>/CONTRACT.md`

---

## Change Policy

A change to module ownership requires review when it affects:

- public inputs;
- public outputs;
- schemas;
- ports;
- exported symbols;
- inter-module imports;
- observable behavior;
- ownership of responsibility.

If a module boundary is ambiguous, mark it as:

`NEEDS_ARCHITECTURE_DECISION`

Do not resolve ambiguity implicitly.

---

## Success Criteria

This registry is correct when:

- every active module has explicit responsibility;
- no module claims responsibility owned by another module;
- transitional files are marked clearly;
- empty runtime directories are not treated as active modules;
- future documentation targets are listed;
- I/O contracts are delegated to `IO_REGISTRY.json`;
- pending architectural decisions remain explicit.
