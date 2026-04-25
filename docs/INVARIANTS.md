# Invariants

## Status

`ACTIVE`

## Objective

Definir invariantes do sistema que não podem ser violados.

## Scope

Aplica-se a todas as camadas.

## Precedence

Tem prioridade sobre:

* DECISIONS.md
* FLOW.md
* INTERFACES.md

## Invariants

* core é agnóstico ao domínio
* sistema não conhece o objetivo do usuário
* sistema não interpreta significado semântico
* sistema opera sobre estrutura e guia exploração por relevância estrutural
* core é determinístico
* resultado é reprodutível a partir da entrada
* evidência estrutural precede qualquer narrativa
* métricas medem; heurísticas sinalizam; nenhuma interpreta semanticamente
* pipeline oficial do core: métricas → heurísticas → signal → explanation → suggested_actions
* ranking é unificado e derivado exclusivamente de `signal` (ordem decrescente)
* pipeline permanece simples (ver ARCHITECTURE.md)
* nenhuma camada introduz persistência de resultado
* estado em memória não é fonte de verdade
* o dataset em execução pode revelar problema, mas não define regra analítica
* exemplos concretos revelam falhas; não calibram comportamento geral
* UI pode refletir estado atual; não pode induzir tuning analítico
* novas heurísticas devem nascer de propriedades estruturais, não de casos particulares

## Flow Constraints

* progressão posicional obrigatória até coluna (ver FLOW.md)
* após coluna: progressão orientada por estado estrutural

## AI Constraint

* IA é opcional e externa ao core (ver ARCHITECTURE.md)
* agentes que alteram comportamento analítico devem bloquear instruções baseadas em conteúdo concreto do dataset em execução

## Data Constraint

* entrada preserva estrutura sem interpretação (ver INPUT_LAYER.md)
* dados não são armazenados como resultado analítico

## Síntese

Qualquer mudança deve preservar o determinismo, o agnosticismo e a primazia da evidência estrutural.
