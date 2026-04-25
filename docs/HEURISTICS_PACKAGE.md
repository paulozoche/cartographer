# Pacote de Heurísticas

## Estado

`REFERENCE`

## Escopo Inicial

O pacote começa com heurísticas de coluna. Ainda não inclui heurísticas de tabela ou de relação.

## Entrada

Cada heurística recebe métricas da coluna.

## Saída Padronizada

Cada heurística deve retornar `name`, `triggered`, `score`, `evidence` e `metadata`.

## Regras

- `score` inicial entre `0.0` e `1.0`
- `triggered` é decidido pela própria heurística
- `evidence` deve ser estruturada
- `metadata` guarda detalhes auxiliares

## Organização Prevista

Estrutura mínima esperada: `base.py`, `registry.py`, `apply.py` e uma heurística por arquivo.

## Validação

Validado em testes unitários: contrato de saída, aplicação do registry e integração com inputs cegos.

## Princípio

As heurísticas combinam métricas e produzem sinais estruturais de nível mais alto. Não realizam interpretação semântica.
