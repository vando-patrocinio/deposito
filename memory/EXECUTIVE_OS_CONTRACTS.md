# 🧠 EXECUTIVE OS — CONTRATOS DAS 4 CAMADAS PRESIDENCIAIS

> **Operação:** LIGO EXECUTIVE OS — Fase A · Etapa 1 · Doc 1/5
> **Data:** 14/06/2026
> **Status:** Documento normativo. Define contratos públicos.
> **Princípio:** *Os 4 Presidentes NÃO são duplicidade. São 4 camadas distintas. Esse doc formaliza isso.*

---

## RESUMO EM 1 FRASE

```
presidente_ia          = MEMÓRIA / VISÃO
presidente_executive   = FINANCEIRO / R$
presidente_brain       = SIMULAÇÃO / CENÁRIOS
presidente_operator    = EXECUÇÃO / AÇÕES
```

Cada cérebro tem **um e apenas um** dever. Quem violar deve ser corrigido em code review.

---

## CAMADA 1 — `services/presidente_ia.py` (660 linhas)

### 🎯 Função
**Memória corporativa + observação contínua.** Núcleo do "Presidente IA V2.0". Fluxo: `OBSERVA → ENTENDE → CORRELACIONA → PREVÊ → DECIDE → AGE → APRENDE`. **Nunca chama LLM.**

### 📥 Entrada (lê)
- `motor_ia_events` — stream de eventos (insert-only)
- `motor_ia_memory` — memória de longo prazo (insights consolidados)
- `motor_ia_insights` — insights gerados na varredura
- `motor_ia_predictions` — predições com score 0-100
- `motor_ia_decisions` — decisões tomadas (com contexto)
- `motor_ia_actions` — ações executadas (rastreabilidade)
- `motor_ia_learnings` — aprendizados (feedback loop)
- `subscribers`, `tickets`, `network_outages`, `ctos`, `smartolt_onus` (para `compute_corporate_health`)

### 📤 Saída (funções públicas)
- `compute_corporate_health(cid)` → **Health Score 0-100** (saúde geral)
- `compute_risks(cid, health)` → `{criticos, altos, medios}`
- `compute_opportunities(cid)` → `{items}`
- `compute_clients_at_risk(cid)` → top N
- `proactive_scan(cid)` → varredura ativa
- Catálogo `AGENT_ORBIT` (14 agentes orbitais)

### 🗂️ Coleções escritas
- `motor_ia_insights` (cache de insights)
- `motor_ia_predictions` (atualização de predições)
- Demais collections `motor_ia_*` são **append-only** por outros serviços

### ✅ Quem PODE consumir
- `services/secretaria_tools.py` (5 funções)
- `services/leo_proactive.py`
- `services/presidente_ia_briefing.py` (Café com IA do CEO)
- `routes/presidente_ia.py`
- Qualquer endpoint que precise de **Health Score** ou **lista de riscos/oportunidades agregada**.

### 🚫 Quem **NÃO** deve usar
- ❌ Endpoints financeiros precisando de **R$** → usar `presidente_executive`
- ❌ Simulações "e se fizermos X?" → usar `presidente_brain`
- ❌ Execução de ações concretas → usar `presidente_operator`
- ❌ Pareceres CEO/COO/CTO via LLM → usar `presidente_ia_conselho`

### ⚠️ Risco se outra camada duplicar este papel
Se outro arquivo começar a calcular Health Score por conta própria, **divergência de número** entre dashboards. **Health Score é palavra-chave reservada deste módulo.**

---

## CAMADA 2 — `services/presidente_executive.py` (884 linhas)

### 🎯 Função
**Camada de monetização.** Tudo em R$. Saída: 8 blocos (`president_score`, `riscos`, `oportunidades`, `previsao_30d`, `dinheiro_em_risco`, `dinheiro_recuperavel`, `surpresas`, `acoes`). **Heurística determinística** (não LLM).

### 📥 Entrada (lê)
- `subscribers`, `smartolt_onus`, `tickets`, `network_outages`, `ctos`
- `motor_ia_predictions`, `motor_ia_insights`
- `parcerias_*`, `contracts`, `invoices`
- `sales_leads`, `site_leads`, `indicacao_leads`, `referrals`
- `olt_snmp_cache`
- Constantes: `P_CHURN_SIGNAL_CRITICAL=0.22`, `P_CHURN_TICKET_OPEN_7D=0.05`, `RETENTION_RECOVERY_RATE=0.40`, `TICKET_AVG_BACKUP_BRL=117.43`

### 📤 Saída (funções públicas)
- `build_executive_report(cid)` → 8 blocos com R$
- `_base_q(cid)` → filtro Mongo (já corrigido com `$nin` sintéticos em 14/06)

### 🗂️ Coleções escritas
- Nenhuma. **Read-only**.

### ✅ Quem PODE consumir
- `routes/presidente_ia.py` (`GET /executive`)
- `services/executor_ia.py`
- `services/score_recovery.py` (3 chamadas)
- `services/governador_ia.py`
- `services/presidente_evolution.py`
- `services/presidente_brain.py` (intra-família — usa para context)
- **CEO Briefing futuro** (Fase B) — único componente autorizado a chamar `build_executive_report` para gerar a linha de "Receita / Dinheiro em risco" do Café com o CEO.

### 🚫 Quem **NÃO** deve usar
- ❌ Health Score → use `presidente_ia`
- ❌ Atribuição de receita por agente → use `agent_revenue.py` (ver `EXECUTIVE_REVENUE_CONTRACTS.md`)
- ❌ Simulação de cenário → use `presidente_brain`

### ⚠️ Risco se outra camada duplicar este papel
"Executive Score" e "Dinheiro em risco" são **propriedade desta camada**. Outro módulo calculando independente = números divergentes no briefing CEO. **Risco político** porque o número é mostrado ao CEO todo dia.

### ⚖️ Health Score vs Executive Score — POLÍTICA OFICIAL
- **Health Score (0-100, presidente_ia)** = saúde *interna* da operação. Não exposto ao CEO no briefing.
- **Executive Score (R$, presidente_executive)** = saúde *monetizada*. **Único score exposto no Café com o CEO.**

São números **diferentes por design**. Não tente convergir.

---

## CAMADA 3 — `services/presidente_brain.py` (521 linhas)

### 🎯 Função
**Cérebro de simulação de cenários.** V12 Causality Engine + V13 Digital Twin + V14 Autopilot Simulation (top 10 decisões). **Read-only**, não cria coleção persistente nova.

### 📥 Entrada (lê)
- `corporate_goals`
- Snapshot do `presidente_executive.build_executive_report` (intra-família)
- `motor_ia_actions`, `motor_ia_outcomes`
- `CATEGORY_EFFECT` interno: `REAJUSTE_IPCA → mrr_brl`, `DISPARO_COBRANCA → dinheiro_em_risco_brl`, `CONTATO_LEO_PROATIVO → churn_previsto_30d_brl`, etc.

### 📤 Saída (funções públicas)
- Simulações: "se rodarmos X ação Y vezes, qual o impacto esperado em campo Z?"
- Top 10 decisões previstas (Autopilot)
- Causalidade entre ações passadas e outcomes

### 🗂️ Coleções escritas
- **Nenhuma persistente.** Apenas memória temporária.

### ✅ Quem PODE consumir
- Endpoints de planejamento ("o que vamos fazer este mês?")
- **CEO Briefing futuro** (Fase B/E) — opcional, para responder "o que fazer agora?" no CEO Mode

### 🚫 Quem **NÃO** deve usar
- ❌ Como fonte de números reais (são simulações)
- ❌ Para receita realizada → use `revenue_realization`
- ❌ Para Health Score → use `presidente_ia`

### ⚠️ Risco se outra camada duplicar este papel
Se outro módulo começar a simular cenários sem usar `CATEGORY_EFFECT`, **dois mundos paralelos** de "e se?". Difícil de auditar. **Toda simulação executiva é deste módulo.**

---

## CAMADA 4 — `services/presidente_operator.py` (1.033 linhas)

### 🎯 Função
**Executor operacional.** Transforma o Presidente IA de **analista** em **operador**. Três motores: Oportunidades, Economia, Recuperação. **Matriz de Autonomia 4 níveis** (N1 autônoma → N4 humano-only). **Briefing matinal** com 6 perguntas. Executa ações via `executor_ia`.

### 📥 Entrada (lê)
- `motor_ia_actions`, `corporate_goals`, `subscribers`, `invoices`, `smartolt_onus`, `motor_ia_subscriber_scores`
- `services/executor_ia` (dispara ações)

### 📤 Saída (funções públicas)
- `company_value(cid)` — valor consolidado da empresa
- 3 motores: Oportunidades / Economia / Recuperação
- Briefing matinal (6 perguntas obrigatórias) — **DIFERENTE** do Café com o CEO
- Seed das 8 metas corporativas permanentes (idempotente)

### 🗂️ Coleções escritas
- `motor_ia_actions` (via executor_ia, indireto)
- `corporate_goals` (seed)

### ✅ Quem PODE consumir
- `services/presidente_cash.py` (`company_value` × 2)
- Painéis operacionais que mostram ações pendentes
- **Conselho Operacional futuro** (Fase C) — única fonte de "ações operacionais pendentes"

### 🚫 Quem **NÃO** deve usar
- ❌ Para análise executiva sem ação → use `presidente_executive`
- ❌ Para histórico de outcomes → use `presidente_ia` (memória)

### ⚠️ Risco se outra camada duplicar este papel
**Disparo duplicado de ação.** Se outro módulo chamar `executor_ia` sem passar pela Matriz de Autonomia, **risco de spam para cliente** (mensagem duplicada, OS duplicada). **Toda ação executiva concreta passa por este módulo.**

---

## CONTRATO DE INTEROPERABILIDADE

```
                ┌──────────────────┐
                │   CEO BRIEFING   │  (Fase B — futuro)
                │  /  CEO MODE     │
                └────────┬─────────┘
                         │ lê (em ordem)
            ┌────────────┼────────────┬──────────────┐
            ▼            ▼            ▼              ▼
   ┌──────────────┐ ┌─────────┐ ┌──────────┐ ┌──────────────┐
   │ presidente_ia│ │executive│ │  brain   │ │   operator   │
   │  (memória)   │ │  (R$)   │ │(simulação│ │  (execução)  │
   └──────┬───────┘ └────┬────┘ └────┬─────┘ └──────┬───────┘
          │              │           │              │
          │              │           │              │
          ▼              ▼           ▼              ▼
     motor_ia_*    R$ heurística  simulação    executor_ia
```

**Regra de ouro:** o CEO Briefing NUNCA puxa direto de coleções operacionais. Sempre via uma das 4 camadas presidenciais. **Razão:** as camadas já aplicam o filtro `$nin SYNTHETIC_TENANTS` corretamente.

---

## DECISÕES TOMADAS POR ESTE DOC

1. ✅ **Manter os 4 arquivos como estão.** Sem fusão.
2. ✅ **Health Score** ≠ **Executive Score** por design.
3. ✅ Cada arquivo terá um header normativo (adicionado na Etapa 3) referenciando este doc.
4. ✅ CEO Briefing (Fase B) consome **`presidente_executive`** para "linha financeira" e **`presidente_ia`** para "linha de risco/oportunidade". Nunca duas vezes a mesma métrica de duas fontes.

## DÚVIDAS EM ABERTO

| # | Dúvida | Quem decide |
|---|---|---|
| D1 | Em qual momento `presidente_brain` (simulação) entra no CEO Briefing? Como "previsão" ou como "recomendação"? | Decisão na Fase B |
| D2 | `presidente_operator` deve sugerir ações no Café com o CEO ou só no painel próprio? | Decisão na Fase B |
| D3 | Os 4 arquivos eventualmente vão para `/app/backend/services/presidente/` (pasta dedicada)? | Decisão pós-Fase A |
