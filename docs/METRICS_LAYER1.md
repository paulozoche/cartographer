# Camada 1 de Métricas

## Status

`REFERENCE`

## Objective

Sustentar o núcleo observacional com métricas básicas, necessárias e estruturalmente mais seguras.

## Escopo

Inclui `cardinality`, `null_ratio`, `unique_ratio`, `frequency`, `mode_frequency`, `average_length`, `length_range`, `length_variance` e `empty_string_ratio`.

## Regras Aplicadas

- uma métrica não faz duas coisas
- duas métricas não fazem a mesma coisa
- `None` continua distinto de `""`
- a política de amostragem não fica escondida dentro da definição da métrica

## Validação

Validada em testes unitários: métricas individuais, aplicação conjunta e integração com inputs cegos.
