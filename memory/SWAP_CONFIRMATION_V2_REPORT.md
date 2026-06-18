# P1 V2.0 — Ciclo Fechado de Confirmação Patrimonial
**CEO order**: 18/06/2026 · **Status**: ✅ ENTREGUE · **Testes**: 63/63 PASS

---

## 🎯 Os 4 níveis do ciclo (todos implementados)

```
[Nível 1] Auto-detect Bug #6 → cria evento pending_confirmation
                ↓
[Nível 1] Gestor envia WhatsApp via Watchtower → sent_to_technician
                ↓ (4h sem resposta)
[Nível 2] Cron 30min → patrimonial_sla_tick → REMINDER (1x)
                ↓ (24h sem resposta)
[Nível 3] Cron 30min → patrimonial_sla_tick → status=overdue_confirmation
                ↓                                   + notifica gestores
                ↓
[Nível 4] Compliance Score 0-100 por técnico (30d janela)
          KPI executivo + ranking pior→melhor
```

---

## 🛠️ Implementação

### Nível 2 — Lembrete 4h (`services/patrimonial_confirmation_worker.py`)
- **Quando**: `sent_to_technician` AND `confirmation_sent_at <= now - 4h` AND `reminder_count = 0`.
- **O que faz**: reenvia WhatsApp via Baileys 1x única com texto "⏰ Lembrete · Confirmação Patrimonial Pendente" + 3 links HMAC.
- **Idempotência**: `reminder_count=1` impede segundo envio.
- **Audit**: `reminder_sent_at` + `reminder_last_error`.
- **Não dispara** quando já passou 24h (evento vai direto pra escalonamento).

### Nível 3 — Escalonamento 24h
- **Quando**: `sent_to_technician` AND `confirmation_sent_at <= now - 24h`.
- **O que faz**:
  - `status → overdue_confirmation` (`escalated_at`, `escalation_reason="no_response_24h"`).
  - Cria 1 notification por gestor (`type=patrimonial_confirmation_overdue`, severity=warning, com link ao evento).
- **Watchtower**: banner vermelho destacado quando `breakdown.overdue_confirmation > 0`.

### Nível 4 — Compliance Score
**Pontuação por evento decidido**:
| Cenário                                      | Pontos |
|-----------------------------------------------|-------:|
| Resposta CONFIRMADO em <4h (sem precisar lembrete) | **100** |
| Resposta CONFIRMADO em 4-24h (após lembrete)      |  60 |
| Resposta DISPUTED ou NEEDS_REVIEW (transparência) |  85 |
| OVERDUE_CONFIRMATION (sem resposta em 24h)        |   0 |
| pending/sent (sem decisão ainda)                  | não pontua |

**Score do técnico** = média ponderada dos eventos decididos nos últimos 30d.
**Ranking** = ordenado por pior score primeiro (ação prioritária).

### Cron registrado
`server.py` linha ~888: `patrimonial_sla_tick` roda a cada 30min (`scheduler.add_job`).

### Endpoints novos
- `GET /api/swap-confirmation/compliance?days=30` — payload com overall + ranking.
- `POST /api/swap-confirmation/sla-tick` — manual trigger (admin only, para testes).

### Watchtower atualizado
- Card "Trocas de ONT · ciclo de confirmação" agora inclui:
  - 5 KPIs de status existentes + **banner vermelho** quando `overdue_confirmation > 0`.
- **Novo card "Compliance Patrimonial"** (`data-testid=diagnostico-card-compliance`):
  - Score geral grande (cor: verde >=90, amarelo >=70, vermelho <70).
  - 4 KPIs: Eventos totais · Decididos · No prazo (<4h) · Tempo médio (min).
  - Ranking top 5 piores técnicos com nome + total/decididos/overdue + score colorido.
- Backend retorna agora `patrimonial_kpis` no payload diagnostico.

---

## ✅ Testes (9 novos V2.0 + 54 anteriores = 63 total verdes)

```
tests/test_swap_sla_v2.py:
  ✓ test_reminder_fires_after_4h_only_once
  ✓ test_reminder_not_fired_before_4h
  ✓ test_escalation_fires_after_24h
  ✓ test_escalation_idempotent
  ✓ test_compliance_on_time_scores_100
  ✓ test_compliance_late_response_scores_60
  ✓ test_compliance_overdue_scores_0
  ✓ test_compliance_ranking_orders_worst_first
  ✓ test_worker_logs_run_in_collection
```

Regressão: 54/54 (Onda A + B + C + RCA Fibra + Swap Confirmation P1 v1) — zero quebra.

---

## 🛡️ Regras de ouro mantidas

| Regra | Status | Evidência |
|-------|--------|-----------|
| Auditoria append-only em `auto_ont_swap_confirmations` | ✅ | sem deletes |
| Nunca toca estoque | ✅ | testes prévios validam `count_documents` pré/pós; worker novo só lê/escreve em `auto_ont_swap_events` + `notifications` + `patrimonial_sla_runs` |
| Token HMAC determinístico (reutilizado no lembrete) | ✅ | `_hmac_token` |
| Run log em `patrimonial_sla_runs` | ✅ | observabilidade total |
| Worker idempotente | ✅ | `reminder_count` + status check |
| Notificação por gestor (não broadcast geral) | ✅ | `db.users.find({role: gestor|administrador})` por company |

---

## 📊 Métricas atuais (snapshot)

| Métrica | Valor |
|---------|------:|
| Trocas Detectadas (Bug #6, 30d) | 0 |
| Trocas Confirmadas | 0 |
| Trocas Contestadas | 0 |
| Trocas em Revisão | 0 |
| Trocas em Atraso (overdue) | 0 |
| Tempo Médio de Confirmação | — |
| Compliance Patrimonial Geral | — |

**Sistema pronto pra absorver tráfego real**. A medida que técnicos forem trocando ONTs, o worker SLA mantém o ciclo fechado automaticamente.

---

## 🚀 Integração com Sprint 5.1 (Auto Balanço Patrimonial) — registrado

Adicionar no schema `inventory_monthly_balance` o grupo **CONFIABILIDADE PATRIMONIAL**:

```python
{
  "confiabilidade_patrimonial": {
    "swaps_detected": int,
    "swaps_confirmed": int,
    "swaps_disputed": int,
    "swaps_needs_review": int,
    "swaps_overdue": int,
    "response_rate_pct": float,  # confirmed+disputed+review / detected
    "techs_without_response_count": int,
    "ranking_compliance": [{tech_id, name, score}, ...]
  }
}
```

A função `compute_compliance_score()` já está pronta — Sprint 5.1 só precisa chamar com `days=30` apontando para o mês fechado.

---

## 📁 Files

### Novos
- `/app/backend/services/patrimonial_confirmation_worker.py` (235 linhas — worker SLA + Compliance Score)
- `/app/backend/tests/test_swap_sla_v2.py` (9 testes)
- `/app/memory/SWAP_CONFIRMATION_V2_REPORT.md` (este documento)

### Modificados
- `/app/backend/routes/swap_confirmation.py` — 2 endpoints novos (`compliance` + `sla-tick` admin)
- `/app/backend/routes/watchtower_estoque_diagnostico.py` — `_agg_patrimonial_kpis`, `overdue_confirmation` em pending_states/breakdown
- `/app/backend/server.py` — cron 30min `patrimonial_sla_30m`
- `/app/frontend/src/WatchtowerEstoqueDiagnostico.jsx` — banner overdue + card Compliance Patrimonial

---

## 🎯 Próximos passos (ordem oficial)

- **P2** — Watchtower Patrimônio Consolidado + Export CSV em PayersComponents + seed E2E completo (stok_stock + smartolt + cto) para FLUXO 2 success path.
- **Sprint 5** — Owner & Location Normalization (estrutural).
- **Sprint 5.1** — Auto Balanço Patrimonial (snapshot mensal com grupo CONFIABILIDADE PATRIMONIAL integrado).
- HOLD 7-14d (já alinhado): refactor `lousa.py` (9.224 linhas) + `whatsapp_baileys.py` (>5.400 linhas).
