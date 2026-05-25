# Agent Global Rules

## Status

`ACTIVE`

## Level

`1 — GLOBAL AGENT RULES`

## Objective

Definir regras operacionais comuns a todos os agentes do projeto.

Estas regras valem para:

- agentes locais de módulo;
- agente orquestrador;
- agente gestor de contexto;
- agentes auxiliares;
- assistentes usados para refatoração;
- assistentes usados para documentação.

---

## Precedence

Este documento segue `docs/PROJECT_CONSTITUTION.md`.

Se houver conflito entre estas regras e a constituição do projeto, a constituição prevalece.

A tarefa atual pode restringir mais.

A tarefa atual não pode liberar algo proibido por documentos de nível superior.

---

## Core Working Principle

Cada agente deve trabalhar com escopo explícito, responsabilidade limitada e comportamento preservado.

```text
Uma tarefa.
Um eixo de responsabilidade.
Nenhuma mudança comportamental implícita.
Nenhum ruído deixado para trás.
```

---

## One Task, One Responsibility

Cada execução deve tratar apenas uma responsabilidade.

Permitido:

- mover uma policy;
- extrair uma função isolada;
- atualizar imports seguros;
- criar um documento;
- ajustar teste para comportamento preservado;
- auditar consumidores.

Proibido:

- mover arquivo e alterar regra;
- refatorar e mudar comportamento;
- corrigir teste e alterar arquitetura;
- mover vários eixos sem plano;
- limpar ruído e introduzir contrato novo.

---

## No Behavioral Drift

Durante refatoração estrutural, o agente não pode alterar comportamento.

Não alterar:

- assinatura;
- retorno;
- tipo;
- schema;
- validação;
- mensagem de erro;
- ordenação;
- ranking;
- cache;
- persistência;
- algoritmo;
- semântica pública;
- texto observável, salvo autorização explícita.

Se um teste falhar por divergência pré-existente, reportar separadamente.

Não corrigir divergência funcional dentro de tarefa estrutural.

---

## Audit Before Change

Antes de mover, remover ou renomear arquivo, o agente deve auditar consumidores.

A auditoria deve buscar:

- caminho qualificado antigo;
- nome do arquivo;
- símbolos públicos;
- imports diretos;
- imports agregados;
- reexports;
- testes relacionados.

Se houver consumidor real que não possa ser atualizado com segurança, a origem deve permanecer como compat bridge temporária.

---

## Audit After Change

Depois da alteração, o agente deve auditar novamente.

A auditoria final deve confirmar:

- ausência de imports legados inesperados;
- consumidores internos usando o novo caminho;
- ausência de bridges desnecessárias;
- testes focados executados;
- comportamento preservado.

---

## Compatibility Bridge Policy

Compat bridge só é permitida durante migração curta.

Uma bridge deve:

- conter apenas import/reexport;
- não conter lógica;
- existir apenas se houver consumidor real;
- ser marcada com:

```python
# DEPRECATED: compat bridge. Remove after migration cycle.
```

Não criar bridge se não houver consumidor real.

Remover bridge assim que consumidores forem migrados.

---

## No Duplicate Implementation

Nunca manter duas implementações reais do mesmo comportamento.

Após mover implementação:

- novo módulo vira dono real;
- origem é removida ou vira bridge mínima;
- imports internos são atualizados para o novo caminho;
- testes confirmam o novo caminho.

---

## Import Discipline

Imports devem refletir o dono real da responsabilidade.

Código novo deve importar do módulo dono.

Exemplo correto:

```python
from agnostic.sharing.policies.share_id_policy import is_valid_share_id
```

Exemplo a evitar em código interno novo:

```python
from agnostic.application.policies import is_valid_share_id
```

Fachadas públicas podem existir por compatibilidade, mas não devem guiar o design interno.

---

## Test Discipline

Toda tarefa deve declarar testes focados.

O agente deve reportar:

- testes executados;
- testes que passaram;
- testes bloqueados;
- motivo do bloqueio;
- testes não executados.

Quando dependência opcional estiver ausente, reportar como bloqueio ambiental, não como regressão, se confirmado.

Não rodar suíte inteira quando o ambiente já tem dependências opcionais ausentes e a tarefa tem testes focados suficientes.

---

## Reporting Rule

Ao concluir uma tarefa, o agente deve reportar:

- consumidores encontrados antes;
- arquivos criados;
- arquivos alterados;
- arquivos removidos;
- imports atualizados;
- consumidores restantes depois;
- testes executados;
- bloqueios ambientais;
- comportamento preservado;
- riscos restantes;
- próxima ação recomendada.

---

## Stop Conditions

O agente deve parar e pedir decisão quando encontrar:

- conflito com `PROJECT_CONSTITUTION.md`;
- mudança de contrato público;
- dúvida sobre dono de responsabilidade;
- necessidade de mover mais de um eixo funcional;
- dependência circular nova;
- falha de teste não relacionada à tarefa;
- consumidor externo presumido mas não verificável;
- risco de alteração comportamental;
- arquivo marcado como `NEEDS_ARCHITECTURE_DECISION`.

---

## Documentation Rule

Markdown é usado para instrução, governança e contexto.

JSON pode ser usado para contratos formais validáveis.

```text
Markdown explica.
JSON formaliza.
Código executa.
Testes garantem.
```

---

## Current Transitional Rule

O projeto ainda possui itens em transição.

Diretórios que aparecem apenas por `__pycache__` não contam como módulos ativos.

Arquivos pendentes de decisão não devem ser movidos automaticamente.

Itens conhecidos:

- `src/agnostic/application/ports/tabular_source.py`
- `src/agnostic/core/internal_cuts.py`
- `src/agnostic/core/analysis_common.py`
- `src/agnostic/core/errors.py`

---

## Success Criteria

Uma tarefa executada por agente é aceitável quando:

- respeita a constituição;
- tem escopo claro;
- preserva comportamento;
- não deixa duplicação;
- não deixa bridge desnecessária;
- atualiza imports internos;
- executa testes focados;
- reporta bloqueios;
- não cria novo acoplamento indevido.