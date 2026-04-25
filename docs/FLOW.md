# Flow

## Status

`ACTIVE`

## Objective

Definir a progressão analítica e as regras de transição entre estados.

## Progression

```
origem → tabela → coluna → decisões de aprofundamento → valor/célula → caractere
```

## Invariants

Violação quebra o modelo de progressão.

1. Até `coluna`: progressão posicional e obrigatória
2. A partir das decisões de aprofundamento: progressão orientada por estado estrutural do nó em foco
3. O estado seguinte depende de: tipo de decisão, estado estrutural, evidências disponíveis e transições permitidas pelo nó
4. O ranking do nível corrente é sempre aplicado por `signal` (ordem decrescente)

Ver invariante global de precedência estrutural: ARCHITECTURE.md.

## Analysis Tree

- Progressão descreve um ramo, não o modelo global
- Nova base cria novo ramo
- Múltiplos ramos coexistem — análises não se cancelam
- Recorte promovido reinicia como nova base (ver INTERFACES.md para exposição)

## Limits

- Recorte é uma decisão possível, não obrigatória
- Nem toda decisão leva ao mesmo estado seguinte
- Valor/célula e caractere são aprofundamentos possíveis dentro do ramo, não sequência linear obrigatória
- Este documento não define métricas, heurísticas, persistência, contratos de serialização ou implementação de rotas
- `tools` paralelas opcionais não alteram o fluxo base nem o ranking global

## Decision Display Rules (UI)
Regras de exibição que preservam o fluxo atual:

- `dominância`: mostra `top N` valores por frequência (ordem decrescente)
- `exceção`: mostra amostra representativa de valores raros
- `exceção` não usa ranking global de valores; usa recorte de raros + resumo de amostra quando necessário
- resumo de amostra é metadado de exibição, não valor navegável
- sistema guia exploração estrutural; não interpreta semântica dos dados e não responde objetivo do usuário

Ver: ARCHITECTURE.md · APPLICATION.md · INTERFACES.md
