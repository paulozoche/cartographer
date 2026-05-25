# Core Contract Summary

## Status

`TRANSITIONAL`

## Module

`core`

Path:

`src/agnostic/core/`

## Purpose

Conter utilidades transversais ainda não atribuídas definitivamente a um módulo específico.

Este módulo está em transição e não deve crescer por conveniência.

## Owns

- utilidades transversais atualmente ainda não realocadas;
- helpers comuns hoje usados por múltiplos pontos do sistema, quando ainda não houver módulo dono definido;
- erros compartilhados, apenas enquanto sua fronteira definitiva não estiver resolvida.

## Does Not Own

- responsabilidade analítica estável como módulo de negócio próprio;
- API;
- UI;
- IA;
- storage;
- sharing;
- navegação como posse primária;
- presentation como posse primária.

## Public Surface Summary

Superfície pública atual estritamente conservadora:

- artefatos transitórios hoje expostos por `src/agnostic/core/__init__.py`;
- tipos ou erros compartilhados ainda não realocados;
- helpers transversais ainda dependentes de decisão arquitetural.

Nada em `core` deve ser promovido automaticamente a contrato estável só por estar importável.

`NEEDS_DOCUMENTATION_DECISION`

- lista normativa mínima de símbolos públicos transitórios;
- política para documentar superfícies transitórias sem legitimá-las como permanentes.

## Main Producers

- `src/agnostic/core/analysis_common.py`
- `src/agnostic/core/internal_cuts.py`
- `src/agnostic/core/errors.py`

## Main Consumers

Consumidores atuais observáveis na árvore:

- `application`
- `interfaces`
- `domain`

Esse consumo não estabiliza por si só a fronteira de `core`.

## Allowed Dependencies

- dependências internas do próprio módulo `core`;
- dependências estritamente necessárias para manter compatibilidade transitória até decisão explícita.

## Forbidden Dependencies

O módulo `core` não deve:

- crescer por conveniência;
- absorver nova responsabilidade estável sem decisão explícita;
- substituir contrato público de módulo dono;
- redefinir comportamento analítico, de interface ou de infraestrutura como posse própria.

## Contract Notes

- `core` é transitório.
- Mudança em qualquer superfície pública hoje exposta por `core` exige cuidado contratual reforçado, porque pode afetar múltiplos consumidores.
- A existência de imports para `core` não resolve quem deve ser o dono real da responsabilidade.

## Pending Decisions

`NEEDS_DOCUMENTATION_DECISION`

- lista final de superfícies transitórias documentáveis de `core`;
- política para distinguir compatibilidade temporária de contrato estável.

`NEEDS_ARCHITECTURE_DECISION`

- destino de `src/agnostic/core/internal_cuts.py`;
- destino de `src/agnostic/core/analysis_common.py`;
- destino de `src/agnostic/core/errors.py`;
- política final para o que permanece em `core`, se algo permanecer.

## Escalation Triggers

Escalar quando houver:

- tentativa de adicionar nova responsabilidade a `core`;
- tentativa de estabilizar símbolo de `core` sem decisão explícita;
- mudança em helper ou erro transitório consumido por múltiplos módulos;
- dúvida sobre o módulo dono real de qualquer artefato em `core`.
