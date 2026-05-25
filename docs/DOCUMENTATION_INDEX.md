# Documentation Index

## Status

`ACTIVE`

## Objective

Definir quais documentos fazem parte da documentação ativa do projeto e quais fontes não têm autoridade normativa.

---

## Active Documentation

A documentação ativa do projeto está dentro de `docs/` e segue a hierarquia abaixo.

### Level 0 — Project Constitution

- `docs/PROJECT_CONSTITUTION.md`

Define regras soberanas do projeto.

Nenhum agente, módulo, contrato ou tarefa pode violar este documento.

---

### Level 1 — Global Agent Rules

- `docs/AGENT_GLOBAL_RULES.md`

Define regras operacionais comuns a todos os agentes.

---

### Level 2 — Coordination Protocols

- `docs/ORCHESTRATOR_PROTOCOL.md`
- `docs/CONTEXT_MANAGER_PROTOCOL.md`

Define como tarefas são orquestradas e como pacotes mínimos de contexto são montados.

---

## Planned Active Documentation

Os documentos abaixo fazem parte da nova arquitetura documental, mas podem ainda estar em criação.

### Global Registry Documents

- `docs/MODULE_REGISTRY.md`
- `docs/IO_REGISTRY.md`
- `docs/IO_REGISTRY.json`
- `docs/GLOBAL_INVARIANTS_SUMMARY.md`

### Module Documents

Cada módulo poderá ter:

- `src/agnostic/<module>/AGENT.md`
- `src/agnostic/<module>/CONTRACT.md`
- `src/agnostic/<module>/CONTEXT.md`
- `src/agnostic/<module>/CONTRACT_SUMMARY.md`

---

## Legacy Documentation

A documentação antiga foi removida do projeto.

Ela pode existir fora do repositório como referência histórica, mas não possui autoridade normativa sobre o projeto atual.

Documentação antiga não deve ser usada como regra ativa por agentes.

Se algum conteúdo antigo for necessário, ele deve ser explicitamente fornecido na tarefa e tratado como material histórico, não como fonte de precedência.

---

## Precedence

A precedência documental ativa é:

1. `docs/PROJECT_CONSTITUTION.md`
2. `docs/IO_REGISTRY.json`
3. `docs/AGENT_GLOBAL_RULES.md`
4. `docs/ORCHESTRATOR_PROTOCOL.md`
5. `docs/CONTEXT_MANAGER_PROTOCOL.md`
6. `docs/MODULE_REGISTRY.md`
7. `src/agnostic/<module>/CONTRACT.md`
8. `src/agnostic/<module>/AGENT.md`
9. `src/agnostic/<module>/CONTEXT.md`
10. tarefa atual

A tarefa atual pode restringir mais.

A tarefa atual não pode liberar algo proibido por documentos de nível superior.

---

## Agent Rule

Agentes devem usar apenas documentos ativos do projeto como fonte normativa.

Agentes não devem inferir regra ativa a partir de documentação antiga, histórico de conversa, código legado, nomes antigos de arquivos ou estrutura anterior do projeto.

Se faltar documentação ativa para uma decisão, o agente deve marcar o ponto como:

`NEEDS_DOCUMENTATION_DECISION`

ou, quando envolver responsabilidade arquitetural:

`NEEDS_ARCHITECTURE_DECISION`

---

## Success Criteria

A documentação está corretamente organizada quando:

- documentos ativos estão listados neste índice;
- documentação antiga não é usada como autoridade;
- contratos formais ficam em JSON quando precisam ser validáveis;
- instruções humanas ficam em Markdown;
- documentos de módulo não duplicam regras globais;
- agentes conseguem identificar precedência sem ambiguidade.