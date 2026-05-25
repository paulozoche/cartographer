# IO Registry

## Status

`ACTIVE`

## Objective

Definir a finalidade, a governança e o uso do registro formal de contratos públicos entre módulos.

`docs/IO_REGISTRY.md` é a documentação humana do registro.

`docs/IO_REGISTRY.json` será a fonte formal e validável dos contratos registrados.

Este documento não cria contratos específicos por si só.

Este documento não substitui a constituição do projeto, o registro de módulos ou a documentação local de cada módulo.

---

## Files

### `docs/IO_REGISTRY.md`

Documento humano.

Explica:

- por que o registro existe;
- o que deve ou não deve ser registrado;
- como manter o arquivo JSON;
- quando escalar mudanças para o Orchestrator;
- como relacionar o registro com a documentação de módulos.

### `docs/IO_REGISTRY.json`

Documento formal.

Deve conter o inventário validável dos contratos públicos entre módulos.

Ele é a referência operacional para:

- producer;
- consumers;
- tipo de contrato;
- direção de dependência;
- status contratual;
- compatibilidade;
- observações formais necessárias.

Se houver conflito entre este Markdown e o JSON, a precedência documental do projeto deve ser respeitada.

---

## What Is An Inter-Module Contract

Conta como contrato entre módulos toda entrada, saída ou fronteira pública usada para comunicação entre módulos ativos.

Isso inclui, quando público e observável:

- DTO;
- schema;
- dataclass pública;
- `Protocol`;
- porta;
- função exportada;
- erro público;
- campo de resposta;
- formato de ID;
- envelope;
- estado compartilhável;
- semântica de validação;
- chave de cache observável;
- import público entre módulos;
- relação formal producer/consumer.

Um item só deve entrar no IO Registry quando representar uma fronteira pública real entre módulos, e não apenas organização interna de código.

Se houver dúvida sobre publicidade, estabilidade ou dono da fronteira, marcar como `NEEDS_DOCUMENTATION_DECISION`.

Se a dúvida envolver posse de responsabilidade, fronteira de módulo ou destino de artefato transitório, marcar como `NEEDS_ARCHITECTURE_DECISION`.

---

## What Is Not An Inter-Module Contract

Não conta como contrato entre módulos:

- implementação interna;
- helper privado;
- função local não exportada como fronteira pública;
- detalhe interno de algoritmo;
- heurística interna;
- métrica interna;
- adapter concreto usado apenas dentro do próprio módulo;
- estrutura transitória sem publicidade definida;
- diretório existente apenas por `__pycache__`;
- conveniência de import sem intenção pública formalizada;
- detalhe de teste;
- detalhe de refatoração local;
- dependência incidental de implementação.

Implementação interna não vira contrato público só porque outro módulo a importou por conveniência.

Se houver uso cruzado de implementação interna, isso indica risco documental ou arquitetural; não deve ser normalizado automaticamente no registro.

---

## JSON Registry Ownership

O `docs/IO_REGISTRY.json` pertence à governança global do projeto.

Sua manutenção deve ser guiada por:

- `docs/PROJECT_CONSTITUTION.md`;
- `docs/MODULE_REGISTRY.md`;
- `docs/ORCHESTRATOR_PROTOCOL.md`;
- `src/agnostic/<module>/CONTRACT.md`;
- `src/agnostic/<module>/CONTRACT_SUMMARY.md`.

O JSON não deve ser preenchido por inferência livre a partir de implementação interna.

O JSON deve registrar contratos já reconhecidos como públicos.

Quando um contrato ainda não estiver suficientemente definido para registro formal, o ponto deve permanecer fora do JSON até haver documentação suficiente ou decisão explícita.

---

## Required JSON Fields

Os campos abaixo são esperados no `docs/IO_REGISTRY.json`.

Os nomes finais dos campos ainda dependem de padronização e devem ser tratados como `NEEDS_DOCUMENTATION_DECISION` até a criação do JSON.

Campos obrigatórios esperados:

- identificador estável do contrato;
- módulo produtor;
- módulos consumidores conhecidos;
- tipo de contrato;
- símbolo, artefato ou fronteira pública registrada;
- caminho documental de referência;
- status contratual;
- compatibilidade;
- descrição curta da função do contrato;
- observações ou restrições relevantes, quando necessárias.

Campos fortemente recomendados:

- versão ou marcador de evolução;
- indicador de transitoriedade;
- origem formal da decisão;
- notas de migração, quando houver;
- vínculo com reexport ou façade, quando aplicável.

### Exemplo fictício

O exemplo abaixo é ilustrativo.

Ele não representa contrato real do projeto.

```json
{
  "contract_id": "example.public_output.v1",
  "producer_module": "example_producer",
  "consumer_modules": ["example_consumer"],
  "contract_kind": "dto",
  "public_symbol": "ExamplePublicOutput",
  "reference_doc": "src/agnostic/example_producer/CONTRACT.md",
  "status": "active",
  "compatibility": "backward_compatible",
  "description": "Fictitious example only."
}
```

### Pending field standardization

`NEEDS_DOCUMENTATION_DECISION`

- nome exato da chave do identificador estável;
- formato do campo de consumidores;
- enum oficial de `contract_kind`;
- enum oficial de `status`;
- enum oficial de `compatibility`;
- política de versionamento por contrato.

---

## Adding A Contract

Adicionar um contrato novo exige evidência documental de que a fronteira é pública e inter-module.

Fluxo recomendado:

1. confirmar o módulo produtor no `docs/MODULE_REGISTRY.md`;
2. confirmar que a fronteira não é implementação interna;
3. registrar ou atualizar o contrato no `CONTRACT.md` do módulo produtor;
4. resumir o contrato no `CONTRACT_SUMMARY.md` do módulo produtor;
5. registrar a entrada correspondente em `docs/IO_REGISTRY.json`;
6. atualizar `docs/IO_REGISTRY.md` apenas se a regra global de governança mudar, não para listar o contrato em si.

Não adicionar contrato novo:

- por leitura casual da árvore;
- por import interno isolado;
- por conveniência de refatoração;
- para legitimar dependência indevida;
- para resolver ambiguidade arquitetural pendente.

Se não houver documentação suficiente para registrar a fronteira com precisão, marcar como `NEEDS_DOCUMENTATION_DECISION`.

---

## Changing A Contract

Alterar contrato existente é mudança contratual.

A mudança deve ser tratada como relevante quando alterar:

- entrada pública;
- saída pública;
- schema;
- DTO;
- `Protocol`;
- porta;
- erro público;
- formato de ID;
- envelope;
- estado compartilhável;
- semântica observável;
- relação producer/consumer;
- import público entre módulos.

Fluxo recomendado:

1. revisar o contrato atual no JSON;
2. revisar o `CONTRACT.md` do módulo produtor;
3. identificar consumidores conhecidos;
4. classificar compatibilidade da mudança;
5. escalar para o Orchestrator quando houver impacto inter-module real;
6. atualizar o JSON somente depois da mudança estar documentalmente definida.

Mudança de implementação interna que não altera fronteira pública não deve gerar atualização do IO Registry.

---

## Removing A Contract

Remover contrato exige comprovação de que ele deixou de ser fronteira pública válida.

Antes de remover:

1. confirmar ausência de consumidores reais ou necessidade de compatibilidade temporária;
2. revisar `CONTRACT.md` e `CONTRACT_SUMMARY.md` do módulo produtor;
3. verificar se a remoção é substituição, descontinuação ou migração;
4. registrar status apropriado no JSON antes de exclusão definitiva, quando houver fase transitória.

Não remover contrato:

- só porque o símbolo foi movido internamente;
- só porque surgiu um reexport;
- sem revisar impacto em consumers;
- para mascarar decisão arquitetural pendente.

Se o contrato ainda precisar existir por migração controlada, tratá-lo como transitório.

---

## Transitional Contracts

Contratos transitórios podem existir durante migração curta e explícita.

Um contrato transitório deve:

- ter motivo claro;
- possuir producer definido;
- possuir status explícito no JSON;
- apontar o contrato alvo, quando existir;
- indicar se ainda há consumers reais;
- ter remoção planejada.

Contrato transitório não deve virar solução permanente por omissão documental.

Itens marcados em documentação ativa como pendentes de fronteira ou posse de responsabilidade não devem ser promovidos automaticamente a contrato estável.

Se a transição depender de redefinir dono de responsabilidade, marcar como `NEEDS_ARCHITECTURE_DECISION`.

---

## Reexports And Façades

Reexports e façades podem existir por compatibilidade ou conveniência pública controlada.

Eles não definem, por si só, posse de responsabilidade.

Regras:

- o dono do contrato continua sendo o módulo responsável;
- o IO Registry deve registrar a fronteira pública real, não duplicar artificialmente a implementação;
- um reexport pode ser mencionado como observação contratual, se ele fizer parte da superfície pública observável;
- façade pública só deve ser registrada como fronteira própria quando sua semântica pública estiver explicitamente documentada.

Se um reexport existir apenas como ponte técnica curta, ele não deve ser tratado automaticamente como novo contrato independente.

Se a política exata de registro de façades públicas ainda não estiver fechada para todos os casos, marcar como `NEEDS_DOCUMENTATION_DECISION`.

---

## Agent Usage

Agentes devem usar o IO Registry para:

- identificar produtores e consumidores;
- verificar se uma mudança é contratual;
- evitar tratar implementação interna como contrato;
- confirmar se uma fronteira já está formalizada;
- orientar escopo de atualização documental;
- apoiar classificação de impacto entre módulos.

O IO Registry não substitui:

- a constituição;
- o registro de módulos;
- o `CONTRACT.md` do módulo;
- o `CONTRACT_SUMMARY.md` do módulo;
- investigação autorizada pelo Context Manager quando necessária.

Quando o JSON ainda não existir ou estiver incompleto, agentes devem evitar inferir contratos ausentes como se fossem formais.

Nesses casos, marcar lacunas como `NEEDS_DOCUMENTATION_DECISION`.

---

## Escalation Rules

Escalar para o Orchestrator quando houver:

- criação de novo contrato inter-module;
- alteração de contrato público existente;
- remoção de contrato com consumers conhecidos ou presumidos;
- dúvida sobre producer;
- dúvida sobre consumers relevantes;
- mudança de fronteira entre módulos;
- mudança de import público entre módulos;
- conflito entre `MODULE_REGISTRY.md` e documentação local;
- necessidade de classificar compatibilidade;
- risco de normalizar implementação interna como contrato público.

Escalar como `NEEDS_ARCHITECTURE_DECISION` quando houver:

- dúvida sobre dono de responsabilidade;
- redefinição de limites de módulo;
- estabilização indevida de item transitório;
- necessidade de tornar `core` fonte contratual estável sem decisão explícita.

Escalar como `NEEDS_DOCUMENTATION_DECISION` quando houver:

- falta de padronização de campos do JSON;
- dúvida sobre granularidade do registro;
- dúvida sobre como representar façade ou reexport estável;
- falta de documentação suficiente para formalizar a fronteira.

---

## Relationship With Other Documents

### `docs/PROJECT_CONSTITUTION.md`

Define as regras soberanas.

O IO Registry deve respeitar:

- isolamento de responsabilidade entre módulos;
- obrigatoriedade de contratos públicos explícitos;
- proibição de tratar implementação interna como contrato;
- precedência da análise determinística e das fronteiras explícitas.

### `docs/MODULE_REGISTRY.md`

Define módulos ativos, responsabilidades públicas e limites.

O IO Registry não substitui esse mapa.

Ele detalha apenas as fronteiras públicas entre módulos que já precisam de registro formal.

### `src/agnostic/<module>/CONTRACT.md`

É a definição contratual detalhada do módulo.

Quando existir, deve ser a fonte específica do conteúdo contratual daquele módulo.

O IO Registry aponta e organiza contratos entre módulos; não deve repetir toda a especificação local.

### `src/agnostic/<module>/CONTRACT_SUMMARY.md`

É o resumo operacional do contrato do módulo.

O Orchestrator pode usá-lo para classificação rápida de impacto.

O IO Registry deve permanecer compatível com esse resumo, sem substituí-lo.

---

## Stop Conditions

Parar e registrar bloqueio quando:

- for necessário inventar contrato específico ainda não documentado;
- a fronteira pública não puder ser distinguida de implementação interna;
- houver conflito com `PROJECT_CONSTITUTION.md`;
- houver conflito com `MODULE_REGISTRY.md`;
- a mudança depender de resolver item marcado como `NEEDS_ARCHITECTURE_DECISION`;
- a padronização do JSON exigir decisão não documentada;
- a existência de producer ou consumers não puder ser afirmada com segurança.

---

## Success Criteria

Este documento está correto quando:

- explica a função do IO Registry com clareza;
- diferencia corretamente Markdown de JSON;
- define o que conta e o que não conta como contrato entre módulos;
- orienta adição, alteração e remoção de contratos;
- cobre contratos transitórios e reexports sem inventar casos reais;
- instrui agentes sobre uso e escalonamento;
- mantém alinhamento com a documentação ativa;
- não duplica regras globais completas;
- não inventa contratos específicos do projeto;
- deixa explícitos os pontos ainda dependentes de `NEEDS_DOCUMENTATION_DECISION`.
