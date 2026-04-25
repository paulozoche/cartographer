# Application Layer

## Status

`ACTIVE`

## Objective

Orquestrar a execução do fluxo analítico entre core e interfaces.

## Responsibilities

* Coordenar a execução do core a partir de entradas estruturadas
* Expor casos de uso para consumo interno e externo
* Preparar o próximo escopo analítico conforme `FLOW.md`
* Gerenciar cache em memória (LRU) com base em fingerprint
* Entregar unidades já ordenadas por `signal` no nível atual de navegação

## Inputs

* Entradas estruturadas compatíveis com o contrato do core
* Requisições de casos de uso

## Outputs

* Resultado de análise estruturado
* Decisões de orquestração (escopo seguinte)
* Erros de validação ou de contrato
* Ranking aplicado por `signal` (ordem decrescente), independente do tipo de unidade

## Limits

* Não alcança lógica analítica do core
* Não alcança fluxo de navegação (ver `FLOW.md`)
* Não alcança contratos de interface
* Não possui conhecimento de protocolo (ex: HTTP)
* Não realiza lógica de apresentação
* Não realiza interpretação de domínio de negócio
