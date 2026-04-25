# Input Layer

## Status

`REFERENCE`

## Objective

Definir o contrato de entrada estrutural para o core.

## Principles

* zero interpretação
* preservação da estrutura observável
* desacoplamento da fonte

## Contract

Entrada deve fornecer:

`DataSource → TabularUnit → UnitMetadata + UnitStructure + RowStream`

## Rules

* não inferir significado de negócio
* não classificar entidades
* não enriquecer dados
* não alterar valores
* manter ordem posicional

## Objects

* `DataSource` → origem dos dados
* `TabularUnit` → unidade tabular
* `UnitMetadata` → metadados da unidade
* `UnitStructure` → colunas e atributos brutos
* `RowStream` → fluxo de linhas

## Boundary

* core não depende de formato específico
* formatos de entrada são decisões (ver DECISIONS.md)
* adaptadores pertencem à infraestrutura (ver ARCHITECTURE.md)

## Síntese

Entrada entrega estrutura; análise começa depois.
