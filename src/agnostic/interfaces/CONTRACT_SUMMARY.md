# Interfaces Contract Summary

## Status

`ACTIVE`

## Module

`interfaces`

Path:

`src/agnostic/interfaces/`

## Purpose

Expor a superfície externa do sistema.

Este módulo apresenta contratos externos por API, schemas, rotas, rendering e assets, sem assumir responsabilidade analítica.

## Owns

- API externa;
- schemas externos;
- rotas;
- validação externa de entrada e saída;
- rendering de interface;
- assets estáticos;
- composição de resposta observável para consumidores externos.

## Does Not Own

- análise estrutural;
- métricas;
- heurísticas;
- cálculo de `signal`;
- ranking estrutural;
- regras analíticas de domínio;
- storage concreto;
- assinatura como posse primária de `sharing`;
- coordenação de casos de uso como posse primária de `application`.

## Public Surface Summary

Superfície pública esperada, sujeita a formalização detalhada em `CONTRACT.md`:

- aplicação HTTP exposta por `interfaces/api/`;
- rotas externas;
- schemas de request e response;
- contratos de rendering observável entregues à interface;
- assets estáticos e componentes de interface quando fizerem parte da superfície observável.

Validação externa em schemas não transforma `interfaces` em dona de regras de domínio.

Helpers de rendering só devem ser tratados como contrato público quando sua superfície observável e seu escopo estiverem explicitamente formalizados.

`NEEDS_DOCUMENTATION_DECISION`

- lista normativa final de rotas, schemas e superfícies externas estáveis;
- distinção formal entre contrato externo estável e helpers internos de rendering;
- política normativa para assets e componentes que façam parte da superfície pública.

## Main Producers

- `src/agnostic/interfaces/api/app.py`
- `src/agnostic/interfaces/api/routes.py`
- `src/agnostic/interfaces/api/schemas.py`
- `src/agnostic/interfaces/api/dependencies.py`
- `src/agnostic/interfaces/api/rendering/`
- `src/agnostic/interfaces/api/static/`
- `src/agnostic/interfaces/value_identity.py`

## Main Consumers

Consumidores atuais ou previstos pela documentação ativa:

- clientes HTTP externos;
- consumidores de schemas e respostas observáveis da interface;
- camadas de entrega externa que precisem da aplicação exposta.

O módulo também consome contratos públicos de:

- `application`
- `navigation`
- `sharing`

Consumo direto de tipos ou helpers de `domain` dentro de `interfaces` não deve ser promovido automaticamente a fronteira estável sem formalização contratual.

## Allowed Dependencies

- `application`, para casos de uso e fachadas públicas formalizadas;
- `navigation`, para contratos de navegação e validação externa associada;
- `sharing`, para contratos de compartilhamento e validação externa associada;
- `domain`, apenas quando houver contrato público explícito legitimando esse consumo;
- dependências internas do próprio módulo `interfaces`;
- dependências de framework e validação externa, como FastAPI e Pydantic.

Dependências de FastAPI e Pydantic podem bloquear testes por ambiente quando ausentes ou incompatíveis.

## Forbidden Dependencies

O módulo `interfaces` não pode depender de:

- lógica analítica própria;
- cálculo próprio de métricas;
- cálculo próprio de heurísticas;
- cálculo próprio de `signal`;
- alteração própria de ranking;
- redefinição de semântica analítica recebida;
- implementação interna de outros módulos sem contrato público explícito.

Rendering deve apresentar contratos recebidos, não alterar sua semântica analítica.

## Contract Notes

- `interfaces` expõe a superfície externa do sistema.
- Schemas e validações externas devem refletir contratos recebidos, não substituir regras internas de domínio.
- Rendering deve transformar contrato em apresentação observável sem alterar o conteúdo analítico de origem.
- Dependências de framework podem introduzir bloqueios ambientais de teste e devem ser reportadas como tal quando ocorrerem.
- Mudança em rota pública, schema público, envelope observável ou semântica de resposta externa é mudança contratual.

## Pending Decisions

`NEEDS_DOCUMENTATION_DECISION`

- lista final de rotas e schemas públicos do módulo;
- política final para identificar quais renderers fazem parte da superfície pública;
- papel documental de `value_identity.py` dentro da superfície contratual do módulo.

`NEEDS_ARCHITECTURE_DECISION`

- escopo público real de `interfaces`: apenas API/schemas externos ou também helpers de rendering;
- qualquer dependência direta de `domain` que hoje não passe por contrato público explicitamente formalizado;
- política final para considerar assets estáticos e componentes como parte contratual estável da interface.

## Escalation Triggers

Escalar quando houver:

- criação, remoção ou mudança de rota pública;
- criação ou mudança de schema público observável;
- mudança de semântica em rendering observado externamente;
- necessidade de calcular análise dentro de `interfaces`;
- dependência nova de implementação interna de `domain`, `application`, `sharing` ou `navigation`;
- dúvida sobre se um helper de rendering faz parte da superfície pública;
- conflito entre validação externa e contrato público do módulo produtor.
