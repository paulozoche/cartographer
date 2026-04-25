# Configuration

## Status
`ACTIVE`

## Objective
Definir a configuração operacional do sistema sem introduzir comportamento analítico.

## Scope
Configuração cobre:
- Provedores externos (ex: IA)
- Parâmetros de integração
- Servidor HTTP
- Limites operacionais

## Types

### 1. Startup Configuration
- Definida no boot do sistema
- Carregada via `agnostic.load_app_config()`
- Não muda durante a execução

### 2. Runtime Configuration
- Ajustável por requisição
- Não altera comportamento estrutural do core

## AI
- Seleção de provedor é feita por configuração
- Modos definidos nesta camada (ver AI.md)
- Fallback para simulação quando não configurado

## Limits
- Não alcança comportamento do core (ver ARCHITECTURE.md)
- Não alcança fluxo de navegação (ver FLOW.md)
- Não alcança contratos de interface
- Não introduz persistência de resultado

## Execution Model
Sistema é compute-first (ver ARCHITECTURE.md). Não há persistência de resultados.

## Cache
Cache em memória é responsabilidade da application (ver APPLICATION.md).

## Revocation
Backend definido por configuração. Contrato não muda entre implementações.

## Principle
Configuração controla ambiente e operação, não comportamento analítico.
