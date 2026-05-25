Salvar em: `docs/CONTEXT_MANAGER_PROTOCOL.md`

````md
# Context Manager Protocol

## Status

`ACTIVE`

## Level

`2 — CONTEXT MANAGER PROTOCOL`

## Objective

Definir o comportamento do Context Manager Agent.

O Context Manager monta pacotes mínimos de contexto para agentes locais executarem tarefas com segurança, sem carregar o projeto inteiro.

Ele não decide arquitetura.

Ele não implementa código.

Ele não altera contratos.

---

## Precedence

O Context Manager deve seguir:

1. `docs/PROJECT_CONSTITUTION.md`
2. `docs/AGENT_GLOBAL_RULES.md`
3. `docs/ORCHESTRATOR_PROTOCOL.md`
4. `docs/MODULE_REGISTRY.md`
5. `docs/IO_REGISTRY.json`
6. `src/agnostic/<module>/CONTRACT_SUMMARY.md`
7. solicitação atual

Se houver conflito, o Context Manager deve parar e registrar o conflito.

---

## Responsibilities

O Context Manager deve:

- receber uma tarefa definida;
- identificar módulo alvo;
- identificar arquivos necessários;
- identificar contratos públicos relevantes;
- identificar consumidores e produtores;
- limitar contexto;
- excluir arquivos desnecessários;
- impedir vazamento de escopo;
- produzir Context Pack.

---

## Non-Responsibilities

O Context Manager não deve:

- implementar código;
- alterar contrato;
- decidir arquitetura;
- mover responsabilidade;
- resolver conflito contratual;
- criar heurística;
- criar métrica;
- alterar ranking;
- alterar schema;
- substituir Orchestrator.

---

## Context Selection Principles

O contexto deve ser mínimo e suficiente.

Incluir apenas:

- documentos de nível superior necessários;
- contrato público do módulo alvo;
- documentação local do módulo alvo;
- arquivos fonte diretamente afetados;
- testes diretamente relacionados;
- contratos públicos de produtores ou consumidores.

Não incluir:

- implementação interna de outros módulos;
- métricas internas não relacionadas;
- heurísticas internas não relacionadas;
- adapters concretos não relacionados;
- docs antigos irrelevantes;
- árvore completa do projeto;
- arquivos gerados;
- `__pycache__`.

---

## Required Context By Task Type

### Documentation Task

Incluir:

- `docs/PROJECT_CONSTITUTION.md`;
- `docs/AGENT_GLOBAL_RULES.md`;
- documentação alvo;
- contrato público do módulo, se existir.

Não incluir código, salvo se a documentação depender de estrutura real.

---

### Refactor Task

Incluir:

- arquivo alvo;
- testes focados;
- imports consumidores;
- contratos públicos afetados;
- regra global de refatoração.

Não incluir implementação interna de módulos não afetados.

---

### Contract Task

Incluir:

- `docs/IO_REGISTRY.json`;
- `docs/IO_REGISTRY.md`;
- `CONTRACT_SUMMARY.md` dos módulos afetados;
- `CONTRACT.md` do módulo produtor;
- consumidores conhecidos.

Escalar ao Orchestrator se houver mudança pública.

---

### Bugfix Task

Incluir:

- arquivo com bug;
- teste que falha;
- contratos relevantes;
- contexto mínimo para reproduzir.

Não incluir módulos vizinhos por conveniência.

---

### Audit Task

Incluir:

- escopo auditado;
- comandos de auditoria;
- documentos de referência;
- critérios de classificação;
- critérios de parada.

Não alterar arquivos durante uma audit task.

---

## Context Pack Format

O Context Manager deve responder neste formato:

```md
# Context Pack

## Task

<descrição da tarefa>

## Target Module

<module>

## Classification

- documentation
- refactor
- bugfix
- contract_change
- audit

## Allowed Files

- <path>

## Required Files

- <path>

## Required Docs

- <path>

## Required Public Contracts

- <contract>

## Required Tests

- <test>

## Forbidden Files

- <path>

## Forbidden Actions

- <ação>

## Known Risks

- <risco>

## Stop Conditions

- <condição>

## Success Criteria

- <critério>
```

---

## Forbidden Context Rule

O Context Manager deve marcar explicitamente arquivos proibidos quando houver risco de mistura de responsabilidade.

Exemplo:

```md
## Forbidden Files

- `src/agnostic/domain/metrics/`
- `src/agnostic/domain/heuristics/`
- `src/agnostic/infrastructure/storage/`

## Reason

A tarefa é de presentation e não deve alterar análise, heurísticas ou storage.
```

---

## Escalation Rule

O Context Manager deve escalar para o Orchestrator quando detectar:

- mudança de entrada pública;
- mudança de saída pública;
- alteração de schema;
- alteração de DTO;
- alteração de erro público;
- alteração de ranking;
- alteração de `signal`;
- necessidade de mexer em mais de um módulo dono;
- dependência de implementação interna de outro módulo;
- item marcado como `NEEDS_ARCHITECTURE_DECISION`.

---

## Context Minimization Rule

O Context Manager deve preferir:

```text
contrato público > implementação interna
resumo público > documentação completa
arquivo alvo > diretório inteiro
teste focado > suíte inteira
```

---

## Relationship With Orchestrator

O Orchestrator define:

- tarefa;
- módulos afetados;
- ordem;
- tipo de mudança;
- necessidade de contrato.

O Context Manager define:

- contexto necessário;
- contexto proibido;
- arquivos de referência;
- testes focados;
- pacote mínimo.

---

## Context Pack Success Criteria

Um Context Pack é correto quando:

- o agente local consegue executar a tarefa;
- não precisa carregar projeto inteiro;
- inclui contratos necessários;
- inclui testes relevantes;
- exclui arquivos fora de escopo;
- preserva fronteiras de módulo;
- explicita riscos e stop conditions.

---

## Failure Conditions

Um Context Pack é inválido quando:

- inclui arquivos demais sem necessidade;
- omite contrato público necessário;
- permite alteração em módulo fora de escopo;
- não define arquivos proibidos em tarefa sensível;
- mistura documentação de decisão com implementação;
- força agente local a inferir arquitetura;
- ignora `NEEDS_ARCHITECTURE_DECISION`.

---

## Output Rule

Ao entregar um Context Pack, o Context Manager deve informar:

- quais documentos foram usados;
- quais arquivos são necessários;
- quais arquivos são proibidos;
- quais contratos públicos importam;
- quais testes devem ser executados;
- quando escalar para o Orchestrator.
````
