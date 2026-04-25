# Método de Evolução

## Status

`REFERENCE`

## Objective

Evitar erro estrutural silencioso.

## Regra

O projeto evolui em ciclos curtos:

1. implementar
2. testar
3. registrar falhas
4. refinar
5. repetir

## Granularidade

- Os ciclos devem ser pequenos o bastante para validar, mas grandes o bastante para produzir avanço observável.
- Tarefas microscópicas demais reduzem a agilidade e aumentam o custo de coordenação.
- Cada ciclo deve entregar uma mudança que possa ser percebida, testada ou consolidada.
- Se uma tarefa não gera progresso observável, ela deve ser agregada a outra tarefa maior ou adiada.

## Princípio

Sempre que houver validação empírica possível, ela deve vir antes do refinamento.
O contrato é materializado, o comportamento é observado, os problemas reais são registrados e só então o método é ajustado.

## Uso

Vale especialmente para:

- camada de entrada
- métricas
- heurísticas
- orquestração por IA
- exposição de resultados
