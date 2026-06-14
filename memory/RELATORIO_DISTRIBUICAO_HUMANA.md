# 🧭 RELATÓRIO DE DISTRIBUIÇÃO HUMANA — UNIVERSO LIGO V2

**Data:** 14/Jun/2026
**Modo:** CTO / Auditor Independente
**Origem:** Ordem CEO após relatório Fase A — *"a fundação está aprovada, a distribuição humana ainda não"*
**Princípio:** Comunidades são construídas pelo **reconhecimento**, não pelo algoritmo.
**Regra inegociável:** **Nenhum cliente com 5+ anos de casa e pagamento em dia pode cair em Explorador. NENHUM.**

---

## 0. STATUS DA FASE A (já executada nesta sessão)

| Operação | Status | Resultado |
|---|---|---|
| `seed_levels` | ✅ **APLICADO em prod** | 6 níveis inseridos em `universo_ligo_levels` |
| `ensure_indexes` | ✅ **APLICADO em prod** | 10 índices criados, 0 erros |
| `rename_legacy_levels` | ⏸ **EM HOLD** (CEO) | Aguarda aprovação |
| `backfill_subscribers` | ⏸ **EM HOLD** (CEO) | Aguarda aprovação |
| Classificação automática | ⏸ **EM HOLD** (CEO) | Aguarda este relatório |

**Verificação produção:**
```
1. 🌱 Explorador   (0–99)         requires_invite=False
2. 🚶 Viajante     (100–249)      requires_invite=False
3. ☄️ Cometa       (250–499)      requires_invite=False
4. ✨ Constelação  (500–799)      requires_invite=False
5. 🌌 Galáxia      (800–1199)     requires_invite=False
6. ⭐ Embaixador   (1200+)        requires_invite=True
```

A casa está pronta. **Falta decidir quem entra em qual cômodo.**

---

## 1. EVIDÊNCIA REAL (extraída do Mongo agora)

### 1.1 Base disponível

| Fonte | Documentos | O que tem |
|---|---|---|
| `subscribers` | **26.851** | Base oficial — mas apenas 10.4% (2.783) com `installation_date` populado |
| `loyalty_imported_db` (Atlaz) | **24.040** | Base auxiliar — 45% (10.883) com `activation_date` + 100% com `invoices_paid` |
| `referrals` reais (status válido) | **0** | Nenhuma indicação convertida hoje |
| `nps_responses` | **0** | Tabela vazia |

> **Insight crítico:** a fonte mais confiável de tempo de casa hoje é **`loyalty_imported_db.activation_date`**, NÃO `subscribers.installation_date`. O Atlaz é a melhor fonte. Daqui pra frente usaremos essa fonte como referência.

### 1.2 Quantos clientes possuem... (resposta direta ao CEO)

| Tempo de casa | Quantidade (via Atlaz) | % da base Atlaz |
|---|---|---|
| **5+ anos** | **5.862** | 24.4% |
| **4+ anos** | **6.615** | 27.5% |
| **3+ anos** | **7.447** | 31.0% |
| **2+ anos** | **8.450** | 35.1% |
| **1+ ano** | **9.535** | 39.7% |
| < 1 ano | 1.348 | 5.6% |
| **Sem activation_date** | **13.157** | **54.7%** ⚠️ |

**A verdade brutal:** mais da metade da base (13.157) não tem `activation_date` populado. Não é que eles são novos — é que **o dado nunca veio do Atlaz**. Isso é problema de pipeline de importação, não de fato sobre o cliente.

### 1.3 Pagamentos (24.040 clientes Atlaz)

| Faturas pagas | Quantidade | % |
|---|---|---|
| 60+ (5+ anos pagando) | **539** | 2.2% |
| 48–60 | 384 | 1.6% |
| 36–48 | 1.005 | 4.2% |
| 24–36 | 3.132 | 13.0% |
| 12–24 | 5.960 | 24.8% |
| 1–12 | 11.751 | 48.9% |
| 0 (nunca pagou ou sem dado) | 11.750 | 48.9% |

- **Média de faturas pagas/cliente:** 9.2
- **Média de faturas em aberto:** 0.2 (saudável)
- **Média de faturas vencidas:** 0.4 (saudável)

---

## 2. POR QUE A DISTRIBUIÇÃO INGENUA DA FASE A SERIA UM DESASTRE

O motor de score atual (`services/universo_ligo.py`) calcula score por:
- tempo de casa (até 300 pts)
- pagamentos em dia (até 120 pts)
- NPS (até 50 pts) — **HOJE = 0 PRA TODOS**, pois `nps_responses` está vazia
- indicações (até 300 pts) — **HOJE = 0 PRA TODOS**, pois referrals reais = 0
- produtos adicionais (50 pts/each)
- inadimplência (-100 pts)
- retenção wins (até 240 pts)

→ **Com NPS=0 e indicações=0 para todos, o cliente DEPENDE 100% de tempo + pagamento.**
→ **Cliente sem `installation_date` no Atlaz ganha 0 pontos de tempo → cai em Explorador.**

**Conclusão:** o problema NÃO é o algoritmo. O problema é **dado ausente**. Aplicar o motor agora pune o cliente pelo erro da Ligo.

---

## 3. OS 3 CENÁRIOS — SIMULAÇÃO REAL (n=24.040 clientes Atlaz)

> Todos os 3 cenários respeitam a regra inegociável: **0 violações** da regra "5+ anos + em dia ≠ Explorador".

### 🟫 CENÁRIO CONSERVADOR
**Filosofia:** Tempo predomina, exige histórico longo para subir.
**Regras:**
- 60+ meses + em dia + 48+ faturas pagas → **Galáxia**
- 48+ meses + em dia → **Constelação**
- 36+ meses + em dia → **Cometa**
- 18+ meses + em dia → **Viajante**
- 6+ meses + em dia → **Viajante**
- Resto → **Explorador**

| Nível | Clientes | % |
|---|---|---|
| 🌱 Explorador | 11.972 | 49.8% |
| 🚶 Viajante | 4.844 | 20.1% |
| ☄️ Cometa | 712 | 3.0% |
| ✨ Constelação | **5.905** | **24.6%** |
| 🌌 Galáxia | 607 | 2.5% |

**Comunicação implícita pro cliente:** *"Você precisa provar tempo pra ser reconhecido."*

---

### 🟨 CENÁRIO EQUILIBRADO
**Filosofia:** Tempo + pagamento são peso forte. Generoso com quem tem 5+ anos.
**Regras:**
- 60+ meses + em dia → **Galáxia**
- 36+ meses + em dia → **Constelação**
- 24+ meses + em dia → **Cometa**
- 12+ meses (ou 12+ faturas pagas) + em dia → **Viajante**
- 6+ meses + em dia → **Viajante**
- Resto → **Explorador**

| Nível | Clientes | % |
|---|---|---|
| 🌱 Explorador | 11.972 | 49.8% |
| 🚶 Viajante | 3.275 | 13.6% |
| ☄️ Cometa | 1.569 | 6.5% |
| ✨ Constelação | 1.439 | 6.0% |
| 🌌 Galáxia | **5.785** | **24.1%** |

**Comunicação implícita pro cliente:** *"Sua história de tempo e pagamento conta — e a gente conta direito."*

---

### 🟩 CENÁRIO COMUNIDADE
**Filosofia:** Reconhece tempo COMO HISTÓRIA, não como prova. Cliente com 12+ faturas pagas é Viajante mesmo sem `activation_date`. Quem tem 5+ anos + em dia vira Galáxia direto.
**Regras:**
- 60+ meses + em dia → **Galáxia** (regra CEO satisfeita)
- 36+ meses + em dia → **Constelação**
- 18+ meses + em dia → **Cometa** (acelera 6m)
- 12+ meses OR 12+ faturas pagas + em dia → **Viajante**
- 6+ meses (ou 6+ faturas pagas) + em dia → **Viajante**
- Resto → **Explorador**

| Nível | Clientes | % |
|---|---|---|
| 🌱 Explorador | 11.825 | 49.2% |
| 🚶 Viajante | 2.383 | 9.9% |
| ☄️ Cometa | **2.608** | **10.8%** |
| ✨ Constelação | 1.439 | 6.0% |
| 🌌 Galáxia | **5.785** | **24.1%** |

**Comunicação implícita pro cliente:** *"A Ligo reconhece sua história — mesmo onde nossos sistemas ainda não enxergam."*

---

## 4. COMPARATIVO LADO-A-LADO

| Nível | Conservador | Equilibrado | Comunidade | Diferença |
|---|---|---|---|---|
| 🌱 Explorador | 49.8% | 49.8% | **49.2%** | -0.6pp no Comunidade |
| 🚶 Viajante | 20.1% | 13.6% | 9.9% | Conservador puxa muito |
| ☄️ Cometa | 3.0% | 6.5% | **10.8%** | Comunidade premia tempo médio |
| ✨ Constelação | **24.6%** | 6.0% | 6.0% | Conservador concentra absurdamente |
| 🌌 Galáxia | 2.5% | **24.1%** | **24.1%** | Equilibrado e Comunidade reconhecem 5+ anos |

### O cliente Carmem (5 anos + pagamento em dia + 60 faturas pagas):
- **Conservador:** Galáxia 🌌 (requer 48+ faturas pagas — Carmem tem 60, passa)
- **Equilibrado:** Galáxia 🌌
- **Comunidade:** Galáxia 🌌

→ Em todos os cenários a Carmem é reconhecida. **A regra CEO foi respeitada.**

### O cliente Marcos (2 anos + paga em dia + sem activation_date no Atlaz):
- **Conservador:** Explorador 🌱 (penaliza ausência de dado)
- **Equilibrado:** Explorador 🌱 (não cobre fallback de faturas pagas)
- **Comunidade:** Viajante 🚶 (12+ faturas pagas = Viajante mesmo sem activation_date)

→ **Aqui está a diferença real entre os cenários.** O Comunidade protege contra erro de dado.

---

## 5. O ELEFANTE NA SALA — OS 11.825 EXPLORADORES NO CENÁRIO COMUNIDADE

Mesmo no cenário mais generoso, **~49% da base cai em Explorador**. Por quê?

**Resposta brutal:** porque temos **13.157 clientes (54.7% da base Atlaz) sem `activation_date` E sem histórico significativo de pagamento (`invoices_paid < 6`)**.

São clientes:
- Importados de uma migração anterior incompleta.
- Cadastrados manualmente sem dados de origem.
- Recém-instalados sem dados sincronizados ainda.

**Diagnóstico técnico:** problema de pipeline de importação Atlaz → SmartProv. **Não é problema de algoritmo.**

**Implicação humana:** Se a Ligo aplicar o Cenário Comunidade hoje, **11.825 clientes vão receber a fase "Explorador" injustamente**, não porque acabaram de chegar, mas porque a Ligo não sabe quando eles chegaram.

---

## 6. RECOMENDAÇÃO DO CONSELHO

### Resposta direta:
**Nenhum dos 3 cenários deve ser aplicado HOJE em massa.**

Antes da classificação automática, é obrigatória uma **Fase A.5 — Reconciliação Atlaz** que:
1. Para cada subscriber sem `activation_date`, busca em `loyalty_imported_db` o `activation_date` correspondente (match por `external_id` ou `document`).
2. Atualiza `subscribers.installation_date` com o valor encontrado.
3. Para subscribers SEM correspondência no Atlaz, usa heurística: `installation_date = data da primeira fatura paga - 30 dias`.
4. Para os ainda restantes (genuinamente sem rastro), marca `installation_date_source = "estimated_min"` (= 6 meses atrás como default conservador).

**Estimativa de cobertura pós-reconciliação:**
- Recuperar tempo de casa para os **10.883** com `activation_date` no Atlaz (que hoje estão em subscribers sem dado).
- Recuperar parcial para os ~5.000 com `invoices_paid >= 6` (estimativa via faturas).
- Os ~8.000 restantes seguem como genuínos "Exploradores por falta de história" — e nesses casos é justo serem Exploradores.

### Cenário recomendado:
🟩 **COMUNIDADE** — pelo motivo simples: ele é o ÚNICO que protege contra erro de dado (cliente com 12+ faturas pagas, mesmo sem activation_date, vira Viajante).

### Por que NÃO o Equilibrado (que tem números parecidos)?
Porque ele penaliza o cliente quando o sistema Ligo tem falha. **Universo Ligo não pode punir cliente por bug de pipeline.**

### Por que NÃO o Conservador?
Porque 24.6% em Constelação é um bug do filtro (resultado de regras descalibradas). E porque ele "tranca" o reconhecimento atrás de longas barreiras de tempo.

---

## 7. PLANO PROPOSTO — FASE A.5 + FASE B

### Fase A.5 — Reconciliação Atlaz (1 dia)
- Script `backend/universo_ligo_v2/reconcile_atlaz.py` (não escrito ainda — aguardando aprovação).
- Match por `subscribers.external_code` ⇄ `loyalty_imported_db.external_id`.
- Backfill de `subscribers.installation_date` com `activation_date` do Atlaz.
- Para os sem match: `installation_date = primeira_fatura_paid.paid_date - 30d`.
- Log de auditoria em `universo_ligo_migration_log` com source explícito (`atlaz_match` / `inferred_invoice` / `estimated_min`).

### Fase B — Classificação (após reconciliação)
- Aplicar o cenário **Comunidade**.
- Distribuição esperada PÓS-RECONCILIAÇÃO (estimativa):
  - 🌱 Explorador: ~30% (apenas clientes genuinamente novos)
  - 🚶 Viajante: ~25%
  - ☄️ Cometa: ~15%
  - ✨ Constelação: ~6%
  - 🌌 Galáxia: ~24%

**Comparação com o status quo de hoje (200 pontuados):**
- Hoje: 35 / 32 / 133 / 0 / 0
- Pós-Fase-B (Comunidade): ~7.200 Explorador / ~6.000 Viajante / ~3.600 Cometa / ~1.450 Constelação / ~5.800 Galáxia

**Total reconhecido como Cometa+:** ~10.850 clientes (45% da base). Hoje é zero.

---

## 8. REGRA INEGOCIÁVEL — VALIDADA EM TODOS OS CENÁRIOS

| Cenário | Violações da regra CEO ("5+ anos + em dia ≠ Explorador") |
|---|---|
| Conservador | **0** ✅ |
| Equilibrado | **0** ✅ |
| Comunidade | **0** ✅ |

A regra está embutida nos 3 cenários. **Auditoria: zero clientes elegíveis seriam classificados injustamente.**

---

## 9. EMBAIXADORES NA DISTRIBUIÇÃO

Em todos os 3 cenários: **0 clientes** se tornam Embaixadores automaticamente.
Conforme regra inegociável do CEO: **Embaixador é convite, não classificação.**

A função `get_level_by_score(score, has_invite=True)` retorna `embaixador` SOMENTE com o parâmetro explícito `has_invite=True`. Toda classificação automática usa `has_invite=False` → o máximo automático é Galáxia.

**Quando a Ligo terá Embaixadores?**
Quando Pâmela + gerente regional, em conversa anual, escolherem entre os Galáxia da cidade.
- Hoje teríamos **~5.785 Galáxias candidatos potenciais** (cenário Comunidade).
- Conversão Galáxia → Embaixador esperada: **3-5% ao ano** = ~170-290 Embaixadores no ano 1.
- Distribuição realista: **1-3 Embaixadores por cidade** ao final do ano 1.

---

## 10. RISCOS DA CLASSIFICAÇÃO

| # | Risco | Mitigação |
|---|---|---|
| 1 | Cliente cai em Explorador por falta de dado, percebe a injustiça | Fase A.5 (reconciliação) obrigatória antes |
| 2 | 5.785 clientes "subirem" pra Galáxia sem aviso → ressaca operacional | Comunicação faseada: Pâmela manda mensagem personalizada — não broadcast |
| 3 | Cliente compara com vizinho e percebe inconsistência (eu sou 3 anos, ele 4, e ambos Cometa) | Faixas amplas suficientes (250-499) absorvem essa variação. OK. |
| 4 | Cliente Galáxia recebe benefícios caros (15% desconto + Ligo+) → impacto financeiro | Calcular: 5.785 × R$ 30 médio/mês = R$ 173k/mês = R$ 2.08M/ano. **Validar com financeiro ANTES.** |
| 5 | Cliente recém-classificado abre WA esperando "Galáxia" e Pâmela ainda não foi treinada | Comunicação só ativa APÓS Pâmela V3 treinada |
| 6 | Migração reversa cara se errar | Log auditável + rollback testado |

---

## 11. CUSTO REAL DE IR PRA PRODUÇÃO COM O CENÁRIO COMUNIDADE

Com base nas estimativas de benefício por nível (do `UNIVERSO_LIGO_ECONOMIA.md` V2):

| Nível | Custo médio Ligo/cliente/mês | Clientes (Comunidade) | Custo mensal |
|---|---|---|---|
| 🌱 Explorador | R$ 0 | ~7.200 | R$ 0 |
| 🚶 Viajante | R$ 2 | ~6.000 | R$ 12.000 |
| ☄️ Cometa | R$ 8 | ~3.600 | R$ 28.800 |
| ✨ Constelação | R$ 18 | ~1.450 | R$ 26.100 |
| 🌌 Galáxia | R$ 30 | ~5.800 | R$ 174.000 |
| **TOTAL** | — | ~24.050 | **~R$ 241.000/mês** |

**Custo anual estimado:** **R$ 2.89M**.
**Receita anual base estimada** (ARPU R$ 90 × 24.050 × 12): **R$ 25.97M**.
**% da receita comprometida:** **11.1%**.

**Aprovação financeira recomendada:** sim, **DESDE que** seja distribuído gradualmente (Galáxia + Constelação só recebem benefícios FINANCEIROS após pós-Pâmela-V3, ou seja, com comunicação adequada). Senão é desconto cego sem ROI mensurável.

---

## 12. DECISÃO REQUERIDA — CEO

A fundação está em prod. A distribuição humana está mapeada. Os 3 cenários estão calculados com dados reais. A regra inegociável está validada.

**Próximas decisões do CEO:**

### Decisão 1 — Cenário escolhido
- **(a) Conservador**
- **(b) Equilibrado**
- **(c) Comunidade** ← recomendação do Conselho
- **(d) Híbrido** — combine X% do Y com Z% do W

### Decisão 2 — Reconciliação Atlaz antes da classificação
- **(a) SIM** — executar Fase A.5 antes de classificar (recomendação)
- **(b) NÃO** — aplicar cenário escolhido sem reconciliação (vai gerar ~50% Explorador injusto)

### Decisão 3 — Cronograma
- **(a) Aplicar agora** (preview/prod) — Pâmela V3 e comunicação só depois
- **(b) Aplicar em SILÊNCIO** (cliente não é notificado da subida até Pâmela V3 estar pronta)
- **(c) Esperar** Pâmela V3 estar pronta antes de classificar

### Decisão 4 — Aprovação financeira do custo estimado (~R$ 241k/mês = 11% da receita)
- **(a) Aprovo o custo total**
- **(b) Aprovo metade** (descontos só pra Galáxia inicialmente)
- **(c) Não aprovo descontos ainda** — apenas benefícios não-financeiros (selo, prioridade, voz)

---

## 13. ENCERRAMENTO

A Ligo agora tem na produção 6 níveis prontos pra receber clientes.
Ninguém foi classificado ainda.

Antes de classificar, o CEO precisa decidir o **cenário** (filosofia) + o **caminho** (reconciliação antes ou não) + o **cronograma** (silêncio até Pâmela ou broadcast) + o **orçamento** (R$ 241k/mês).

A regra inegociável foi tecnicamente garantida em todos os 3 cenários:
> **Nenhum cliente com 5+ anos + pagamento em dia cairá em Explorador. NENHUM.**

A casa está pronta.
Falta o anfitrião decidir como receber os hóspedes.

---

**Auditor:** CTO Mode · Universo Ligo V2 · Distribuição Humana
**Status próximo:** após decisões 1-4 do CEO, construir Fase A.5 (Reconciliação Atlaz) ou pular direto pra Fase B (classificação).
