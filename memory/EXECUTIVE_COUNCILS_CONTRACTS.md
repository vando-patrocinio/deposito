# 🏛️ EXECUTIVE COUNCILS — CONTRATOS DE HIERARQUIA

> **Operação:** LIGO EXECUTIVE OS — Fase A · Etapa 1 · Doc 2/5
> **Data:** 14/06/2026
> **Status:** Documento normativo.
> **Princípio:** *Existem 3 conselhos com papéis diferentes. Os 5 Conselhos do CTO entram como subseções do orquestrador — não como módulos independentes.*

---

## RESUMO EM 1 FRASE

```
isabella_conselho       = ATA RAW (Commanders convergem)
conselho_ia (route)     = ORQUESTRADOR (5 subseções)
presidente_ia_conselho  = PARECER LLM (sob demanda)
```

---

## NÍVEL 1 — `services/isabella_conselho.py` (224 linhas)

### 🎯 Função
**Ata diária consolidada dos Commanders.** Convergência operacional de Churn + Dunning + Revenue + Twin + Expansion + Conselho Comandantes. **Não é parecer estratégico.** É **registro do que aconteceu**.

### 📥 Entrada
- `isabella_commander_opportunities` (status=pending)
- `isabella_incidents` (status in {predicted, confirmed})
- Subordinados: `isabella_churn`, `isabella_dunning`, `isabella_revenue`, `isabella_twin`, `isabella_expansion`

### 📤 Saída
- Ata Markdown/JSON persistida em `isabella_council_minutes` (53 atas co-demo)
- Top 10 oportunidades pendentes
- Riscos críticos (score ≥ 80)
- Estimativa de receita prevista vs em risco

### 🤖 LLM?
**Não.** Agregação determinística.

### ⏰ Frequência
**Diária** (via `isabella_commanders_worker`).

### ✅ Quem consome
- `services/conselho_ia` (orquestrador acima) — **fonte primária** para os blocos Comercial + Operacional + Financeiro
- `routes/isabella_commanders`

### 🚫 Quem **NÃO** deve consumir
- ❌ CEO Briefing direto → vai via orquestrador (Nível 2)

---

## NÍVEL 2 — `routes/conselho_ia.py` (1.362 linhas) → **ORQUESTRADOR**

### 🎯 Função
**Endpoint configurável que gera o relatório executivo do dia.** Consome ata do Nível 1, agrega 7 collectors (`_collect_overview`, `_collect_network`, `_collect_technicians`, `_collect_atendimento`, `_collect_sales`, `_collect_universo_ligo`, `_collect_protege`), aplica Auditor IA (auto-correção) e Agent Loop (executa tools como `flag_dunning`).

### 📥 Entrada
- Ata do `isabella_conselho` (via collection `isabella_council_minutes`)
- `subscribers`, `tickets`, `subscriber_invoices`, `subscriber_addresses`, `sales_leads`, `motor_ia_predictions`
- 7 collectors específicos

### 📤 Saída
- Persistido em `conselho_ia_reports` (1 doc co-demo) + `conselho_ia_settings`
- Estrutura: `overview · network · technicians · atendimento · sales · universo_ligo · protege · ai_brief · agent_actions`

### 🤖 LLM?
**Sim** — em `_ai_brief` (modelo configurável via `conselho_ia_settings`).

### ⏰ Frequência
**Diária às 08:00 BRT** (via `conselho_ia_scheduler`).

### ✅ Quem consome
- **CEO Briefing futuro (Fase B)** — fonte primária do "Café com o CEO"
- `frontend/src/ConselhoIaPanel.js`

### 🚫 Quem **NÃO** deve consumir
- ❌ Não chamar para pareceres LLM por papel (CEO/COO/CTO/CFO/CPO) → vai ao Nível 3

---

## NÍVEL 3 — `services/presidente_ia_conselho.py` (235 linhas)

### 🎯 Função
**Pareceres LLM especializados das 6 cadeiras** (CEO/COO/CTO/CFO/CPO + Estrategista). Modelo: Claude Sonnet 4.6 via Emergent LLM Key. Cache 60min por (cid, role).

### 📥 Entrada
- Dashboard agregado do `presidente_ia` (Health, Risks, Opportunities)
- Prompts especializados em `ROLES` (system prompt por cadeira)

### 📤 Saída
- 6 pareceres textuais (cache in-memory 60min, não persiste)
- Tom: executivo sênior, direto, sem rodeios

### 🤖 LLM?
**Sim** — Claude Sonnet 4.6, custo médio-alto.

### ⏰ Frequência
**Sob demanda** (não diário). Cache 60min para reduzir custo.

### ✅ Quem consome
- `routes/presidente_ia.py::GET /conselho` e `/conselho/{role}`
- Painel do Presidente IA (botão "Pedir parecer do CEO IA")

### 🚫 Quem **NÃO** deve consumir
- ❌ CEO Briefing diário — caro demais para rodar todo dia × 6 cadeiras
- ❌ Conselhos do CTO (Comercial/Operacional/etc) — esses usam Nível 2

---

## OS 5 CONSELHOS DO CTO (SUBSEÇÕES DO NÍVEL 2)

Cada um dos 5 Conselhos pedidos pelo CTO entra como **bloco específico** dentro do orquestrador `conselho_ia.py::generate_report`. **Não cria módulo novo.** Cada bloco lê de provedores existentes e responde a **uma pergunta diária**.

### 🟢 Conselho Comercial — "Como vender mais?"
- **Responsável técnico (computa):** `agent_revenue.py` + `isabella_revenue.py` (oportunidades) + `services/sales_outreach.py`
- **Persona pública (assina):** Camila (voz comercial — ver `PERSONAS_GOVERNANCE.md`)
- **Lê de:** `isabella_commander_opportunities` (kind=revenue|expansion) + `sales_leads` + `subscriber_addresses` (clusters geográficos)
- **Produz:**
  - Top 3 gargalos comerciais
  - Top 3 oportunidades (regiões + produtos)
  - Indicações reais (com flag "INDISPONÍVEL" se referrals=0 reais)

### 🟢 Conselho Operacional — "Onde estamos falhando?"
- **Responsável técnico:** `alvaro_v5` + `isabella_incident` + `rede_ia_outage_detector` + `presidente_operator` (motor de Recuperação)
- **Persona pública:** Álvaro (já é módulo + persona)
- **Lê de:** `isabella_incidents` + `tickets` (recorrentes, last 30d) + `network_outages` + `field_os`
- **Produz:**
  - Bairros problemáticos (top 5)
  - CTOs com falhas recorrentes (top 5)
  - Técnicos com desvios (sem promessa se dado não existe — declara "INDISPONÍVEL")
  - Incidentes recorrentes (≥3 ocorrências em 30d)

### 🟢 Conselho Financeiro — "Onde estamos perdendo dinheiro?"
- **Responsável técnico:** `presidente_cash` + `presidente_financeiro` + `isabella_dunning` + `revenue_realization`
- **Persona pública:** Pâmela (voz de relacionamento/cobrança — ver `PERSONAS_GOVERNANCE.md`)
- **Lê de:** `subscriber_invoices` (status=overdue) + `executive_ledger` (já tagueado pós-Fase A) + `motor_ia_revenue_attribution` (kind=cost_saved)
- **Produz:**
  - Desperdícios identificados (custos anormais)
  - Inadimplência critica (clientes >30d)
  - Cancelamentos evitáveis (cruzando com `isabella_churn`)
  - Custos anormais (variação ≥ 20% MoM)

### 🟢 Conselho Produto — "O que os clientes querem?"
- **Responsável técnico:** `motor_ia_intel` (feedback/learnings) + `isabella_experience` + `nps_responses_mvp`
- **Persona pública:** Isabella (voz da experiência)
- **Lê de:** `motor_ia_learnings` + `experience_campaigns` + `nps_responses_mvp` (baixa massa por meses)
- **Produz:**
  - Desejos recorrentes (top 5, com tag de confiança)
  - Reclamações recorrentes (top 5)
  - Pedidos recorrentes (top 5)
- ⚠️ **Cuidado de governança:** NPS confiança BAIXA por meses — declarar em CADA relatório enquanto a base não cresce.

### 🟢 Conselho Universo Ligo — "Estamos criando pertencimento?"
- **Responsável técnico:** `universo_ligo_curadoria` (route) + `universo_ligo_v2` + `experience_campaigns`
- **Persona pública:** Pâmela (Guardiã da Comunidade)
- **Lê de:** `universo_ligo_invites` + `universo_ligo_scores` + `experience_campaigns`
- **Produz:**
  - Fundadores carimbados (APTO/REVISAR/NÃO CONVIDAR)
  - Invisíveis recém-tocados (zero — programa não disparado ainda)
  - Embaixadores ativos (carimbados na Lista Ouro)
  - Histórias reais (snippets dos `notes` dos invites)
- ⚠️ **Proibido produzir:** ranking, score, medalha, programa de fidelidade, cashback.

---

## ANATOMIA DO RELATÓRIO DIÁRIO (NÍVEL 2)

```json
{
  "id": "rpt-YYYY-MM-DD-co-demo-daily",
  "company_id": "co-demo",
  "period": "daily",
  "generated_at": "2026-06-14T11:00:00Z",
  "overview":     {...},   // collector existente
  "network":      {...},   // collector existente
  "technicians":  {...},   // collector existente
  "atendimento":  {...},   // collector existente
  "sales":        {...},   // collector existente
  "universo_ligo":{...},   // collector existente
  "protege":      {...},   // collector existente
  // NOVOS BLOCOS (Fase C — não nesta etapa):
  "conselho_comercial":   { "pergunta": "Como vender mais?", "gargalos": [...], ... },
  "conselho_operacional": { "pergunta": "Onde estamos falhando?", ... },
  "conselho_financeiro":  { "pergunta": "Onde estamos perdendo dinheiro?", ... },
  "conselho_produto":     { "pergunta": "O que clientes querem?", ... },
  "conselho_universo":    { "pergunta": "Estamos criando pertencimento?", ... },
  "ai_brief":     "...",   // texto LLM consolidado
  "agent_actions":[...]    // ações disparadas pelo Agent Loop
}
```

---

## DECISÕES TOMADAS POR ESTE DOC

1. ✅ **Não fundir os 3 conselhos.** São 3 níveis de uma pirâmide.
2. ✅ **Os 5 Conselhos do CTO** entram como **blocos novos no relatório do Nível 2**, não como módulos separados.
3. ✅ **Cada Conselho tem 1 pergunta diária** explícita (não múltiplas).
4. ✅ **Pamela e Camila** são **personas que assinam** os blocos públicos. O cálculo é feito por agentes reais. (Ver `PERSONAS_GOVERNANCE.md`)
5. ✅ **Pareceres LLM por cadeira (Nível 3)** ficam fora do briefing diário — caro demais.

## DÚVIDAS EM ABERTO

| # | Dúvida | Quem decide |
|---|---|---|
| D1 | Os 5 conselhos do CTO devem ser exibidos sempre, ou só quando houver "algo a dizer"? | Decisão na Fase C |
| D2 | Quem é o "responsável editorial" final do relatório? Liderança Ligo lê e edita antes de mandar ao CEO, ou IA manda direto? | Decisão na Fase B |
| D3 | Frequência do parecer LLM (Nível 3): sob demanda apenas, ou 1× por semana? | Decisão pós-Fase A |
