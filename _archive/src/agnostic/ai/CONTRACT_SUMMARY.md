# AI Contract Summary

## Status

`ACTIVE`

## Module

`ai`

Path:

`src/agnostic/ai/`

## Purpose

Definir e executar integração de IA pós-core.

## Owns

- contrato de orquestração de IA;
- resposta de IA;
- consulta de IA pós-core;
- superfícies públicas necessárias para acionar IA sobre resultado estrutural já produzido.

## Does Not Own

- análise inicial;
- métricas;
- heurísticas;
- cálculo de `signal`;
- ranking estrutural;
- persistência;
- UI;
- contrato de compartilhamento;
- provider concreto de IA como posse primária.

## Public Surface Summary

Superfície pública esperada, sujeita a formalização detalhada em `CONTRACT.md`:

- porta pública de orquestração de IA;
- tipos públicos de resposta de IA;
- função pública de consulta pós-core, quando formalizada;
- artefatos necessários para integrar IA sem alterar a origem analítica.

Os símbolos públicos exatos ainda dependem de formalização detalhada.

`NEEDS_DOCUMENTATION_DECISION`

- lista normativa final de símbolos públicos do módulo;
- formato público estável da resposta de IA;
- distinção final entre contrato de orquestração e utilitário interno de chamada.

## Main Producers

- `src/agnostic/ai/ports/`
- `src/agnostic/ai/consult_ai.py`

## Main Consumers

Consumidores atuais ou previstos pela documentação ativa:

- `application`
- `interfaces`, quando usar contratos públicos de IA legitimamente expostos

Consumidores devem usar contratos públicos do módulo, não providers concretos diretamente.

## Allowed Dependencies

- `domain` ou `application`, apenas por contratos públicos necessários para consumir resultado estrutural já produzido;
- dependências internas do próprio módulo `ai`;
- portas e tipos públicos necessários à integração pós-core.

## Forbidden Dependencies

O módulo `ai` não pode depender de:

- definição do primeiro resultado estrutural;
- cálculo próprio de métricas;
- cálculo próprio de heurísticas;
- cálculo próprio de `signal`;
- alteração própria de ranking;
- provider concreto como substituto de contrato público;
- implementação interna de outros módulos sem contrato público explícito.

## Contract Notes

- IA é pós-core.
- O módulo `ai` pode explicar, resumir ou responder com base em resultado estrutural já calculado.
- Mudança em contrato público de orquestração, tipo de resposta pública ou semântica observável da consulta pós-core é mudança contratual.
- Provider concreto não pertence a este módulo como posse primária quando a implementação está em `infrastructure/ai`.

## Pending Decisions

`NEEDS_DOCUMENTATION_DECISION`

- formato público final da resposta de IA;
- lista final de superfícies públicas do módulo;
- política final para distinguir resposta estável de artefatos auxiliares.

`NEEDS_ARCHITECTURE_DECISION`

- fronteira entre `ai` e `infrastructure/ai`;
- política final para o que é contrato público do módulo versus detalhe de provider concreto.

## Escalation Triggers

Escalar quando houver:

- mudança em resposta pública de IA;
- mudança em semântica pública de consulta pós-core;
- tentativa de mover análise estrutural para `ai`;
- dependência nova de provider concreto sem mediação contratual;
- dúvida sobre fronteira entre `ai`, `application` e `infrastructure/ai`.
