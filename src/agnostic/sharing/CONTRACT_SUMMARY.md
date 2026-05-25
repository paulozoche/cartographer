# Sharing Contract Summary

## Status

`ACTIVE`

## Module

`sharing`

Path:

`src/agnostic/sharing/`

## Purpose

Gerar, validar, assinar, verificar e revogar estados compartilháveis reproduzíveis.

## Owns

- share state;
- share envelope;
- políticas de share id;
- políticas de chave de assinatura;
- assinatura e verificação de share link;
- porta de revogação;
- contratos de compartilhamento.

## Does Not Own

- análise estrutural;
- métricas;
- heurísticas;
- cálculo de `signal`;
- ranking estrutural;
- UI;
- renderização final;
- persistência analítica como fonte de verdade;
- navegação estrutural interna.

## Public Surface Summary

Superfície pública esperada, sujeita a formalização detalhada em `CONTRACT.md`:

- estado compartilhável reproduzível;
- envelope de compartilhamento;
- políticas públicas de identificação e verificação;
- porta pública de revogação;
- operações públicas de assinatura e verificação.

Os símbolos públicos exatos ainda dependem de formalização detalhada.

`NEEDS_DOCUMENTATION_DECISION`

- lista normativa final de símbolos públicos do módulo;
- formato público estável de share state e share envelope;
- distinção final entre políticas públicas e helpers internos de assinatura.

## Main Producers

- `src/agnostic/sharing/state/`
- `src/agnostic/sharing/envelope/`
- `src/agnostic/sharing/policies/`
- `src/agnostic/sharing/ports/`
- `src/agnostic/sharing/services/`

## Main Consumers

Consumidores atuais ou previstos pela documentação ativa:

- `application`
- `interfaces`

Consumidores devem usar contratos públicos do módulo, não detalhes internos de implementação.

## Allowed Dependencies

- dependências internas do próprio módulo `sharing`;
- `domain`, `application` ou outros módulos apenas quando houver contrato público explícito legitimando a composição necessária;
- portas públicas necessárias para revogação e verificação.

## Forbidden Dependencies

O módulo `sharing` não pode depender de:

- lógica analítica própria;
- cálculo próprio de métricas;
- cálculo próprio de heurísticas;
- cálculo próprio de `signal`;
- alteração própria de ranking;
- UI ou rendering como posse primária;
- implementação interna de outros módulos sem contrato público explícito.

Também não deve transformar persistência, cache ou revogação em fonte de verdade analítica.

## Contract Notes

- Compartilhamento deve apontar para estado reproduzível, não para resultado analítico persistido como fonte primária.
- Mudança em envelope público, estado compartilhável, formato de ID, política pública de assinatura ou semântica de verificação é mudança contratual.
- A presença de porta de revogação não transfere posse de storage concreto para `sharing`.

## Pending Decisions

`NEEDS_DOCUMENTATION_DECISION`

- formato público final do share state;
- formato público final do share envelope;
- lista final de políticas públicas estáveis do módulo.

`NEEDS_ARCHITECTURE_DECISION`

- qualquer fronteira em que `sharing` hoje dependa de implementação concreta sem contrato público explicitamente formalizado;
- política final para superfícies reexportadas por outros módulos como fachada de compartilhamento.

## Escalation Triggers

Escalar quando houver:

- mudança em share state público;
- mudança em envelope público;
- mudança em formato de share id;
- mudança em semântica de assinatura, verificação ou revogação observável;
- tentativa de tornar compartilhamento fonte de verdade analítica;
- dúvida sobre posse de responsabilidade entre `sharing`, `application` e `interfaces`.
