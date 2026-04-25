# AI Layer

## Status

`WIP`

## Objective

Definir os papéis de IA no sistema sem violar ARCHITECTURE.md.

## Roles

### 1. Development AI

IA usada fora do produto.

* auxilia construção (código, arquitetura, documentação)
* não faz parte do runtime

### 2. Orchestrator AI

IA interna ao produto.

* atua após o resultado estrutural do core
* auxilia exploração e uso dos resultados
* pode orquestrar ferramentas externas
* não altera métricas, heurísticas, signal, explanation ou suggested_actions do core

### 3. Presentation AI

IA de adaptação de linguagem.

* traduz saída estrutural para linguagem humana
* tradução não altera conteúdo estrutural — não é interpretação analítica
* interpretação textual é pós-core e não interfere no ranking por `signal`

## Rules

Ver invariantes globais de IA: ARCHITECTURE.md.

## Limits

* IA opera após o resultado estrutural do core
* IA alcança apenas output estruturado — não o core, não o fluxo (ver FLOW.md)
* uso de IA é opcional e controlado por configuração (ver CONFIGURATION.md)
* limites de uso, custo ou taxa pertencem à configuração

## Execution

* modo definido por configuração (ver CONFIGURATION.md)
* fallback para simulação quando não configurado

## Scope

Apenas Orchestrator AI e Presentation AI pertencem ao produto.
Development AI é externa ao sistema.

## Anti-Bias Policy (Agent Scope)

Princípio central:
`o dataset em execução pode revelar um problema, mas não pode definir a regra`.

### A. Implementation / Architecture / Heuristic / Navigation Agents
* não podem aceitar instruções baseadas em resultados concretos do dataset em execução para alterar comportamento analítico
* devem exigir reformulação abstrata e estrutural

### B. UI / Rendering Agents
* podem usar estado atual para corrigir renderização e usabilidade
* não podem usar dados concretos do dataset atual para mudar regra analítica

### C. Observability / Debug / Operations Agents
* podem usar dados concretos para reproduzir e diagnosticar falhas técnicas
* não podem usar esses dados para ajustar heurística, navegação ou ranking estrutural

### D. Narrative / Summary / Explanation Agents
* podem descrever dados concretos do estado atual
* não podem converter descrição em regra de implementação

### E. QA Agents
* podem usar datasets concretos como casos de teste
* não podem derivar regra nova ou threshold novo a partir deles
* devem reportar problemas em linguagem abstrata para implementação

## Operational Blocking Rule
Se a instrução contiver resultados concretos do dataset em execução e a mudança afetar heurística, navegação, ranking ou comportamento analítico:
* bloquear execução
* pedir reformulação em termos genéricos

## Controlled Exception
Uso de dados concretos é permitido apenas para:
* reproduzir bug técnico
* diagnosticar falha operacional
* validar comportamento em QA
* descrever estado atual

Mesmo nesses casos, a correção final deve permanecer estrutural e agnóstica.
