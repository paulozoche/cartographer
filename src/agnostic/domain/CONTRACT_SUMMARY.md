# Domain Contract Summary

## Status

`ACTIVE`

## Module

`domain`

Path:

`src/agnostic/domain/`

## Purpose

Produzir análise estrutural determinística sobre unidades tabulares.

Este módulo é responsável pelo núcleo analítico estrutural do projeto.

## Owns

- análise tabular determinística;
- modelos analíticos públicos do domínio;
- padronização analítica;
- métricas estruturais;
- heurísticas estruturais;
- cálculo de `signal`;
- ranking estrutural;
- explicações estruturais;
- sugestões estruturais.

## Does Not Own

- IA;
- API;
- interface;
- renderização textual ou Markdown;
- storage;
- persistência como fonte de verdade;
- compartilhamento;
- navegação de interface;
- adapters concretos de infraestrutura.

## Public Surface Summary

Superfície pública esperada, sujeita a formalização detalhada em `CONTRACT.md`:

- entrada analítica tabular aceita pelo fluxo determinístico;
- modelos estruturais públicos usados para representar unidades, colunas e resultados;
- funções públicas de análise estrutural;
- tipos públicos necessários para consumidores legítimos do resultado estrutural.

Os símbolos públicos exatos ainda dependem de formalização detalhada.

`NEEDS_DOCUMENTATION_DECISION`

- lista normativa final de símbolos públicos do módulo;
- distinção formal entre superfície pública estável e helpers internos hoje importáveis.

## Main Producers

- `src/agnostic/domain/analysis/`
- `src/agnostic/domain/metrics/`
- `src/agnostic/domain/heuristics/`
- `src/agnostic/domain/models/`

## Main Consumers

Consumidores atuais ou previstos pela documentação ativa:

- `application`
- `presentation`
- `interfaces`

Consumidores concretos devem usar contratos públicos do módulo, não implementação interna.

Uso de tipos de `domain` por `infrastructure` como suporte de adaptação pode existir, mas não amplia automaticamente a superfície pública do módulo além do que for formalizado.

## Allowed Dependencies

- `core`, apenas quando necessário e compatível com a documentação ativa;
- tipos de entrada formalmente definidos para o fluxo analítico, se documentados como fronteira pública;
- dependências internas do próprio módulo `domain`.

Observação:

`src/agnostic/application/ports/tabular_source.py` aparece como fronteira usada pelo domínio, mas seu papel documental permanece `NEEDS_ARCHITECTURE_DECISION`.

## Forbidden Dependencies

O módulo `domain` não pode depender de:

- `infrastructure`;
- `interfaces`;
- `ai`;
- `presentation`;
- `sharing`;
- implementação interna de outros módulos sem contrato público explícito.

Também não pode depender de:

- providers concretos;
- storage concreto;
- regras de UI;
- renderização final;
- lógica pós-core de IA.

## Contract Notes

- Mudança em métrica, heurística, cálculo de `signal`, ranking estrutural ou semântica observável da análise é mudança contratual.
- O módulo `domain` deve permanecer determinístico.
- Consumidores entre módulos devem ser orientados por contratos públicos, não por imports incidentais.
- Detalhes internos de métricas e heurísticas não fazem parte deste resumo.

## Pending Decisions

`NEEDS_DOCUMENTATION_DECISION`

- símbolos públicos normativos do módulo;
- formato final da entrada analítica pública do módulo;
- lista final de tipos públicos estáveis expostos por `domain/models`.

`NEEDS_ARCHITECTURE_DECISION`

- papel definitivo de `src/agnostic/application/ports/tabular_source.py` como fronteira consumida pelo domínio;
- eventual ajuste de fronteira se algum consumidor atual depender de implementação interna em vez de contrato público.

## Escalation Triggers

Escalar quando houver:

- mudança em `signal`;
- mudança em ranking estrutural;
- mudança em métrica pública observável;
- mudança em heurística com efeito observável na análise;
- mudança em tipos públicos consumidos por outros módulos;
- necessidade de tornar público um símbolo hoje apenas interno;
- dependência nova de `infrastructure`, `interfaces` ou `ai`;
- dúvida sobre a fronteira entre entrada pública do domínio e porta de `application`.
