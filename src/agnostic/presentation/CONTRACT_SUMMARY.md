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

Superfície pública esperada, sujeita a formalização detalhada em `CONTRACT.md`:

- funções públicas de sumarização textual;
- funções públicas de rendering Markdown;
- tipos públicos necessários para representar saídas textuais observáveis.

Os símbolos públicos exatos ainda dependem de formalização detalhada.

`NEEDS_DOCUMENTATION_DECISION`

- lista normativa final de símbolos públicos do módulo;
- distinção final entre transformação textual pública e helper interno de formatação;
- formatos públicos estáveis de saída textual e Markdown.

## Main Producers

- `src/agnostic/presentation/summaries/`
- `src/agnostic/presentation/markdown/`

## Main Consumers

Consumidores atuais ou previstos pela documentação ativa:

- `application`
- `interfaces`

Consumidores devem usar contratos públicos do módulo, não detalhes internos de formatação.

## Allowed Dependencies

- `domain`, para consumir resultados estruturais por contrato público;
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
