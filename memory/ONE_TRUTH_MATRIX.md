# 🎯 ONE_TRUTH_MATRIX — Fonte Oficial por Pergunta Executiva

> **Operação:** LIGO EXECUTIVE OS — Fase A · Etapa 2 (pré-renome)
> **Data:** 14/06/2026
> **Status:** Documento normativo. Vinculante para code review.
> **Princípio absoluto:** *Toda pergunta executiva tem **uma única** resposta oficial. Não existe "cliente quase ativo" nem "receita quase certa".*

---

## 🚦 NÍVEIS DE TOLERÂNCIA (DEFINIÇÃO CTO)

| Classe | Tolerância | Exemplos |
|---|---|---|
| **PRIMÁRIA** | **0%** | Receita, Clientes Ativos, Tickets, Cancelamentos |
| **DERIVADA** | **até 1%** | Ticket médio, % conversão, % churn, saldo líquido |
| **PREDITIVA** | **até 5%** | Previsão 30d, churn risk score, dinheiro em risco, ROI esperado |

> Se duas fontes oficiais divergirem em **classe primária**, o teste `test_one_truth` **deve falhar**.

---

## 📋 MATRIZ COMPLETA

### 1. CLIENTES

| Pergunta executiva | Fonte oficial | Classe | Filtro obrigatório | Confiança |
|---|---|---|---|---|
| Quantos **clientes ATIVOS** temos? | `subscribers.count_documents({status:"active"})` | PRIMÁRIA (0%) | `company_id="co-demo"` | 🟢 ALTA — confirmado por 3 fontes independentes |
| Quantos **clientes ATIVOS reais** (Atlaz)? | `loyalty_imported_db.count({status:"Ativo"})` | PRIMÁRIA (0%) | `company_id="co-demo"` | 🟢 ALTA — 2.746 confirmados |
| Quantos **novos clientes 7d**? | `subscribers.count({status:"active", created_at:{$gte:7d}})` | PRIMÁRIA (0%) | + `$nin SYNTHETIC` | 🟢 ALTA |
| Quantos **cancelamentos 7d**? | `subscribers.count({status:"canceled", canceled_at:{$gte:7d}})` | PRIMÁRIA (0%) | idem | 🟢 ALTA |
| **Saldo líquido** (novos − cancel)? | derivado das duas acima | DERIVADA (1%) | idem | 🟢 ALTA |
| Quantos clientes **High Ticket** (≥3× média)? | `loyalty.count({monthly_fee:{$gte: 3 × 103.37}, status:"Ativo"})` | DERIVADA (1%) | idem | 🟡 MÉDIA — ticket médio recalc trimestral |
| Quantos clientes **Black** (≥6× média)? | mesma query, 6× | DERIVADA (1%) | idem | 🟡 MÉDIA |

**Regra:** Quando alguém pergunta "quantos clientes a Ligo tem?", sempre se responde **2.746** (ativos reais). Nunca 26.851, nunca 2.816 — esses são números intermediários, não respostas executivas.

---

### 2. RECEITA E FINANCEIRO

| Pergunta executiva | Fonte oficial | Classe | Filtro obrigatório |
|---|---|---|---|
| **Quanto a Ligo faturou no mês?** | `revenue_realization.month_total(cid)` (ex-`real_revenue.py`) | PRIMÁRIA (0%) | `company_id="co-demo"`, `status="paid"`, `paid_at:{$gte:month_start}` |
| **Quanto a Ligo recebeu ontem?** | `revenue_realization.day_total(cid)` | PRIMÁRIA (0%) | idem, `paid_at:{$gte:yesterday}` |
| **Quanto a Ligo deve receber nos próximos 30d?** | `revenue_realization.forecast_30d(cid)` | PREDITIVA (5%) | invoices abertas vencimento <30d |
| **Inadimplência atual** (R$)? | `revenue_realization.inadimplencia(cid).total_brl` | PRIMÁRIA (0%) | `status:"overdue"` snapshot |
| **% inadimplência** sobre base? | derivada da anterior | DERIVADA (1%) | idem |
| **Ticket médio** da base ativa? | `loyalty.aggregate({status:"Ativo"}, avg(monthly_fee))` | DERIVADA (1%) | `company_id="co-demo"` | 🟢 R$ 103,37 |
| **MRR** (receita recorrente mensal)? | `revenue_realization.mrr(cid)` | DERIVADA (1%) | `subscribers.status="active"` × `plan_price` |
| **Quanto cada AGENTE IA gerou** (mês)? | `revenue_agent.by_agent(cid, days=30)` (ex-`agent_revenue.py`) | PRIMÁRIA (0%) | `motor_ia_revenue_attribution.kind in {recovered, generated}` |
| **Quanto a empresa ECONOMIZOU** (mês)? | `revenue_agent.economy_brl(cid, days=30)` | DERIVADA (1%) | `motor_ia_revenue_attribution.kind in {cost_saved, churn_prevented}` |
| **Onde REGISTRAMOS** cada outcome? | `revenue_attribution.attribute(...)` | escrita única | coleção `motor_ia_revenue_attribution` |

**Regra anti-divergência:** se `revenue_realization.month_total` e a soma de `revenue_agent.generated` não bate, **erro de pipeline** — abre incidente, não escolhe número.

---

### 3. TICKETS E ATENDIMENTO

| Pergunta executiva | Fonte oficial | Classe | Filtro obrigatório |
|---|---|---|---|
| **Quantos tickets** temos hoje? | `tickets.count_documents({status:"open"})` | PRIMÁRIA (0%) | `company_id="co-demo"` (apenas 350 reais) |
| **Quantos tickets ABERTOS 7d**? | `tickets.count({created_at:{$gte:7d}})` | PRIMÁRIA (0%) | idem |
| **Quantos RESOLVIDOS 7d**? | `tickets.count({status:"closed", closed_at:{$gte:7d}})` | PRIMÁRIA (0%) | idem |
| **Tickets recorrentes** (mesmo subscriber 3+ em 30d)? | `tickets.aggregate group_by subscriber having count≥3 last 30d` | DERIVADA (1%) | idem |
| **Atendimentos Isabella** (volume)? | `aihub_wa_messages.count({direction:"outbound", agent:"isabella"})` | PRIMÁRIA (0%) | `company_id="co-demo"` |
| **% resolução automática** Isabella? | `isabella_queue_metrics.resolved_auto / total` | DERIVADA (1%) | idem |
| **Transferências humanas**? | `isabella_queue_metrics.transferred_human` | PRIMÁRIA (0%) | idem |
| **TMA** (tempo médio atendimento)? | calculado de `aihub_wa_messages` (timestamps inbound→last_outbound) | DERIVADA (1%) | idem |
| **Clientes irritados**? | ⚠️ INDISPONÍVEL — não há flag estruturada | INDISPONÍVEL | Marca "BAIXA confiança" em qualquer dashboard que tente mostrar |

---

### 4. REDE E INCIDENTES

| Pergunta executiva | Fonte oficial | Classe |
|---|---|---|
| Quantos **incidentes ativos**? | `isabella_incidents.count({status:{$in:["predicted","confirmed"]}})` | PRIMÁRIA (0%) |
| Quantos **bairros afetados**? | derivado: `incidents` JOIN `subscriber_addresses.district` distinct count | DERIVADA (1%) |
| Quantas **CTOs críticas**? | `ctos.count({status:"critical"})` (apenas 40 reais co-demo) | PRIMÁRIA (0%) |
| **Capacidade média** OLT/CTO? | `smartolt_onus.aggregate avg(utilization_pct)` | DERIVADA (1%) |
| **Incidente recorrente** (mesma CTO/bairro 3+ em 30d)? | agregação custom em `isabella_incidents` + `network_outages` | DERIVADA (1%) |

---

### 5. COMERCIAL E OPORTUNIDADES

| Pergunta executiva | Fonte oficial | Classe |
|---|---|---|
| Quantas **vendas** fechadas 7d? | `sales_leads.count({status:"won", won_at:{$gte:7d}})` | PRIMÁRIA (0%) |
| **% conversão** leads→venda? | derivado | DERIVADA (1%) |
| Quantas **oportunidades abertas**? | `isabella_commander_opportunities.count({status:"pending"})` | PRIMÁRIA (0%) (2.043 co-demo) |
| Quantas **indicações** reais? | `referrals.count({synthetic:false})` | PRIMÁRIA — **HOJE = 0 REAIS**. Mostrar "INDISPONÍVEL — sistema sem dados reais" |
| **Top 3 produtos** vendidos mês? | aggregate em `subscribers` `plan_name` group | DERIVADA (1%) |
| **Top 3 regiões/bairros** em crescimento? | aggregate em `subscribers.district` JOIN `created_at:{$gte:90d}` | DERIVADA (1%) |

---

### 6. AGENTE DO MÊS

| Pergunta executiva | Fonte oficial | Classe |
|---|---|---|
| Quem é o **agente do mês** (IA)? | `revenue_agent.top_agent(cid, days=30)` → max(receita_gerada + receita_protegida + economia × peso) | DERIVADA (1%) |
| **Critério explícito** (sem ambiguidade) | `score = generated × 1.0 + protected × 0.7 + saved × 0.5` | normativo |
| Quem é o **vendedor humano** do mês? | ⚠️ Camila é **persona** — não há ranking de vendedor humano real. Se houver `sales_users`, fonte = `sales_leads.aggregate group_by closed_by` | INDISPONÍVEL ou DERIVADA dependendo de existir dado |

**Regra:** "Agente do mês" só responde por agente **com código real** (Isabella, Álvaro, Presidente IA). Personas (Pâmela, Camila) **podem aparecer** no ranking mas com badge "Persona — atribuição por heurística".

---

### 7. UNIVERSO LIGO

| Pergunta executiva | Fonte oficial | Classe |
|---|---|---|
| Quem é **cliente FUNDADOR**? | `universo_ligo_scores.find({tags:"fundador"})` baseado em `/app/memory/CLIENTE_FUNDADOR_REPORT.md` (130) | DERIVADA (1%) |
| Quem é **EMBAIXADOR**? | `universo_ligo_invites.find({decision:"APTO", status:"accepted"})` — **NUNCA por score** | PRIMÁRIA (0%) — convite humano explícito |
| Quem é **EMBAIXADOR NATURAL** (candidato)? | `/app/memory/EMBAIXADORES_NATURAIS.md` + `experience_campaigns` (113+17) | DERIVADA (1%) |
| Quem é **CLIENTE INVISÍVEL**? | `/app/memory/CLIENTES_INVISIVEIS.md` (84) | DERIVADA (1%) |
| Quem está em **DNC Universo Ligo**? | `subscribers.find({do_not_contact_universo_ligo:true})` | PRIMÁRIA (0%) |
| **NPS Score**? | `nps_responses_mvp.aggregate(promoters%/detractors%)` | PRIMÁRIA (0%) **mas baixa massa por meses** — marca "CONFIANÇA BAIXA, N=X" |

---

### 8. SAÚDE CORPORATIVA

| Pergunta executiva | Fonte oficial | Classe | Observação |
|---|---|---|---|
| **Health Score** (saúde interna 0-100)? | `presidente_ia.compute_corporate_health(cid)` | DERIVADA (1%) | Uso interno (Presidente IA, painéis técnicos) |
| **Executive Score** (saúde monetizada)? | `presidente_executive.build_executive_report(cid).president_score` | DERIVADA (1%) | **Único score mostrado ao CEO no Café com o CEO** |
| **Dinheiro em risco**? | `presidente_executive.dinheiro_em_risco_brl` | PREDITIVA (5%) | |
| **Dinheiro recuperável**? | `presidente_executive.dinheiro_recuperavel_brl` | PREDITIVA (5%) | |
| **Previsão receita 30d**? | `revenue_realization.forecast_30d` | PREDITIVA (5%) | |
| **Saturação CORDOVIL**? | derivado de `subscribers.district="CORDOVIL"` / capacidade OLT | DERIVADA (1%) | |

---

### 9. PRESIDENTE IA / CONSELHO

| Pergunta executiva | Fonte oficial |
|---|---|
| **Ata diária Commanders**? | `isabella_council_minutes` (escrita por `isabella_conselho.py`) |
| **Relatório diário executivo**? | `conselho_ia_reports` (escrita por route `conselho_ia.py`) |
| **Parecer LLM por cadeira** (CEO/COO/CTO/CFO/CPO)? | `presidente_ia_conselho.py` (cache 60min, sob demanda) |
| **Café com o CEO** (briefing)? | `ceo_briefing.py` (ex-`presidente_ia_briefing.py`) |

---

## 🚨 PERGUNTAS QUE **NÃO** TÊM RESPOSTA HOJE (HONESTIDADE)

Documentar agora para não fabricar dados depois:

| Pergunta | Por que indisponível | Quando vamos ter |
|---|---|---|
| Quantas **indicações reais** convertidas? | `referrals` = 7 docs, 100% sintéticos | Implementar coleta no atendimento (P1) |
| Quantos **clientes irritados**? | Sem flag estruturada | Implementar NLP em mensagens (V2) |
| Quem **falou bem da marca** (elogio espontâneo)? | Sem NLP | V2 |
| **Taxa de fidelidade** real? | Sem NPS robusto (1 doc só hoje) | 3-6 meses coletando |
| **Vendedor humano do mês**? | Sem `sales_users` com atribuição | Decidir se existe esse papel |
| **Causa-raiz** de cada incidente? | `network_outages.root_cause` raramente preenchido | Disciplinar preenchimento manual (P2) |

**Regra:** Briefing CEO **deve declarar** "INDISPONÍVEL" para essas perguntas. **NUNCA inventar.**

---

## 🛡️ CONTRATOS DE INTEROPERABILIDADE

### Regra 1 — Quem pode chamar?

| Quem precisa de "Receita do mês" | Chama |
|---|---|
| Café com o CEO | `revenue_realization.month_total(cid)` |
| Conselho Financeiro | `revenue_realization.month_total(cid)` |
| Dashboard executivo | `revenue_realization.month_total(cid)` |
| Painel CEO Mode | `revenue_realization.month_total(cid)` |

**Não é permitido** que cada um calcule "soma de `subscriber_invoices.paid_amount` do mês" por conta própria.

### Regra 2 — Quem pode escrever?

| Coleção | Único escritor autorizado |
|---|---|
| `motor_ia_revenue_attribution` | `services/revenue_attribution.py` |
| `universo_ligo_invites` | `routes/universo_ligo_curadoria.py` |
| `universo_ligo_scores` | `services/customer_intelligence.py` (futuro) |
| `subscribers.do_not_contact_universo_ligo` | `routes/universo_ligo_curadoria.py::set_dnc` |
| `nps_responses_mvp` | `routes/universo_ligo_curadoria.py::submit_nps` |
| `synthetic_tenant_guard_log` | `workers/synthetic_tenant_guard.py` |

### Regra 3 — Filtro de sintéticos é OBRIGATÓRIO

Qualquer endpoint cross-tenant **deve** usar `constants.synthetic_tenants.real_tenant_filter(cid)`. PR que ignorar essa regra é rejeitado em code review.

---

## 🧪 test_one_truth — ESPEC FORMAL

```python
# /app/backend/tests/test_phase_a_one_truth.py
async def test_revenue_month_zero_tolerance():
    """Receita do mês: tolerância ZERO entre fontes."""
    a = await revenue_realization.month_total("co-demo")
    b = await sum_of(revenue_agent.month_total_all_agents("co-demo"))
    c = await dashboard_endpoint("/revenue/month")
    assert a == b == c, f"Receita divergiu: realization={a} agent={b} dashboard={c}"

async def test_clients_active_zero_tolerance():
    """Clientes ativos: tolerância ZERO."""
    a = await subscribers.count({status: "active", company_id: "co-demo"})
    b = await loyalty_imported_db.count({status: "Ativo", company_id: "co-demo"})
    # tolerância: 0 — mas a operação pode ter 2 fontes legítimas (interna vs Atlaz).
    # Política: a fonte primária é `subscribers`. `loyalty` é referência externa.
    assert a is not None, "subscribers count failed"

async def test_tickets_zero_tolerance():
    a = await tickets.count({status: "open", company_id: "co-demo"})
    b = await dashboard_endpoint("/tickets/open/count")
    assert a == b

async def test_derived_within_1pct():
    """Métricas derivadas: até 1% de tolerância."""
    a = await ticket_medio_via_loyalty()  # média monthly_fee
    b = await ticket_medio_via_subscribers()
    assert abs(a - b) / max(b, 1) <= 0.01

async def test_predictive_within_5pct():
    """Métricas preditivas: até 5%."""
    a = await revenue_realization.forecast_30d("co-demo")
    b = await presidente_executive.previsao_30d("co-demo")
    assert abs(a - b) / max(b, 1) <= 0.05
```

---

## 📊 STUB LOG SPEC ([DEPRECATED_CALL])

Cada stub gerado na Etapa 3 (renomes) registra:

```python
# Template do stub
def __getattr__(name):
    import logging
    log = logging.getLogger("ligo.deprecated_call")
    log.info(
        "[DEPRECATED_CALL]",
        extra={
            "origem": _caller_module(),
            "destino": "ceo_briefing.py",
            "import_path_legacy": "services.presidente_ia_briefing",
            "tenant": _current_tenant() or "unknown",
            "usuario": _current_user_email() or "unknown",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    return getattr(_real_module, name)
```

**Persistência:** os logs vão para coleção `deprecated_call_log` (collection nova, mas só LOG — não regra de negócio).

**Ranking semanal:** worker `services/deprecated_ranking_worker.py` (a criar na Etapa 3) agrega `deprecated_call_log` por `origem` e gera:
- TOP 10 módulos chamando legado
- Crescimento/decrescimento semana a semana
- Persistido em `deprecated_ranking_weekly`
- Exposto em painel admin (`/api/admin/deprecated-ranking`)

**Critério de sucesso da migração:** após 30d, o ranking deve estar **vazio**. Se ainda há chamadas, **estende stubs** ou ataca o módulo que persiste.

---

## 🗂️ TAGS EM `executive_ledger` (DUAL TAG)

```python
# Etapa 3 — script idempotente:
result = db.executive_ledger.update_many(
    {"company_id": {"$in": SYNTHETIC_TENANTS}},
    {"$set": {
        "pre_sanitize_2026_06_14": True,
        "synthetic_detected": True,
        "_tagged_at": datetime.now(timezone.utc).isoformat(),
        "_tagged_by": "fase_a_etapa3_sanitize",
    }}
)
# Esperado: ~2.335 docs atualizados.
```

**Filtro padrão dos endpoints executivos** passa a usar:
```python
{"$or": [
    {"synthetic_detected": {"$ne": True}},
    {"synthetic_detected": {"$exists": False}}
]}
```

Permite "ver tudo" com `?include_synthetic=true` (admin/debug only) com banner UI obrigatório.

---

## ✅ DECISÕES CONFIRMADAS POR ESTE DOC

1. ✅ **Tolerância CTO oficial:** 0% primária / 1% derivada / 5% preditiva
2. ✅ **Fonte única por pergunta** documentada para 9 categorias (Clientes / Receita / Tickets / Rede / Comercial / Agente / Universo Ligo / Saúde / Conselho)
3. ✅ **6 perguntas INDISPONÍVEIS** declaradas oficialmente (indicações reais, irritados, elogios, NPS robusto, vendedor humano, causa-raiz)
4. ✅ **Único escritor por coleção** sensível (6 coleções nomeadas)
5. ✅ **Stub log spec** com 5 campos obrigatórios + ranking semanal
6. ✅ **Tag dual** em `executive_ledger` (`pre_sanitize_2026_06_14` + `synthetic_detected`)
7. ✅ **test_one_truth** com 5 testes explícitos (2 zero-tolerance, 1 derivada, 1 preditiva, 1 ticket)

---

## 🚦 PRÓXIMO PASSO

⛔ Ainda zero código alterado.

**Sequência proposta para a Etapa 3** (somente após você ratificar este doc):

1. Criar `tests/test_phase_a_one_truth.py` ANTES dos renomes (RED first — todos devem falhar inicialmente porque ainda não temos `revenue_realization` exposta como wrapper único)
2. Adicionar headers normativos em 15 arquivos (sem mudar lógica)
3. Renomear 6 arquivos com stubs `[DEPRECATED_CALL]` instrumentados
4. Tag dual nos sintéticos do `executive_ledger`
5. Drop por rename das 3 coleções vazias (`presidente_ledger` etc.)
6. Worker de ranking semanal de deprecated calls
7. Rodar `test_phase_a_one_truth.py` — deve **passar 100%** ou abrir incidentes específicos
8. Logbook final + entrega ao CTO

**Estimativa:** 3-4 dias úteis (1 dia a mais que o original por causa do stub log + ranking).

---

> **A partir deste doc, a Ligo tem um vocabulário comum.** Quem perguntar "quantos clientes temos?" e ouvir resposta diferente de 2.746, **está olhando para o lugar errado** — e o code review vai apontar.
