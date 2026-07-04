# Cartographer — Cache Redis

Camada de cache distribuída para resultados de análise do **Core API**, com TTL de 8 horas, renovação automática no acesso, métricas e worker de manutenção.

## Arquivos

| Arquivo | Descrição |
|:---|:---|
| `cache/cache_manager.py` | Classe `CacheManager` — GET, SET, DELETE, `get_or_process`, métricas |
| `cache/cache_worker.py` | Worker que roda a cada hora mantendo integridade do cache |
| `main.py` | Exemplo prático integrado com `CoreService` + launcher do worker |
| `requirements.txt` | Dependências (inclui `redis`) |

## Funcionalidades

| Funcionalidade | Status |
|:---|:---|
| Cache com TTL de 8h | ✅ |
| Renovação de TTL no acesso | ✅ |
| Metadados por análise (Hash) | ✅ |
| Índice de prioridade (Sorted Set) | ✅ |
| Contadores globais (hits, misses, ativas) | ✅ |
| Métricas básicas (hit rate, memória) | ✅ |
| Top análises mais acessadas | ✅ |
| Worker de manutenção | ✅ |
| Tratamento de erros (timeout, fallback) | ✅ |
| Telemetria avançada (logs, retrabalho por ID) | 🔜 Preparado |
| Relatório de retrabalho | 🔜 Preparado |

## Pré-requisitos

```bash
pip install -e .
pip install -r requirements.txt
```

Redis opcional — sem `AGNOSTIC_REDIS_URL`, o cache usa fallback em memória (útil para dev).

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|:---|:---|:---|
| `AGNOSTIC_REDIS_URL` | *(vazio)* | URL Redis (`redis://localhost:6379/0`) |
| `AGNOSTIC_CACHE_TTL_SECONDS` | `28800` | TTL do cache (8 horas) |
| `AGNOSTIC_CACHE_TIMEOUT_SECONDS` | `2.0` | Timeout de conexão/operação Redis |
| `AGNOSTIC_CACHE_WORKER_INTERVAL_SECONDS` | `3600` | Intervalo do worker (1 hora) |

## Uso rápido

### Demo integrada com Core

```bash
python main.py demo /caminho/para/dataset.sqlite
```

O demo:
1. Cria uma sessão em memória via `CoreService`
2. Executa `analyze_unit` duas vezes (segunda deve ser cache hit)
3. Chama `recall` pela `cache_key`
4. Imprime métricas e health check

### Worker de manutenção

```bash
# Um ciclo
python main.py worker --once

# Loop contínuo (a cada hora)
python main.py worker

# Ou diretamente
python -m cache.cache_worker --once
```

O worker:
- Remove metadados órfãos (Hash sem payload)
- Limpa entradas do Sorted Set sem dados correspondentes
- Reconcilia contador `active`
- Expira entradas do fallback em memória

## Integração com CoreService

Contrato de chaves preservado (compatível com Windmill e `/recall`):

- `unit:{unit_name}`
- `vertical:{unit_name}:{column}:{depth}`
- `unit_full:{unit_name}`
- `vertical_full:{unit_name}:{column}`

Exemplo mínimo:

```python
from cache.cache_manager import CacheManager

cache = CacheManager.from_env()

def analyze_unit(session_id: str, unit_name: str, core_service) -> dict:
    cache_key = f"unit:{unit_name}"
    return cache.get_or_process(
        session_id,
        cache_key,
        lambda: core_service.analyze_unit(unit_name),
    )
```

Veja `main.py` (`CachedCoreService`) para wrapper completo.

## Métricas

```python
metrics = cache.get_metrics(session_id="...")
print(metrics.hit_rate, metrics.active, metrics.top_analyses)
print(cache.health_check())
```

Campos de telemetria já reservados nos metadados Redis (`rework_count`, `last_rework_at`, `trace_id`) para evolução futura.

## Subir Redis local

```bash
docker run -d --name cartographer-redis -p 6379:6379 redis:7-alpine
export AGNOSTIC_REDIS_URL=redis://localhost:6379/0
```

## Próximos passos

1. Integrar `CachedCoreService` em `core_api/app.py` (substituir `_cache` in-process)
2. Ativar telemetria de retrabalho preenchendo `rework_count` / `trace_id`
3. Adicionar endpoint `GET /sessions/{id}/cache/metrics` no Core API
4. Pré-aquecimento assíncrono após `POST /sessions`

## Teste manual

```bash
# Terminal 1 — Redis
docker run --rm -p 6379:6379 redis:7-alpine

# Terminal 2 — demo
export AGNOSTIC_REDIS_URL=redis://localhost:6379/0
python main.py demo /caminho/para/dataset.sqlite --verbose

# Terminal 3 — worker
python main.py worker --once --verbose
```
