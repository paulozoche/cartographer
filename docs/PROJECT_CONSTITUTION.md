# Project Constitution

## Status

`ACTIVE`

## Level

`0 — PROJECT CONSTITUTION`

## Objective

Definir as regras soberanas do projeto.

Este documento está acima de todos os agentes, módulos, contratos, prompts e decisões locais.

Nenhum agente pode violar estas regras sem decisão arquitetural explícita.

---

## Scope

Esta constituição define:

- invariantes analíticas;
- limites entre módulos;
- restrições de IA;
- regras sobre ranking;
- regras sobre persistência;
- regras sobre interface;
- regras sobre infraestrutura;
- princípios de evolução do sistema.

---

## Precedence

Em caso de conflito, siga esta ordem:

1. `docs/PROJECT_CONSTITUTION.md`
2. `docs/IO_REGISTRY.json`
3. `docs/ORCHESTRATOR_PROTOCOL.md`
4. `docs/CONTEXT_MANAGER_PROTOCOL.md`
5. `src/agnostic/<module>/CONTRACT.md`
6. `src/agnostic/<module>/AGENT.md`
7. `src/agnostic/<module>/CONTEXT.md`
8. tarefa atual

A tarefa atual pode restringir mais.

A tarefa atual não pode liberar algo proibido por nível superior.

---

## Constitutional Rules

### 1. Deterministic Core

O core analítico é determinístico.

A análise estrutural deve ser produzida por código determinístico, não por IA.

IA não pode substituir:

- métrica;
- heurística;
- cálculo de `signal`;
- ranking;
- análise inicial;
- classificação estrutural;
- saída estrutural canônica.

---

### 2. Dataset-Agnostic Analysis

O sistema é agnóstico ao domínio dos dados.

Um dataset concreto pode revelar bug, mas não define regra geral.

É permitido usar dataset concreto para:

- reproduzir falha;
- criar teste de regressão;
- validar comportamento;
- observar caso limite.

É proibido usar dataset concreto para:

- criar regra sem justificativa estrutural;
- ajustar threshold sem decisão explícita;
- alterar heurística;
- alterar ranking;
- alterar semântica analítica;
- introduzir interpretação semântica do domínio dos dados.

---

### 3. Structural Precedence

A estrutura precede interpretação.

O sistema analisa forma, distribuição, padrões, frequência, cardinalidade, consistência e sinais estruturais.

O sistema não presume intenção de negócio, significado semântico ou objetivo externo do usuário.

---

### 4. Signal-Based Ranking

Ranking estrutural deriva de `signal` ou de contrato explicitamente definido.

Nenhum módulo pode alterar ranking por conveniência visual, preferência textual, IA, persistência ou adaptação de interface.

Mudança no cálculo ou uso de ranking é mudança contratual.

---

### 5. AI Is Post-Core

IA é etapa pós-core.

IA pode:

- explicar resultado estrutural já calculado;
- resumir;
- responder com base em saída estrutural;
- gerar linguagem auxiliar.

IA não pode:

- definir o primeiro resultado estrutural;
- alterar `signal`;
- alterar ranking;
- substituir heurística;
- substituir métrica;
- definir contrato canônico;
- modificar estado analítico de origem.

---

### 6. Persistence Is Not Source Of Truth

Persistência não é fonte de verdade analítica.

Persistência, exportação, cache e snapshots podem existir como suporte operacional.

Eles podem servir para:

- performance;
- debug;
- auditoria;
- reprodução;
- compartilhamento controlado;
- exportação.

Eles não podem definir comportamento analítico.

---

### 7. Interfaces Do Not Analyze

Interfaces expõem, validam e renderizam contratos externos.

Interfaces não podem:

- calcular métrica;
- aplicar heurística;
- recalcular `signal`;
- definir ranking;
- substituir análise;
- acessar implementação interna de domínio sem contrato público.

---

### 8. Infrastructure Does Not Define Behavior

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

### 9. Module Responsibility Isolation

Cada módulo possui responsabilidade própria.

Módulos podem se comunicar por contratos públicos explícitos.

Módulos não podem depender de implementação interna de outros módulos.

Comunicação entre módulos não implica mistura de responsabilidades.

---

### 10. Public Contracts Are Binding

Entradas e saídas públicas são contratos.

São contratos públicos:

- DTO;
- schema;
- dataclass pública;
- Protocol;
- porta;
- função exportada;
- erro público;
- campo de resposta;
- formato de ID;
- envelope;
- estado compartilhável;
- chave de cache observável;
- semântica de validação;
- import público entre módulos.

Mudança em contrato público exige revisão contratual.

---

### 11. Compute-First Principle

O sistema deve ser capaz de reconstruir resultado a partir das entradas e contratos necessários.

Estado salvo não substitui recomputação.

Compartilhamento deve apontar para estado reproduzível, não para resultado analítico persistido como fonte primária.

---

### 12. Explicit Boundaries

Fronteiras devem ser explícitas.

Se dois módulos se comunicam, a comunicação deve estar registrada em contrato público ou no registro de I/O.

Implementação interna não é contrato.

---

## Forbidden Changes Without Architecture Decision

É proibido fazer sem decisão explícita:

- mover responsabilidade entre módulos;
- alterar ranking;
- alterar significado de `signal`;
- mudar schema público;
- mudar contrato de compartilhamento;
- transformar persistência em fonte de verdade;
- tornar IA etapa pré-core;
- permitir interface calcular análise;
- permitir infrastructure definir regra analítica;
- introduzir dependência circular entre módulos;
- usar dataset específico para regra geral.

---

## Current Transitional Notes

O projeto está em fase de consolidação modular.

Itens marcados ou reconhecidos como pendentes não devem ser movidos automaticamente.

Itens conhecidos:

- `src/agnostic/application/ports/tabular_source.py`
- `src/agnostic/core/internal_cuts.py`
- `src/agnostic/core/analysis_common.py`
- `src/agnostic/core/errors.py`

Esses itens exigem decisão arquitetural antes de migração definitiva.

---

## Success Criteria

O projeto respeita esta constituição quando:

- domínio continua determinístico;
- IA continua pós-core;
- ranking segue contrato estrutural;
- interfaces não calculam análise;
- infrastructure não define comportamento analítico;
- persistência não vira fonte de verdade;
- módulos se comunicam por contratos públicos;
- mudanças contratuais são explícitas;
- agentes param diante de conflito de responsabilidade.