# Camadas de Métricas

## Status

`REFERENCE`

## Objective

Reduzir entropia e evitar aumento prematuro de complexidade no núcleo observacional.

## Regra

O sistema cresce por camadas:

1. primeiro o necessário
2. depois o refinamento
3. depois os sinais mais complexos

## Camada 1

Métricas básicas, necessárias e estruturalmente mais seguras. Prioridade alta e implementada sobre a base cega atual.

## Camada 2

Métricas de aprofundamento observacional que aumentam a granularidade sem pertencer ao núcleo mínimo inicial.

## Camada 3

Métricas de aprofundamento avançado. Entram depois da estabilização das camadas anteriores.

## Organização Futura

Além das camadas principais, o sistema poderá ter uma caixa paralela de ferramentas especializadas.

## Critério de Evolução

Uma métrica só sobe de prioridade se tiver valor observacional claro, não violar o paradigma agnóstico, tiver contrato compreensível e não duplicar outra métrica.

## Princípio de Coesão

* duas métricas não fazem a mesma coisa
* uma métrica não faz duas coisas
