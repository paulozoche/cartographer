# Infrastructure Contract Summary

## Status

`ACTIVE`

## Module

`infrastructure`

Path:

`src/agnostic/infrastructure/`

## Purpose

Implementar adaptadores concretos para o mundo externo.

## Owns

- clientes externos;
- storage concreto;
- fontes CSV, Parquet e SQLite;
- exportação concreta;
- provedores concretos de IA;
- integrações de revogação concretas;
- filesystem e integrações operacionais externas.

## Does Not Own

- análise estrutural;
- métricas;
- heurísticas;
- cálculo de `signal`;
- ranking estrutural;
- regras de domínio;
- contratos externos de interface como posse primária;
- decisões de navegação.

## Public Surface Summary

Superfície pública esperada, sujeita a formalização detalhada em `CONTRACT.md`:

- adapters concretos legitimamente expostos;
- implementações concretas de portas públicas de outros módulos;
- fontes de dados concretas e mecanismos concretos de exportação;
- provedores concretos necessários à execução.

Nem todo adapter concreto deve ser tratado automaticamente como contrato público estável.

`NEEDS_DOCUMENTATION_DECISION`

- lista normativa final de adapters concretos que fazem parte da superfície pública do módulo;
- distinção formal entre implementação concreta disponível e contrato estável suportado;
- política final para exposição pública de clientes concretos de IA e storage.

## Main Producers

- `src/agnostic/infrastructure/storage/`
- `src/agnostic/infrastructure/db/`
- `src/agnostic/infrastructure/export/`
- `src/agnostic/infrastructure/ai/`

Diretórios sem código runtime ativo suficiente para contrato não devem ser promovidos automaticamente a superfície pública.

## Main Consumers

Consumidores atuais ou previstos pela documentação ativa:

- `application`
- `interfaces`
- `sharing`, quando houver implementação concreta de portas que ele possua

Consumidores devem depender de contratos públicos e portas, não de acoplamento incidental a detalhes concretos.

## Allowed Dependencies

- `domain`, `application`, `sharing` e `ai` apenas na medida necessária para implementar portas ou consumir tipos públicos formalizados;
- dependências internas do próprio módulo `infrastructure`;
- bibliotecas externas de integração, storage, rede e execução operacional.

## Forbidden Dependencies

O módulo `infrastructure` não pode depender de:

- definição de regra analítica;
- cálculo próprio de métricas;
- cálculo próprio de heurísticas;
- cálculo próprio de `signal`;
- alteração própria de ranking;
- redefinição de comportamento de domínio;
- implementação interna de outros módulos como substituto de contrato público.

## Contract Notes

- `infrastructure` conecta o sistema ao mundo externo; não define comportamento analítico.
- Implementação concreta de porta não transfere posse do contrato para `infrastructure`.
- Mudança em adapter concreto só é mudança contratual quando alterar superfície pública observável, semântica externa ou implementação pública formalmente suportada.
- Persistência e exportação concretas permanecem suporte operacional.

## Pending Decisions

`NEEDS_DOCUMENTATION_DECISION`

- lista final de adapters concretos públicos do módulo;
- política final para identificar implementações concretas oficialmente suportadas;
- relação normativa entre portas públicas de outros módulos e implementações concretas daqui.

`NEEDS_ARCHITECTURE_DECISION`

- fronteira entre `ai` e `infrastructure/ai`;
- qualquer caso em que adapter concreto esteja hoje definindo comportamento que deveria pertencer a outro módulo;
- política final para o que permanece público em `infrastructure` versus apenas disponível internamente.

## Escalation Triggers

Escalar quando houver:

- mudança em implementação concreta formalmente exposta;
- mudança em semântica externa observável de fonte de dados, exportação ou provider;
- tentativa de mover regra analítica para `infrastructure`;
- dúvida sobre posse de responsabilidade entre `infrastructure` e o módulo dono da porta;
- mudança de fronteira entre `ai` e `infrastructure/ai`.
