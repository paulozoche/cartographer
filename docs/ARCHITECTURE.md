# Architecture

## Status
`ACTIVE`

## Overview
Motor de análise agnóstico (não orientado a domínio nem objetivo), focado em descoberta estrutural.
Core determinístico, execução compute-first, sem dependência de persistência.

## Principles
- Core puro e determinístico
- Zero interpretação nas etapas iniciais
- Execução sob demanda
- IA opcional, nunca no core, sempre após o resultado estrutural
- `legacy/` fora do runtime
- Sistema não conhece o objetivo do usuário
- Sistema não interpreta significado semântico
- Sistema opera sobre estrutura e prioriza relevância estrutural
- Sistema guia exploração por evidência estrutural

## Layers
| Layer | Responsibility |
|---|---|
| `domain` | Core analítico: métricas, heurísticas, signal, explanation, suggested_actions e ranking estrutural |
| `application` | Casos de uso, orquestração, cache em memória |
| `infrastructure` | Adaptadores externos (IA, Redis opcional) |
| `interfaces` | FastAPI, rotas, schemas HTTP, validação de entrada |

## Official Pipeline
Pipeline canônico do core:

`métricas → heurísticas → signal → explanation → suggested_actions`

- `métricas`: medições estruturais reproduzíveis
- `heurísticas`: sinais derivados das métricas
- `signal`: escore agregado determinístico para ranking
- `explanation`: síntese textual baseada apenas em heurísticas ativadas
- `suggested_actions`: sugestões de exploração baseadas apenas em heurísticas ativadas

## Analyzable Unit Contract
Qualquer unidade analisável (atual e futura) deve obedecer ao contrato:

```json
{
  "type": "...",
  "name": "...",
  "signal": 0.0,
  "explanation": "...",
  "suggested_actions": []
}
```

Aplicável hoje a `table` e `column`; extensível para unidades futuras.

## Unified Ranking
- Ranking é unificado e independente do tipo de unidade.
- Regra única: ordenação por `signal` em ordem decrescente.
- Aplicação: no nível atual de navegação (tabela, coluna e futuras unidades).
- Interface consome listas já ordenadas.

## Invariants
Violação de qualquer invariante quebra o modelo.

1. Core é determinístico e reproduzível a partir da entrada
2. Resultado estrutural sempre precede IA, narrativa ou interpretação
3. Dados nunca são alterados pelo sistema — análises são projeções
4. Sistema não depende de persistência (compute-first)
5. IA nunca substitui métricas, heurísticas ou lógica determinística
6. Ranking global é derivado exclusivamente de `signal`

## AI Rule
IA é invariante de posição: nunca é o primeiro passo, nunca substitui o core.
IA é opcional e atua como orquestradora ou mediadora após o resultado estrutural.
IA interpreta/apresenta resultados; não interfere no pipeline do core.

## Layer Progression
```
origem → tabela → coluna → [decisões de aprofundamento] → valor/célula → caractere
```
- Até `coluna`: progressão posicional obrigatória dentro de um ramo
- Após `coluna`: orientada por estado estrutural, evidências e transições permitidas pelo nó
- Progressão descreve um ramo; múltiplos ramos coexistem na árvore de análise

## Layer Contract
- A camada atual mostra a si mesma, seus sinais e decisões
- A camada atual oferece o próximo escopo como possibilidade
- Core calcula automaticamente; interface revela e organiza
- Decisão de navegação é do usuário

## Infrastructure
Existe apenas como suporte. Não define comportamento analítico, não armazena resultado, não altera determinismo.

Componentes possíveis: Redis (cache auxiliar ou revogação), provedores de IA, adaptadores de entrada.

## Tools Concept
`tools` são análises paralelas opcionais sob demanda.
- Não definem estado de análise
- Não alteram cálculo do core
- Não impactam ranking global por `signal`

## Ecosystem Principles
- Segurança por minimização de dados
- Simplicidade estrutural antes de sofisticação
- Separação clara de responsabilidades
- Previsibilidade e consistência entre documentação, código e comportamento
