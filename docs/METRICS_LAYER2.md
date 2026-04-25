# Camada 2 de Métricas

## Status

`REFERENCE`

## Objective

Adicionar aprofundamento observacional sem ampliar o núcleo mínimo inicial.

## Escopo

Inclui `numeric_ratio`, `alpha_ratio`, `spaces_ratio` e `uppercase_ratio`.

## Papel no Sistema

A Camada 2 não substitui a Camada 1, não pertence ao scan mínimo inicial e serve para aprofundamento observacional.

## Validação

Validada em testes unitários: métricas individuais, aplicação conjunta e integração com inputs cegos.

## Auditoria Curta

### Pontos Fortes

- adiciona granularidade sem alterar o núcleo mínimo
- preserva o paradigma observacional
- roda sobre múltiplos formatos no mesmo contrato

### Fragilidades

- aumenta a dependência de decisões sobre representação textual
- exige mais cuidado interpretativo na orquestração futura
- deve ser tratada como aprofundamento, não como scan padrão
