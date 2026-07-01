# Presentation Contract Summary

## Status

`ACTIVE`

## Module

`presentation`

Path:

`src/agnostic/presentation/`

## Purpose

Transformar resultados estruturais em texto humano, resumo ou Markdown.

## Owns

- summaries;
- Markdown;
- explicação textual pós-core;
- adaptação de linguagem baseada em contratos estruturais.

## Does Not Own

- análise estrutural;
- métricas;
- heurísticas;
- cálculo de `signal`;
- ranking estrutural;
- persistência;
- API;
- UI como camada externa completa;
- decisão de IA como posse primária.

## Public Surface Summary

Símbolos públicos exportados por `agnostic.presentation.markdown`:

| Símbolo | Uso |
|---------|-----|
| `render_knowledge_map` | Mapa indentado para humanos (comando `mapa`, CLI, sidebar) |
| `render_knowledge_graph_context` | Contexto textual do grafo para Curadora/IA |
| `build_knowledge_map_context` | Monta `dict` de contexto a partir da sessão |
| `render_followup_options_message` | Lista numerada de opções pós-resultado |
| `render_canonical_analysis_markdown` | Markdown de análise canônica |

Helpers internos (não contrato): `_append_knowledge_lines`, `_node_as_dict` em `render_knowledge_graph.py`.

`NEEDS_DOCUMENTATION_DECISION`

- distinção final entre transformação textual pública e helper interno de formatação;
- política de versionamento dos formatos Markdown observáveis (`## Mapa do Conhecimento`, `## Grafo de Conhecimento`).

## Main Producers

- `src/agnostic/presentation/summaries/`
- `src/agnostic/presentation/markdown/`

## Main Consumers

Consumidores atuais:

- `orchestrator.py` — mapa, contexto do grafo, follow-up options, summaries
- `web.py` — comando `mapa` via `render_knowledge_map`

Consumidores previstos:

- `interfaces` (quando `src/agnostic/interfaces/api/` substituir `web.py`)

Consumidores devem usar contratos públicos do módulo, não detalhes internos de formatação.

## Allowed Dependencies

- `domain`, para consumir resultados estruturais por contrato público (ex.: `KnowledgeGraph` como tipo de entrada);
- `application/planning`, para ordenação e filtragem de requisitos na renderização do mapa (`requirement_schema`, `requirement_priority`, `focus_state`);
- dependências internas do próprio módulo `presentation`;
- outras superfícies públicas explicitamente formalizadas necessárias à composição textual.

## Forbidden Dependencies

O módulo `presentation` não pode depender de:

- cálculo analítico próprio;
- métricas próprias;
- heurísticas próprias;
- cálculo próprio de `signal`;
- alteração própria de ranking;
- persistência como fonte de verdade;
- implementação interna de outros módulos sem contrato público explícito.

Também não deve alterar a semântica analítica do conteúdo que apresenta.

## Contract Notes

- `presentation` é pós-core.
- Rendering textual e Markdown devem explicar ou resumir resultado estrutural já produzido.
- Mudança em formato textual público observável ou em semântica pública da saída apresentada é mudança contratual.
- O módulo não deve redefinir significado analítico por conveniência narrativa.

## Pending Decisions

`NEEDS_DOCUMENTATION_DECISION`

- lista final de transformações públicas do módulo;
- formatos públicos finais de summaries e Markdown;
- política para eventual distinção entre saída textual estável e saída apenas auxiliar.

`NEEDS_ARCHITECTURE_DECISION`

- qualquer fronteira em que `presentation` hoje absorva responsabilidade que pertença a `interfaces` ou `application`;
- política final para o que é contrato textual estável versus utilitário interno de apresentação.

## Escalation Triggers

Escalar quando houver:

- mudança em summary público;
- mudança em output Markdown público;
- alteração de semântica analítica durante a apresentação;
- tentativa de mover lógica analítica para `presentation`;
- dúvida sobre posse de responsabilidade entre `presentation`, `application` e `interfaces`.
