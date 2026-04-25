# Decisions

## Status
`ACTIVE`

## Objective
Registrar decisões que afetam o sistema e definir precedência.

## Scope
Inclui:
- Decisões de produto
- Decisões arquiteturais
- Escolhas de tecnologia
- Restrições operacionais

## Precedence
Em caso de conflito:

1. INVARIANTS.md
2. ARCHITECTURE.md
3. DECISIONS.md

## Decisions

### Product
- Sistema é uma API de análise estrutural agnóstica
- Core é determinístico e separado de IA
- Exploração é progressiva por estado, não por camadas fixas (ver FLOW.md)
- `legacy/` não faz parte do runtime (ver LEGACY.md)

### Architecture
- Linguagem: Python
- API: FastAPI
- Estrutura por camadas: domain, application, infrastructure, interfaces
- Métricas e heurísticas são separadas por responsabilidade

### Execution
- Modelo compute-first (ver ARCHITECTURE.md — Invariant 4)
- Sem persistência de resultados
- Estado em memória não é fonte de verdade

### Cache
- Cache em memória (LRU)
- Responsabilidade da application

### Data & Security
- Minimizar retenção de dados
- Preservar estrutura sem interpretação na entrada

### Exploration
- Evidências podem ser coletadas em uma coleção
- Coleção organiza referências ao estado, não dados
- Organização não altera o comportamento analítico

### Sharing
- Compartilhamento é baseado em estado reproduzível
- Qualquer estado compartilhado deve ser reconstruível
- Não depende de persistência de resultados analíticos

## Principle
Decisões devem permitir evolução, distribuição e compartilhamento sem quebrar o modelo determinístico e compute-first.
