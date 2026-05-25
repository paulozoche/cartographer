# Global Invariants Summary

## Status

`ACTIVE`

## Level

`GLOBAL SUMMARY`

## Objective

Resumir os invariantes globais do projeto de forma curta e operacional.

Este documento não substitui `docs/PROJECT_CONSTITUTION.md`.

Em caso de conflito, prevalece `docs/PROJECT_CONSTITUTION.md`.

---

## Scope

Este documento resume apenas invariantes globais já definidos pela documentação ativa.

Ele não cria novos contratos públicos.

Ele não resolve decisões arquiteturais pendentes.

Ele não define regras operacionais detalhadas para agentes.

---

## Invariant 1 — Deterministic Core

O core analítico é determinístico.

A análise estrutural deve ser produzida por código determinístico.

IA não pode substituir:

- métricas;
- heurísticas;
- cálculo de `signal`;
- ranking;
- análise inicial;
- saída estrutural canônica.

---

## Invariant 2 — Dataset-Agnostic Analysis

O sistema é agnóstico ao domínio dos dados.

Datasets concretos podem ser usados para reproduzir falhas e validar comportamento.

Datasets concretos não podem definir regras gerais sem decisão explícita.

Proibido derivar de um dataset específico:

- novo threshold;
- nova heurística;
- alteração de ranking;
- alteração de semântica analítica;
- interpretação de negócio.

---

## Invariant 3 — Structural Precedence

A estrutura precede interpretação.

O sistema analisa:

- forma;
- distribuição;
- frequência;
- cardinalidade;
- consistência;
- padrões estruturais;
- sinais estruturais.

O sistema não presume significado de negócio, intenção do usuário ou semântica externa dos dados.

---

## Invariant 4 — Signal-Based Ranking

Ranking estrutural deriva de `signal` ou de contrato explicitamente definido.

Nenhum módulo pode alterar ranking por:

- preferência visual;
- convenience de API;
- texto de apresentação;
- IA;
- persistência;
- cache;
- adaptação de interface.

Mudança de ranking é mudança contratual.

---

## Invariant 5 — AI Is Post-Core

IA é etapa pós-core.

IA pode explicar, resumir ou responder com base em resultado estrutural já produzido.

IA não pode:

- definir o primeiro resultado estrutural;
- alterar `signal`;
- alterar ranking;
- substituir métrica;
- substituir heurística;
- modificar estado analítico de origem;
- definir contrato canônico.

---

## Invariant 6 — Persistence Is Not Source Of Truth

Persistência não é fonte de verdade analítica.

Persistência, exportação, cache e snapshots são suporte operacional.

Eles podem servir para:

- performance;
- debug;
- auditoria;
- reprodução;
- exportação;
- compartilhamento controlado.

Eles não podem definir comportamento analítico.

---

## Invariant 7 — Interfaces Do Not Analyze

Interfaces expõem, validam e renderizam contratos externos.

Interfaces não podem:

- calcular métrica;
- aplicar heurística;
- recalcular `signal`;
- definir ranking;
- substituir análise;
- depender de implementação interna sem contrato público.

---

## Invariant 8 — Infrastructure Does Not Define Behavior

Infrastructure conecta o sistema ao mundo externo.

Infrastructure pode implementar:

- storage;
- clientes externos;
- fontes de dados;
- provedores de IA;
- Redis;
- filesystem;
- exportação.

Infrastructure não pode definir:

- regra analítica;
- ranking;
- métrica;
- heurística;
- progressão de navegação;
- comportamento de domínio.

---

## Invariant 9 — Module Responsibility Isolation

Cada módulo possui responsabilidade própria.

Módulos podem se comunicar por contratos públicos explícitos.

Módulos não podem depender de implementação interna de outros módulos.

Comunicação entre módulos não implica mistura de responsabilidades.

---

## Invariant 10 — Public Contracts Are Binding

Entradas e saídas públicas são contratos.

São contratos públicos:

- DTOs;
- schemas;
- dataclasses públicas;
- Protocols;
- portas;
- funções exportadas;
- erros públicos;
- campos de resposta;
- formatos de ID;
- envelopes;
- estados compartilháveis;
- semântica de validação;
- imports públicos entre módulos.

Mudança em contrato público exige revisão contratual.

---

## Invariant 11 — Compute-First Principle

O sistema deve ser capaz de reconstruir resultado a partir das entradas e contratos necessários.

Estado salvo não substitui recomputação.

Compartilhamento deve apontar para estado reproduzível, não para resultado analítico persistido como fonte primária.

---

## Invariant 12 — Explicit Boundaries

Fronteiras devem ser explícitas.

Se dois módulos se comunicam, a comunicação deve estar registrada por contrato público ou no registro de I/O.

Implementação interna não é contrato.

---

## Known Pending Decisions

Os itens abaixo não devem ser resolvidos automaticamente por agentes:

- `src/agnostic/application/ports/tabular_source.py`
- `src/agnostic/core/internal_cuts.py`
- `src/agnostic/core/analysis_common.py`
- `src/agnostic/core/errors.py`

Cada item deve permanecer marcado como:

`NEEDS_ARCHITECTURE_DECISION`

até decisão explícita.

---

## Success Criteria

O projeto respeita os invariantes globais quando:

- o domínio continua determinístico;
- IA continua pós-core;
- ranking segue contrato estrutural;
- interfaces não calculam análise;
- infrastructure não define comportamento analítico;
- persistência não vira fonte de verdade;
- módulos se comunicam por contratos públicos;
- mudanças contratuais são explícitas;
- decisões pendentes não são resolvidas implicitamente.