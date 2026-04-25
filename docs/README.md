# Cartographer

## Status
`ACTIVE`

## Objective
Definir o mapa do sistema e a função de cada documento canônico.

## System
API de análise estrutural agnóstica com core determinístico e execução compute-first.
Ver ARCHITECTURE.md.

Pipeline canônico: `métricas → heurísticas → signal → explanation → suggested_actions`.
Ranking unificado por `signal` (ordem decrescente) em qualquer nível analisável.

## Quick Index
- [Core](#core)
- [Support](#support)
- [Reference](#reference)
- [Rules](#rules)

## Documents

### Core
- ARCHITECTURE.md → invariantes, princípios e camadas
- FLOW.md → progressão analítica e árvore de análise
- APPLICATION.md → orquestração
- INTERFACES.md → contratos de exposição externa
- INVARIANTS.md → fonte única dos invariantes do sistema

### Support
- AI.md → uso de IA no sistema
- CONFIGURATION.md → configuração operacional
- DECISIONS.md → decisões e precedência

### Reference
- INPUT_LAYER.md → entrada de dados
- METRICS_LAYERS.md → organização de métricas
- HEURISTICS_PACKAGE.md → heurísticas
- METHOD.md → evolução do projeto
- LEGACY.md → snapshot histórico

## Rules
- Um documento, uma função
- Sem duplicação de regras
- Referências substituem repetição
- Conflito deve ser resolvido antes de consolidação
- O dataset em execução valida comportamento, não define regra do sistema
