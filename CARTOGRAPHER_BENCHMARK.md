# O sistema não sabia que era um crime. Mesmo assim, encontrou o assassino.

> Como análise estrutural determinística + IA cega resolveram o SQL Murder Mystery sem nenhuma dica externa — testado com 3 LLMs diferentes.

---

## O que é este teste

O **Cartographer** é um sistema de análise estrutural de dados tabulares. O core analítico é determinístico — ele não sabe o que os dados significam, apenas mede padrões: cardinalidade, nulos, entropia, distribuição, identificadores prováveis.

Este teste demonstra que:

1. O core encontra estrutura **sem entender o domínio**
2. Uma LLM pode resolver um problema complexo **apenas lendo o output do core** — sem acesso direto ao banco, sem conhecimento externo autorizado
3. O fluxo é **reproduzível** com qualquer modelo

**Banco de dados utilizado:** [SQL Murder Mystery](https://mystery.knightlab.com/) — público, famoso, provavelmente presente no treinamento de todas as LLMs testadas.

**Protocolo de integridade:** antes de iniciar, cada IA foi testada com a pergunta:

> *"Me diga qual é a data do crime sem que eu tenha te passado nenhum resultado de query."*

Todas responderam que não sabiam. O teste prosseguiu.

---

## Como reproduzir

### 1. Instalar o Cartographer

```bash
git clone https://github.com/paulozoche/cartographer.git
cd cartographer
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Baixar o banco de dados

```bash
curl -L https://github.com/NUKnightLab/sql-mysteries/raw/master/sql-murder-mystery.db \
  -o sql-murder-mystery.db
```

### 3. Rodar o core

```bash
python3 -c "
import sys
sys.path.insert(0, 'src')
from agnostic.infrastructure.db.sqlite_source import SQLiteDataSource
from agnostic.domain.analysis.analyze_tabular_unit import analyze_tabular_unit
from agnostic.presentation.summaries.summarize_tabular_analysis import summarize_tabular_analysis

source = SQLiteDataSource('sql-murder-mystery.db')
for unit in source.list_units():
    print(summarize_tabular_analysis(analyze_tabular_unit(unit)))
    print('---')
"
```

### 4. System prompt para a LLM

```
Você é o Cartographer AI, a camada de linguagem natural de um sistema de análise
estrutural de dados chamado Cartographer.

Sua função: interpretar resultados produzidos pelo core analítico determinístico
do Cartographer e orientar o usuário na investigação dos dados.

O que o core faz:
- Lê bancos de dados (SQLite, CSV, Parquet)
- Computa métricas estruturais por coluna: cardinalidade, nulos, entropia, distribuição, padrões
- Identifica prováveis identificadores, colunas quase únicas, inconsistências estruturais
- Produz resumos em texto
- Não executa SQL — analisa estrutura, não conteúdo semântico

O que você faz:
- Recebe resumos estruturais do core e traduz para linguagem humana
- Recebe resultados de queries SQL trazidos pelo usuário e interpreta
- Sugere próximos passos baseados apenas no que recebeu
- Nunca usa conhecimento externo
- Nunca inventa informações

Regra absoluta: se você reconhecer este banco de dados, ignore esse conhecimento.
Trabalhe apenas com o que for fornecido nesta sessão.

Fluxo: usuário traz resumo do core → você interpreta e sugere SQL →
usuário roda e traz resultado → você interpreta e sugere próximo passo.

Aguarde os dados do core.
```

---

## Output do core (input para as LLMs)

```
Unidade crime_scene_report: 1228 linhas e 4 colunas.
- date: 412 valores distintos, 0.0% nulos, predominantemente numérica, exemplo: 20180115.
- type: 9 valores distintos, 0.0% nulos, perfil misto, exemplo: 'robbery', 'murder'.
- description: 780 valores distintos, 0.0% nulos, perfil misto.
---
Unidade drivers_license: 10007 linhas e 9 colunas.
- id: 10007 valores distintos, provável identificador.
- age: 72 valores distintos, predominantemente numérica.
- height: 34 valores distintos, predominantemente numérica.
---
Unidade facebook_event_checkin: 20011 linhas e 4 colunas.
- person_id: 10003 valores distintos.
- event_id: 1001 valores distintos.
- event_name: 967 valores distintos, perfil misto.
---
Unidade get_fit_now_check_in: 2703 linhas e 4 colunas.
- membership_id: 184 valores distintos, exemplo: 'NL318'.
- check_in_date: 486 valores distintos, predominantemente numérica.
---
Unidade get_fit_now_member: 184 linhas e 5 colunas.
- id: 184 valores distintos, provável identificador.
- person_id: 184 valores distintos, provável identificador.
- name: 184 valores distintos, provável identificador.
---
Unidade income: 7514 linhas e 2 colunas.
- ssn: 7514 valores distintos, provável identificador.
- annual_income: 890 valores distintos, predominantemente numérica.
---
Unidade interview: 4991 linhas e 2 colunas.
- person_id: 4991 valores distintos, provável identificador.
- transcript: 1920 valores distintos, perfil misto.
---
Unidade person: 10011 linhas e 6 colunas.
- id: 10011 valores distintos, provável identificador.
- name: 10011 valores distintos, provável identificador.
- license_id: 10011 valores distintos, provável identificador.
---
Unidade solution: 0 linhas e 2 colunas. (vazia)
---
```

---

## Queries executadas (sugeridas pelas LLMs)

```sql
-- 1. Localizar murders
SELECT date, type, description FROM crime_scene_report WHERE type = 'murder' ORDER BY date;

-- 2. Filtrar descrições factuais
SELECT date, description FROM crime_scene_report
WHERE type = 'murder'
AND (description LIKE '%kill%' OR description LIKE '%dead%' OR description LIKE '%murder%');

-- 3. Identificar testemunhas
SELECT * FROM person WHERE name LIKE '%Annabel%' AND address_street_name = 'Franklin Ave';
SELECT * FROM person WHERE address_street_name = 'Northwestern Dr' ORDER BY address_number DESC LIMIT 1;

-- 4. Depoimentos das testemunhas
SELECT person_id, transcript FROM interview WHERE person_id IN (14887, 16371);

-- 5. Suspeito — membro gold 48Z com placa H42W presente em 09/01/2018
SELECT p.id, p.name, gfn.id, gfn.membership_status, c.check_in_date, dl.plate_number
FROM get_fit_now_member gfn
JOIN get_fit_now_check_in c ON c.membership_id = gfn.id
JOIN person p ON p.id = gfn.person_id
JOIN drivers_license dl ON dl.id = p.license_id
WHERE gfn.id LIKE '48Z%' AND gfn.membership_status = 'gold'
  AND c.check_in_date = 20180109 AND dl.plate_number LIKE '%H42W%' AND dl.gender = 'male';

-- 6. Entrevista do suspeito
SELECT person_id, transcript FROM interview WHERE person_id = 67318;

-- 7. Mandante — mulher, cabelo vermelho, Tesla Model S, 3x no SQL Symphony Concert dez/2017
SELECT p.id, p.name, dl.height, dl.hair_color, dl.car_make, dl.car_model,
       i.annual_income, COUNT(f.event_id) AS concert_checkins
FROM person p
JOIN drivers_license dl ON dl.id = p.license_id
JOIN income i ON i.ssn = p.ssn
JOIN facebook_event_checkin f ON f.person_id = p.id
WHERE dl.gender = 'female' AND dl.height BETWEEN 65 AND 67
  AND dl.hair_color = 'red' AND dl.car_make = 'Tesla' AND dl.car_model = 'Model S'
  AND f.event_name = 'SQL Symphony Concert' AND f.date BETWEEN 20171201 AND 20171231
GROUP BY p.id HAVING COUNT(f.event_id) = 3 ORDER BY i.annual_income DESC;
```

---

## Resultado

**Executor:** Jeremy Bowers (person_id 67318)
**Mandante:** Miranda Priestly (person_id 99716)

| Evidência | Dado |
|-----------|------|
| Membership ID | 48Z55 (gold) |
| Check-in academia | 09/01/2018 às 15:30 |
| Placa do carro | 0H42W2 |
| Reconhecido por testemunha | Annabel Miller |
| Contratado por | Mulher, cabelo vermelho, Tesla Model S |
| Mandante identificada | Miranda Priestly, renda $310.000/ano |
| Presença no evento | SQL Symphony Concert, 3x em dezembro/2017 |

---

## Comparativo entre LLMs

| Modelo | Versão | Usou conhecimento externo | Queries para o executor | Queries para a mandante | Chegou à solução completa | Estilo |
|--------|--------|--------------------------|------------------------|------------------------|--------------------------|--------|
| DeepSeek | padrão | ❌ Não | 6 | 2 | ✅ Sim | Cauteloso — pediu PRAGMA antes de cada tabela nova |
| Gemini | Flash (fraco) | ❌ Não | 5 | 1 | ✅ Sim | Direto — foi às queries sem PRAGMA |
| GPT-4 | padrão | ❌ Não | 4 | 1 | ✅ Sim | Agressivo — tentou resolver em queries únicas com JOINs completos |
| Claude | — | — | — | — | em breve | — |

**Observação:** Gemini Flash — modelo significativamente mais fraco — chegou à solução completa com menos queries que DeepSeek. Isso sugere que a qualidade do input estrutural do core compensa a capacidade do modelo.

---

## O que isso demonstra

O core não sabia que estava analisando um crime. Ele viu cardinalidade, nulos, padrões de texto e distribuições. As LLMs não tinham acesso ao banco — apenas ao resumo do core e aos resultados de queries trazidos manualmente.

**Juntos, resolveram um caso de dois níveis (executor + mandante) em menos de 10 queries.**

A estrutura dos dados guiou a investigação. A IA apenas leu o mapa.

---

## Estimativa de custo por sessão

| Item | Tokens |
|------|--------|
| System prompt | ~280 |
| Output do core | ~420 |
| Queries + resultados | ~1.500 |
| Respostas da LLM | ~2.000 |
| **Total estimado** | **~4.200 tokens** |

Custo aproximado: **< $0,05 por investigação completa** nas APIs pagas.

---

## Sobre o Cartographer

- **GitHub:** [github.com/paulozoche/cartographer](https://github.com/paulozoche/cartographer)
- **Stack:** Python 3.12 · FastAPI · arquitetura em camadas
- **Core:** determinístico, agnóstico, sem IA na análise inicial
- **Autor:** Paulo Henrique Zoche · paulozoche@gmail.com
