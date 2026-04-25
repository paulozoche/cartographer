# Interfaces Layer

## Status
`WIP`

## Objective
Definir contratos de exposição externa do sistema.

## Responsibilities
- Receber requisições externas
- Validar entrada e saída
- Traduzir contratos da application
- Expor rotas, schemas e autenticação

## Contracts
- Entrada validada antes da application
- Saída reflete o resultado estruturado
- Erros explícitos e previsíveis
- Interface recebe unidades já ranqueadas por `signal` no nível corrente

## Exposure
Interface expõe **estados** definidos pelo sistema, não camadas ou níveis.

- Estado atual da análise determina o que é exposto
- Interface não infere próximo passo
- Interface não define progressão (ver FLOW.md)

## Structure Mapping
- **Base** representa o ponto de entrada (origem)
- **Recorte promovido** reinicia como nova base — comportamento definido pelo core
- Tools não são estados de análise
- Coleção não é estado de análise
- Contrato de unidade analisável exposta:
  - `type`, `name`, `signal`, `explanation`, `suggested_actions`

## Limits
- Não alcança lógica analítica (ver ARCHITECTURE.md)
- Não alcança fluxo de navegação (ver FLOW.md)
- Não alcança orquestração (ver APPLICATION.md)
- Sem transformação semântica de resultado
- Sem persistência de resultado

## Integration
- Implementa protocolos (ex: HTTP)
- Injeta dependências externas

## Principle
Interface expõe estados; não decide, não interpreta, não define progressão.

## UI Surface Rules
Regras de superfície para manter fluxo direto e baixo ruído visual:

- modo foco não é exposto na UI
- painel de setup não é exposto como bloco de ferramentas
- seleção de origem fica em fluxo mínimo: `caminho/origem atual + botão "Procurar"`
- seleção de arquivo deve disparar envio direto (sem etapa extra de confirmação)

## Left Rail Rules
No painel esquerdo, cada função ocupa um único recipiente visual.

- `Histórico de orientação`: exibir apenas título + árvore
- não exibir subtítulo/linha auxiliar do histórico
- não usar quadro interno para a árvore (sem quadro dentro de quadro)

### History And Tree Contract
Histórico e árvore têm papéis distintos.

- histórico mostra o caminho percorrido
- árvore mostra os ramos de análise
- histórico não deve duplicar estados
- histórico não deve aninhar `decisões de aprofundamento` repetidamente
- `decisões de aprofundamento` deve aparecer como agrupador estrutural único por coluna, quando necessário

## Collection Board Rules
No quadro de coleção, manter apenas operação.

- exibir somente título e botões
- remover texto auxiliar, status textual e metadados decorativos
- preservar ações úteis dos cards (abrir/subir/descer/remover)

## Semantic Interface Principle
Elementos da interface devem deixar explícito seu papel operacional:

- decisões indicam caminhos de navegação
- valores/células são itens selecionáveis
- relações indicam conexões externas
- resumos/metadados descrevem o conjunto exibido, mas não são selecionáveis

## Value/Cell Layer Contract
Na camada `valor/célula`, cards de valor representam apenas valores reais da distribuição.

- Podem conter ações de navegação:
  - aprofundar análise
  - criar nova base
- Formato de exibição:
  - valor
  - impacto combinado: `X registros (Y%)`
  - ações disponíveis

Exemplo:

- Valor: `1012`
- Impacto: `1 registro (0.01%)`
- Ações: `Aprofundar análise`, `Criar nova base`

## Exception Sampling Summary
Em decisões do tipo `exceção`, quando existirem mais valores raros do que os exibidos, a interface deve exibir um resumo separado.

Formato:

- Título: `Resumo da amostra`
- Corpo: `<N> valores raros não exibidos`

Regras:

- não é valor selecionável
- não possui ações
- não deve ser tratado como `value_card`
- em payload/UI estruturada, representar como:

```json
{
  "type": "sample_summary",
  "selectable": false,
  "actions": []
}
```

Cards reais de valores devem manter:

```json
{
  "type": "value",
  "selectable": true,
  "actions": ["deepen", "new_base"]
}
```

## IA Integration Clarity
Para integração futura com IA/agentes, a interface deve evitar ambiguidade entre tipos de elementos.

Elementos mínimos distintos:

- `decision_card`
- `value_card`
- `relation_card`
- `sample_summary`
- `action_button`
- `navigation_state`

A inferência do papel de cada elemento deve ser possível sem depender apenas de aparência visual.

## Source Cards Rules
Na tela de origem, cards de unidades devem seguir padrão enxuto e comparável.

- sem narrativa longa e sem rótulos explicativos redundantes
- exibir dados estruturais de forma curta
- tamanho deve mostrar apenas campos disponíveis (`linhas` e/ou `colunas`)
- campos nulos não devem ser renderizados no card

## Presentation Contract (Cross-Layer)
Contrato transversal para todas as camadas de apresentação.

Objetivo: eliminar ruído visual/textual sem remover função operacional.

### Core Rule
- remover lixo/ruído
- preservar função

### Functional Invariants
- nenhuma ação útil pode desaparecer por simplificação visual
- nenhuma rota/estado de navegação pode ser removido por ajuste de apresentação
- quando houver 1 ação útil: exibir 1 botão
- quando houver 2 ações úteis: exibir 2 botões
- não exibir elementos decorativos que duplicam ação já disponível em botão

### Noise Elimination Rules
- evitar quadro dentro de quadro quando não há separação funcional real
- quando a mudança de função for pequena, preferir subtítulo em vez de novo quadro
- subtítulo só deve existir se orientar leitura/decisão
- evitar texto narrativo longo quando linha curta/tópico resolve
- evitar rótulos redundantes para dados já autoexplicativos no contexto
- ocultar campos nulos em vez de renderizar placeholders

### Layer Baseline
Aplicação mínima por camada, mantendo a função específica:

- origem:
  - mostrar seleção de origem em fluxo mínimo
  - cards curtos e comparáveis para unidades
- tabela:
  - mostrar contexto da unidade + caminhos para coluna
  - sem blocos narrativos redundantes
- coluna:
  - mostrar contexto estrutural da coluna + assinaturas disponíveis
  - sem duplicação entre contexto e cards de assinatura
- após `coluna`, estratégia de apresentação permanece em avaliação
- histórico de orientação:
  - único recipiente visual: título + árvore
  - sem subtítulo e sem quadro interno adicional
- quadro de coleção:
  - título + botões
  - sem status textual e sem metadados decorativos

### Acceptance Checklist
Uma camada está conforme o contrato quando:

- a função da camada continua completa
- o próximo passo é óbvio
- não há duplicação de informação entre título, subtítulo e card
- não há blocos visuais adicionais sem função estrutural

## Dataset-Agnostic Rule
As decisões da interface devem permanecer independentes do dataset em execução.

- o dataset carregado serve para verificar comportamento do sistema
- resultados concretos do dataset podem revelar falhas
- resultados concretos do dataset não podem definir regra de interface, navegação, ranking ou heurística

Formulação central:

- o dataset em execução pode revelar um problema, mas não pode definir a regra

## Rare Phenomena Contract
Contrato curto para fenômenos raros detectados de forma estrutural e agnóstica.

### Objective
Detectar raridade útil para navegação, sem promover ruído da distribuição.

### Structural Signals
- raridade local do valor (`freq` baixa)
- contexto da coluna (`unique_ratio`, `null_ratio`, `cardinality/rows`, `mode_ratio`)
- massa rara no total (`rare_rows_ratio`)
- contraste entre bloco raro e bloco dominante
- recorrência estrutural em outra coluna/tabela (quando existir)

### Promotion Rule
- baixa frequência sozinha não promove decisão
- a decisão só é promovida quando a raridade tiver peso estrutural no contexto da coluna
- em colunas near-unique, raridade banal não vira exceção coletiva

### Decision Split Rule
Um mesmo fenômeno pode gerar mais de um card apenas quando o papel operacional for diferente.

- card de coluna: fenômeno interno/localizado
- card de relação: conexão estrutural com outra coluna/tabela

Se os dois cards levarem ao mesmo caminho operacional, unificar em um.

### Output Rule
- `exception`: raridade estrutural útil
- `conflict`: quebra localizada em contexto near-unique
- `relation`: conexão estrutural externa
- sem promoção: quando não houver peso estrutural suficiente

## Current UI Quality Standard (Applied)
Padrão consolidado da interface para replicação nas próximas camadas.

### 1) Origem
- cards de tabela simplificados
- remoção de ruído, duplicação e placeholders
- sem `unidade em foco` automática no bloco superior
- bloco superior focado no estado da fonte

### 2) Tabela
- cards de coluna como janelas de decisão
- exibição curta: `signal`, assinaturas/heurísticas, decisões estruturais, `nulos` e `únicos`
- métricas completas fora do card-lista

### 3) Coluna
- contexto da coluna + decisões disponíveis
- cards de decisão como portas de navegação

### 4) Decisão: Exceção
- página própria
- caminho inclui `/exceção`
- valores raros como cards navegáveis
- resumo de amostra no contexto
- resumo de amostra não acionável

### 5) Decisão: Dominância
- página própria
- separação de estados:
  - coluna mostra decisões
  - dominância mostra valores
- `preview` não é lista navegável principal
- `values` representa navegação
- navegação até `valor/célula`

### 6) Valor/Célula
- camada analítica mínima no core
- bloco de detalhes estruturais:
  - comprimento
  - composição
  - traços
  - frequência
- comportamento validado para valor numérico, textual e alfanumérico

### 7) CSS / Cards
- altura acompanha conteúdo real
- botões do mesmo card com largura igual
- texto dos botões centralizado
- espaçamento interno padronizado

### 8) Navegação por identidade estável de valor
- navegação de `valor/célula` usa `value_id` estável
- resolução prioriza `selected_value_id`
- `selected_value` fica como fallback de compatibilidade
- distinção entre `None` e `""` preservada

## Princípios Inegociáveis
- o dataset em execução pode revelar problema, mas não define regra
- a interface não calcula análise
- a interface não consulta banco para completar card ou estado
- métricas pertencem ao core
- a interface apenas renderiza payload
- `preview` é amostra
- `values` é navegação
- cada estado mostra o contexto do próprio estado
- valor navegável precisa de identidade estável
- navegação não deve depender da string exibida
- `None` e string vazia devem permanecer distintos
- não normalizar valor silenciosamente para fazer match
- não aplicar `strip/lower/replace` em identidade navegável

## Diretrizes de Ciclo Atual
- card é janela de decisão, não relatório
- detalhe é onde aparece evidência completa
- `Criar nova base` não entra neste ciclo

## Progressão de Estados (Contrato)
- origem mostra unidades disponíveis
- tabela mostra colunas
- coluna mostra decisões disponíveis
- decisão mostra valores daquela decisão
- valor/célula mostra detalhes estruturais do valor

### Estados próprios
- exceção é estado próprio
- dominância é estado próprio
- valor/célula é estado próprio
- `Criar nova base` fica para etapa posterior

## Contrato de Exibição por Estado
### Origem
- mostra fonte, tipo, unidades detectadas e cards de tabelas
- não mostra unidade em foco automática
- não mostra placeholders para campos indisponíveis

### Tabela
- mostra contexto da tabela
- mostra cards de coluna

### Card de coluna
- nome
- signal
- assinaturas/heurísticas curtas
- decisões estruturais curtas
- nulos
- únicos
- ação de abrir coluna

### Coluna
- mostra contexto da coluna
- mostra decisões disponíveis
- não renderiza valores/células como conteúdo principal

### Decisão
- mostra contexto da decisão
- mostra seção `Valor/Célula`
- não mostra quadro geral de decisões da coluna
- não mostra contexto completo da coluna

### Valor/célula
- mostra contexto do valor
- mostra impacto
- mostra detalhes estruturais

## Contrato de Payload Navegável (Valor/Célula)
- `preview` representa amostra curta
- `values` representa lista navegável
- `values` não deve ser derivado na interface
- item navegável de valor deve carregar identidade estável
- item navegável deve carregar `count/ratio` quando disponíveis
- estado `valor/célula` deve resolver por `value_id` primeiro
- fallback textual só existe para compatibilidade

## Status de Entrega (Etapa Atual)
- origem ajustada
- cards de tabela ajustados
- cards de coluna ajustados
- página de exceção criada
- página de dominância criada
- página de valor/célula criada
- métricas de valor/célula criadas no core
- detalhes estruturais renderizados
- botões dos cards padronizados

## Bug Aberto (Próxima Sessão)
- bug: valor textual longo vindo de decisão ainda pode abrir `valor/célula` com impacto/frequência `0`
- causa provável: resolução ainda depende da string exibida em algum trecho do fluxo real, ou não prioriza `value_id` em toda a cadeia
- critério de correção: nenhum item vindo de `recorte.values` com `count > 0` pode abrir `valor/célula` com impacto/frequência `0`
