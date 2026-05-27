# Cartographer

## Status

`ACTIVE`

## Objetivo

Documentar os componentes específicos do fluxo conversacional Cartographer: orquestração por IA, servidor web e interface estática.

---

## Visão Geral

O Cartographer adiciona uma camada conversacional sobre a análise tabular do projeto.

Fluxo de alto nível:

1. O usuário envia um arquivo pela interface web.
2. `web.py` cria uma `OrchestratorSession`.
3. `orchestrator.py` detecta a fonte, lista unidades e produz o contexto estrutural inicial.
4. A IA de Interface apresenta o panorama inicial ao usuário.
5. Em cada turno, a IA Orquestradora decide uma ação estruturada.
6. A sessão executa a ação, atualiza o grafo de conhecimento e a IA de Interface transforma o resultado em resposta em linguagem natural.

---

## `orchestrator.py`

Responsabilidade:

Centralizar a sessão conversacional, o contrato entre as três IAs, a execução de ações e o grafo de conhecimento.

### Arquitetura das 3 IAs

- IA Interface: conversa com o usuário em português claro, interpreta resultados já produzidos e nunca emite JSON.
- IA Orquestradora: decide a próxima ação e responde somente com JSON válido no contrato permitido.
- IA Curadora: filtra contexto estrutural e também ajuda a conectar novos achados ao grafo.

Implementação principal:

- `DeepSeekClient`: cliente HTTP para o provedor.
- `OrchestratorSession`: estado da sessão, histórico, cache por unidade, catálogo dinâmico e grafo.

### Sessão e estado

`OrchestratorSession` mantém:

- `source_path`, `source_type` e `source`
- `units` detectadas na origem
- `history` da conversa
- `analysis_by_unit` para cache de análises sob demanda
- `explored_paths` com unidades já aprofundadas
- `knowledge_graph` com nós e arestas
- `_curator_cache` para contexto já filtrado
- `_session_query_catalog` e `_candidate_queries` para consultas geradas durante a sessão

### Leis da Orquestradora

A IA Orquestradora recebe um `system_prompt` com leis de prioridade explícita:

- LEI 1: responder apenas com um dos JSONs permitidos.
- LEI 2: usar `query` apenas quando houver cobertura exata no catálogo.
- LEI 3: sem cobertura exata, usar `request_new_query`.
- LEI 4: erro operacional nunca vira `done`.
- LEI 5: confirmações curtas como `sim` devem executar a sugestão pendente no histórico.
- LEI 6: não reexecutar a mesma query quando já existe resultado válido no turno.

### Contrato de ação

A orquestradora só pode emitir uma destas ações:

- `{"action":"analyze_unit","unit_name":"nome_da_tabela"}`
- `{"action":"query","query_id":"id_do_catalogo"}`
- `{"action":"template","template_id":"...","params":{...}}`
- `{"action":"request_new_query","description":"...","suggested_sql":"SELECT ..."}`
- `{"action":"schema","table":"nome_da_tabela"}`
- `{"action":"tables"}`
- `{"action":"done","conclusion":"texto"}`

Validação:

- `build_orchestrator_prompt(...)` monta o payload JSON enviado à IA Orquestradora.
- `parse_orchestrator_json(...)` valida a resposta.
- `execute_action(...)` executa a ação escolhida.

### Catálogo e templates

Catálogo embutido:

- `QUERY_CATALOG` contém consultas prontas para casos recorrentes.

Templates analíticos:

- `group_feature_signature`
- `group_feature_signature_by_entity`
- `exclusive_feature_values_by_group`

O ciclo de template é:

1. A orquestradora escolhe `template` com parâmetros concretos.
2. `build_sql_from_template(...)` materializa o SQL.
3. O SQL é validado.
4. A sessão executa preview e registra o resultado no grafo.

### Grafo de conhecimento

Estruturas:

- `KnowledgeNode`
- `KnowledgeEdge`
- `KnowledgeGraph`

Uso:

- `update_knowledge_graph(...)` cria nós a partir de `analyze_unit`, `query` e `template`.
- `_curate_knowledge_edge(...)` tenta relacionar o novo achado a nós existentes.
- `render_knowledge_map()` produz um resumo em Markdown com:
  `### Achados`
  `### Caminhos não explorados`

### Bootstrap e ciclo de turno

Bootstrap:

- `bootstrap()` monta o contexto estrutural completo e pede à IA Interface a abertura da sessão.

Turno:

1. `orchestrate(...)` escolhe a ação.
2. `execute_action(...)` produz o resultado bruto.
3. `interface_reply(...)` transforma o resultado em texto para o usuário.
4. O histórico é comprimido e preservado para turnos futuros.

---

## `web.py`

Responsabilidade:

Expor o Cartographer via FastAPI, manter sessões em memória e conectar upload/chat ao `OrchestratorSession`.

### Componentes principais

- `app = FastAPI(title="Cartographer Web")`
- `SESSIONS`: dicionário global de sessões ativas
- `SessionState`: `session_id`, `file_path`, `orchestrator`, `structural_context`
- `ChatRequest` e `ChatResponse`: modelos Pydantic

### Endpoints

- `GET /`
  Retorna `static/index.html`.

- `POST /upload`
  Recebe `UploadFile`, grava em arquivo temporário em `/tmp`, cria a sessão e devolve a mensagem inicial com `session_id`.

- `POST /chat`
  Recebe `session_id` e `message`, executa um turno do orquestrador e devolve a resposta textual.

### Sessões

As sessões ficam apenas em memória do processo:

- são indexadas por `session_id`
- guardam o objeto `OrchestratorSession`
- preservam histórico e contexto estrutural entre mensagens

Não há persistência de sessão fora do processo web.

### Upload e execução

Upload:

- aceita o arquivo enviado pela UI
- mantém o sufixo do nome para ajudar na detecção da fonte
- usa `NamedTemporaryFile(delete=False, dir="/tmp")`

Execução de turno:

- `_run_turn(...)` trata comandos locais `ajuda`, `mapa` e `sair`
- usa `MAX_ATTEMPTS_PER_TURN` para tentativas de decisão/execução
- diferencia respostas de `done`, `tables`, `schema` e respostas analíticas gerais

### Timeouts e erros

- `REQUEST_TIMEOUT_SECONDS = 60.0`
- `UPLOAD_TIMEOUT_SECONDS = 300.0`

Erros viram `HTTPException` com códigos adequados:

- `400` para upload inválido
- `404` para sessão ausente
- `504` para timeout no chat
- `500` para falhas internas durante o turno

---

## `static/index.html`

Responsabilidade:

Fornecer a interface única do Cartographer no navegador.

### Papel da interface

A página combina:

- upload do arquivo
- chat conversacional
- renderização de Markdown das respostas
- leitura do mapa de conhecimento para preencher a barra lateral

### Estrutura visual

Áreas principais:

- topbar com marca Cartographer
- sidebar com mapa da sessão
- painel principal com histórico do chat
- composer para envio de mensagens
- statusbar com estado do servidor, sessão, tabelas e nós do grafo

### Comportamento cliente

Estado principal em JavaScript:

- `sessionId`
- `lastUserMessage`
- `mapState = { explored, pending, nodeCount }`

Interações:

- `uploadFile()` envia `FormData` para `/upload`
- `sendMessage()` envia JSON para `/chat`
- `appendMessage()` renderiza mensagens no histórico
- `parseKnowledgeMap()` extrai listas de exploradas e pendentes do Markdown retornado por `mapa`
- `updateSidebar()` e `updateStatusBar()` refletem o estado atual da sessão

### Contratos esperados do backend

Upload:

- resposta JSON com `response` e `session_id`

Chat:

- resposta JSON com `response` e `session_id`

Mapa:

- texto em Markdown contendo `## Mapa do Conhecimento`
- seção `### Achados`
- seção `### Caminhos não explorados`

### Observações

- O chat fica desabilitado até existir `sessionId`.
- As respostas do bot são renderizadas com `marked`.
- O comando `mapa` é tratado como resposta especial para sincronizar a sidebar com o grafo atual.
