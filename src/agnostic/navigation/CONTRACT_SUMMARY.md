# Navigation Contract Summary

## Status

`ACTIVE`

## Module

`navigation`

Path:

`src/agnostic/navigation/`

## Purpose

Representar recortes, slices e transições de navegação estrutural.

## Owns

- slices;
- políticas de transição;
- validação de transições de recorte;
- contratos de navegação estrutural.

## Does Not Own

- análise estrutural;
- métricas;
- heurísticas;
- cálculo de `signal`;
- ranking estrutural;
- IA;
- persistência;
- rendering final;
- assinatura de compartilhamento.

## Public Surface Summary

Superfície pública esperada, sujeita a formalização detalhada em `CONTRACT.md`:

- tipos públicos de slices;
- políticas públicas de transição;
- validações públicas de navegação estrutural;
- artefatos necessários para navegação observável entre recortes.

Os símbolos públicos exatos ainda dependem de formalização detalhada.

`NEEDS_DOCUMENTATION_DECISION`

- lista normativa final de símbolos públicos do módulo;
- formato público estável de slices;
- superfície pública final das validações de transição.

## Main Producers

- `src/agnostic/navigation/slices/`
- `src/agnostic/navigation/transitions/`

## Main Consumers

Consumidores atuais ou previstos pela documentação ativa:

- `application`
- `interfaces`

Consumidores devem usar contratos públicos do módulo, não detalhes internos de implementação.

## Allowed Dependencies

- dependências internas do próprio módulo `navigation`;
- contratos públicos necessários para compor navegação estrutural, quando explicitamente formalizados.

## Forbidden Dependencies

O módulo `navigation` não pode depender de:

- lógica analítica própria;
- cálculo próprio de métricas;
- cálculo próprio de heurísticas;
- cálculo próprio de `signal`;
- alteração própria de ranking;
- UI como posse primária;
- implementação interna de outros módulos sem contrato público explícito.

## Contract Notes

- Navegação estrutural não substitui análise estrutural.
- Mudança em slice público, política pública de transição ou semântica observável de validação é mudança contratual.
- Validação de transição não transfere posse de regras analíticas para `navigation`.

## Pending Decisions

`NEEDS_DOCUMENTATION_DECISION`

- formato público final dos slices;
- lista final de políticas públicas do módulo;
- superfície normativa das validações públicas de transição.

`NEEDS_ARCHITECTURE_DECISION`

- qualquer fronteira em que regras de navegação estejam hoje acopladas a comportamento que pertença a outro módulo;
- política final para o quanto da navegação observável pertence a `navigation` versus `interfaces`.

## Escalation Triggers

Escalar quando houver:

- mudança em slices públicos;
- mudança em política pública de transição;
- mudança em validação pública observável;
- tentativa de mover lógica analítica para `navigation`;
- dúvida sobre posse de responsabilidade entre `navigation`, `application` e `interfaces`.
