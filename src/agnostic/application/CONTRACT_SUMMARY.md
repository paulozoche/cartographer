# Application Contract Summary

## Status

`ACTIVE`

## Module

`application`

Path:

`src/agnostic/application/`

## Purpose

Orquestrar casos de uso e coordenar módulos especializados sem assumir suas responsabilidades internas.

Este módulo organiza fluxos de execução e compõe capacidades públicas de outros módulos quando necessário.

## Owns

- casos de uso de application;
- coordenação entre `domain`, `presentation`, `infrastructure`, `sharing`, `navigation`, `interfaces` e `ai`;
- cache operacional de application;
- porta de resultado canônico atualmente mantida em `application/ports/canonical_result_store.py`;
- regras operacionais de composição de fluxo no nível de application.

## Does Not Own

- cálculo analítico;
- métricas;
- heurísticas;
- cálculo de `signal`;
- ranking estrutural;
- rendering visual final;
- contratos concretos de infraestrutura;
- storage concreto;
- provider concreto de IA;
- assinatura como posse primária de `sharing`.

## Public Surface Summary

Superfície pública esperada, sujeita a formalização detalhada em `CONTRACT.md`:

- casos de uso públicos de orchestration;
- portas de application legitimamente expostas;
- resultados e envelopes operacionais necessários para coordenação de fluxo;
- possível fachada pública em `application/__init__.py`, quando explicitamente formalizada.

Reexports em `application/__init__.py`, se existirem, devem ser tratados como fachada pública potencial, não como posse automática de responsabilidade sobre os símbolos reexportados.

Os símbolos públicos exatos ainda dependem de formalização detalhada.

`NEEDS_DOCUMENTATION_DECISION`

- lista normativa final de símbolos públicos do módulo;
- distinção formal entre casos de uso públicos, portas públicas e reexports de conveniência;
- semântica pública estável da fachada em `application/__init__.py`, se ela for mantida como superfície oficial.

## Main Producers

- `src/agnostic/application/use_cases/`
- `src/agnostic/application/ports/`
- `src/agnostic/application/cache/`

Diretórios sem código runtime ativo não contam como produtores do módulo:

- `src/agnostic/application/policies/`
- `src/agnostic/application/services/`

## Main Consumers

Consumidores atuais ou previstos pela documentação ativa:

- `interfaces`
- outros consumidores externos autorizados via superfície pública de application

O módulo `application` também atua como coordenador de produtores especializados, incluindo:

- `domain`
- `presentation`
- `sharing`
- `navigation`
- `ai`
- `infrastructure`

Consumidores e integrações devem usar contratos públicos, não implementação interna incidental.

## Allowed Dependencies

- `domain`
- `presentation`
- `sharing`
- `navigation`
- `ai`
- `infrastructure`, apenas via adapters e capacidades concretas necessárias à execução
- dependências internas do próprio módulo `application`

Cache, persistência e exportação podem ser coordenados por `application` como suporte operacional.

Eles não se tornam fonte de verdade analítica por isso.

## Forbidden Dependencies

O módulo `application` não pode depender de:

- lógica que redefina responsabilidade analítica de `domain`;
- cálculo próprio de métricas;
- cálculo próprio de heurísticas;
- cálculo próprio de `signal`;
- definição própria de ranking estrutural;
- adaptação de interface como posse primária de `interfaces`;
- contrato de infraestrutura tratado como regra analítica.

Também não deve transformar:

- cache operacional em fonte de verdade;
- persistência ou exportação em fonte de verdade analítica;
- reexport de símbolo alheio em transferência automática de responsabilidade.

## Contract Notes

- `application` coordena fluxos; não substitui responsabilidades internas dos módulos especializados.
- Cache de application é suporte operacional, não fonte de verdade.
- Persistência e exportação coordenadas por `application` são suporte operacional, não fonte de verdade analítica.
- `src/agnostic/application/ports/canonical_result_store.py` é porta legítima de `application` por enquanto.
- Mudança em porta pública, caso de uso público, envelope operacional observável ou fachada pública estável é mudança contratual.

## Pending Decisions

`NEEDS_DOCUMENTATION_DECISION`

- lista final de casos de uso públicos do módulo;
- lista final de portas públicas do módulo;
- política normativa para a superfície pública de `application/__init__.py`;
- distinção final entre fachada pública estável e reexport apenas transitório.

`NEEDS_ARCHITECTURE_DECISION`

- papel definitivo de `src/agnostic/application/ports/tabular_source.py`;
- escopo estável de `application` como fachada pública para símbolos coordenados de outros módulos;
- qualquer fronteira em que `application` hoje reexporte símbolo de outro módulo sem contrato local ainda formalizado.

## Escalation Triggers

Escalar quando houver:

- criação ou remoção de porta pública de `application`;
- mudança em caso de uso público observável;
- mudança na semântica pública da fachada em `application/__init__.py`;
- necessidade de mover responsabilidade analítica para dentro de `application`;
- tentativa de tornar cache, persistência ou exportação fonte de verdade analítica;
- dúvida sobre posse de responsabilidade entre `application` e módulos especializados;
- mudança na fronteira de `src/agnostic/application/ports/tabular_source.py`.
