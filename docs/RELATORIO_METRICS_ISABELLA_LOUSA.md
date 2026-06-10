# RELATÓRIO — OPERAÇÃO ISABELLA LOUSA METRICS

**Data:** 10/02/2026
**Política:** Read-only · Zero coleção nova · Zero IA nova · Zero dashboard novo

---

## 1. ARQUIVOS

### Criados
| Arquivo | LoC | Função |
|---|---|---|
| `backend/services/isabella_lousa_metrics.py` | 240 | Função `isabella_lousa_metrics(company_id, days)` — agrega os 18 KPIs |
| `backend/scripts/test_isabella_lousa_metrics.py` | 90 | Teste automatizado · 7 asserts |

### Alterados
| Arquivo | Mudança |
|---|---|
| `backend/routes/isabella_lousa.py` | Adicionado `GET /api/isabella-lousa/metrics?days=7` · permite admin/gestor/auditor |

---

## 2. ENDPOINT CRIADO

**`GET /api/isabella-lousa/metrics?days=N`**
- Auth: `require_roles("administrador", "gestor", "auditor")`
- Query param `days` (clamp 1-90, default 7)
- Read-only · sem persistir nada · seguro contra side-effects

Validado HTTP em co-demo (admin@empresa.com): **`http=200 time=0.180s`**.

---

## 3. QUERIES USADAS (todas em coleções existentes)

| Coleção | Filtros |
|---|---|
| `db.tickets` | `{origin: "isabella", created_at: {$gte: cutoff}, company_id}` — totais por status + top motivos + top técnicos via `$group` em `client_snapshot.relato` e `assigned_collaborator_id` |
| `db.ticket_logs` | `{action: /reagend/i}` para `os_reagendadas` |
| `db.ai_evaluations` | `kind=ISABELLA_WINDOW_PROPOSED` (proposta→confirmação) · `kind=OS_LEARNING` (1º contato) · `nps_inferido` (NPS médio) · `premium_repair.active` (premium count) |
| `db.truck_roll_decisions` | `$group _id=decision` (distribuição) |
| `db.collaborators` | join leve para nome do técnico |

---

## 4. PAYLOAD REAL — co-demo · days=30

```json
{
  "company_id": "co-demo",
  "window_days": 30,
  "computed_at": "2026-06-10T04:09:56+00:00",

  "total_os_isabella": 4,
  "os_agendadas": 1,
  "os_finalizadas": 3,
  "os_canceladas": 0,
  "os_reagendadas": 0,

  "tempo_medio_proposta_confirmacao_s": null,
  "tempo_medio_criacao_fechamento_s": 15.6,

  "taxa_primeiro_contato_resolvido_pct": 0.0,
  "taxa_reagendamento_pct": 0.0,

  "nps_medio_inferido": 5.9,
  "nps_samples": 36,
  "premium_repair_count": 33,

  "truck_roll_decisions": {
    "DO_NOT_DISPATCH": 0,
    "DISPATCH": 15,
    "ESCALATE_COLLECTIVE": 1,
    "PREVENTIVA": 0
  },

  "top_5_motivos_os": [
    {"motivo": "sem internet de novo", "count": 3},
    {"motivo": "sem internet ainda", "count": 1}
  ],
  "top_5_tecnicos_por_os_isabella": [
    {"collaborator_id": "col-mural-0-68a1de",
     "name": "Alpha Tech", "count": 4}
  ],

  "os_sem_followup": 0,
  "os_duplicadas_bloqueadas": 0,

  "economia_estimativa_brl": 80.0,
  "health_signals": {
    "first_contact_ok": 0.0,
    "reschedule_bad": 1.0,
    "nps_ok": 0.59,
    "followup_ok": 1.0
  },
  "status_geral": "AMARELO"
}
```

---

## 5. INTERPRETAÇÃO DO STATUS_GERAL

Fórmula: média de 4 sinais ponderados (escala 0-1):
- `first_contact_ok` = `taxa_primeiro_contato_resolvido / 100` (alvo: alto)
- `reschedule_bad` = `1 - taxa_reagendamento` (alvo: baixo reagendamento)
- `nps_ok` = `nps_medio / 10` (default 0.7 quando sem amostra)
- `followup_ok` = `1 - (os_sem_followup / total)`

Mapeamento:
| Média ≥ | Status |
|---|---|
| 0.70 | 🟢 **VERDE** — operação saudável |
| 0.45 | 🟡 **AMARELO** — atenção pontual |
| < 0.45 | 🔴 **VERMELHO** — intervenção imediata |

**No payload acima** (co-demo): média = (0 + 1 + 0.59 + 1)/4 = **0.65 → AMARELO**.

Diagnóstico desse `AMARELO`:
- `first_contact_ok = 0` → falta executar `register_os_learning` nas OS Isabella (não há `kind=OS_LEARNING` ainda para os tickets dela).
- `nps_ok = 0.59` → NPS 5.9 está abaixo do alvo (≥7 ideal).
- `reschedule_bad = 1` → 0 reagendamentos ✅.
- `followup_ok = 1` → 0 OS sem follow-up ✅.

Ação corretiva sugerida: agendar job `register_os_learning` para todos os tickets `origin=isabella` fechados, e revisar prompts que estão derrubando NPS.

---

## 6. TESTE AUTOMATIZADO — 7/7 ✅

`scripts/test_isabella_lousa_metrics.py` valida:
1. ✅ Todas as 18 chaves obrigatórias presentes
2. ✅ `truck_roll_decisions` tem `DO_NOT_DISPATCH` · `DISPATCH` · `ESCALATE_COLLECTIVE`
3. ✅ `status_geral` ∈ {VERDE, AMARELO, VERMELHO}
4. ✅ Coerência matemática (agendadas+finalizadas+canceladas ≤ total+reagendadas)
5. ✅ `top_5_*` são listas
6. ✅ `economia_estimativa_brl` é numérico
7. ✅ **Read-only** — `count_documents(origin=isabella)` igual antes/depois

---

## 7. CRITÉRIOS DE ACEITE — 8/8 ✅

| # | Critério | Status |
|---|---|---|
| 1 | endpoint HTTP 200 | ✅ `http=200 time=0.180s` |
| 2 | retorna dados reais | ✅ 4 OS Isabella · 36 NPS samples · 33 premium repairs |
| 3 | não quebra Lousa | ✅ read-only, contagem `db.tickets` igual antes/depois |
| 4 | não altera fluxo de criação de OS | ✅ não toca `tickets`/`smart_repairs`/`isabella_lousa_scheduler` |
| 5 | não altera Isabella | ✅ não toca `ai_orchestrator`/`whatsapp_twilio` |
| 6 | não altera Lousa Mobile | ✅ não toca `routes/lousa.py` nem cliente mobile |
| 7 | pelo menos 1 teste automatizado | ✅ 7 asserts em `test_isabella_lousa_metrics.py` |
| 8 | exemplo de payload real | ✅ seção 4 deste relatório |
