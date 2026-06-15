# 🧠 CEO DIGITAL — Plano de Implantação (Executive Memory + CEO_BRIEFING_08H)

> Princípio: **zero coleção nova · zero KPI duplicado · zero dashboard novo**. Reuso máximo.

## 1. Arquitetura (3 camadas existentes · 1 nova mínima)

```
ONE TRUTH (fontes oficiais já definidas em ONE_TRUTH_MATRIX.md)
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│  services/executive_memory.py  ◀── ÚNICO ARQUIVO NOVO   │
│  - snapshot_today(cid)         (consolida ONE TRUTH)    │
│  - compare(cid)                (vs ontem/7d/30d/ano)    │
│  - detect_signals(cid)         (riscos + oportunidades) │
└─────────────────────────────────────────────────────────┘
        │                                       │
        ▼                                       ▼
  president_daily               services/ceo_briefing.py
  (REUSO · já existe;            (REUSO · expandido para
   adiciona 4 campos)             usar comparações + metas)
        │
        ▼
  conselho_ia_scheduler._worker_loop  (REUSO · cron já gira)
        │
        ▼
  POST /api/ceo/briefing/now      ← ChatGPT consome ISTO
  GET  /api/ceo/memory?days=30    ← E ISTO. Mais nada.
```

## 2. Mapa de reuso (zero retrabalho)

| Componente | Status | Decisão |
|---|---|---|
| `services/ceo_briefing.py · build_briefing_text` | existe (Etapa 3) | **REUSO** — adicionar bloco "comparações" + "decisão sugerida" |
| `services/conselho_ia_scheduler · _worker_loop + _maybe_send_presidente_briefing` | existe · cron horário UTC | **REUSO** — só setar `cron_hour_utc=11` (= 08h BR) e `presidente_briefing_enabled=true` em `conselho_ia_settings` |
| Coleção `president_daily` | 1 doc em co-demo (09/06) com `mapa_executivo`, `roi_30d`, `metas`, `narrativa`, `saude` | **REUSO como `executive_memory`** — só adicionar 4 campos: `clientes_ativos`, `mrr`, `inadimplencia_brl`, `tickets_abertos` (vindos do ONE TRUTH) |
| `services/presidente_ia.compute_corporate_health/compute_risks/compute_opportunities` | existe | **REUSO** direto |
| `services/revenue_realization.month_total / inadimplencia / mrr` | existe | **REUSO** (fonte oficial ONE TRUTH) |
| `scripts/one_truth_audit.py` | existe | **REUSO** como ground truth do snapshot |
| `routes/presidente_ia.py` | existe (briefing endpoint via auth) | **EXPANDIR**: adicionar 2 endpoints CEO-only `/api/ceo/briefing/now` e `/api/ceo/memory` |
| `motor_ia_daily_briefings` / `executive_daily_closings` | existem | **NÃO TOCAR** — são insumos de IA por agente, não executivo. |

## 3. GAP real (o que falta, em ordem)

| # | Gap | Tamanho |
|---|---|---|
| G1 | snapshot diário consolidado a partir de ONE TRUTH (`clientes_ativos, mrr, inadimplencia, cancelamentos, novos_clientes, tickets_abertos, tickets_fechados, incidentes, isabella_vendas, isabella_retencoes, fundadores, embaixadores`) | 1 função ~80 LoC |
| G2 | comparações vs ontem / 7d / 30d / meta anual (delta + %) | 1 função ~60 LoC |
| G3 | detecção de **riscos e oportunidades** com base em deltas (top 3 + top 3) | 1 função ~70 LoC |
| G4 | bloco de METAS hardcoded (`{clientes:3500, mrr:450000}`) — versionado em `services/executive_memory.py:METAS_2026` | constante |
| G5 | endpoint API `/api/ceo/briefing/now` (≤500 palavras texto + payload estruturado) | route ~30 LoC |
| G6 | endpoint API `/api/ceo/memory?days=30` (array compacto) | route ~20 LoC |
| G7 | persistência idempotente em `president_daily` com chave `(company_id, date_key)` | `update_one(...upsert=True)` |
| G8 | bloco "decisão sugerida" no briefing (1 ação concreta com base em top-risk + top-opp) | já existe esqueleto · refinar prompt |

**Total estimado:** ~300 LoC em **1 arquivo novo** + 2 endpoints + 1 update em `ceo_briefing.py`.

## 4. Plano de implantação (3 PRs reversíveis)

### PR1 — `services/executive_memory.py` (read-only · backfill 30d)
- Cria o módulo com `snapshot_today`, `compare`, `detect_signals`, `METAS_2026`.
- Job idempotente que faz upsert em `president_daily` com chave `(company_id, date_key)`.
- **Backfill 30 dias** lendo o que já existe em `executive_ledger`, `subscriber_invoices.paid_date`, `tickets.created_at`, etc. para popular histórico mínimo.
- Reversível: `python3 scripts/executive_memory_rollback.py` remove apenas os campos `_em_added_by="ceo_digital_v1"`.

### PR2 — `ceo_briefing.py` expandido
- Acrescenta seções: **O QUE MELHOROU (top 5)** · **O QUE PIOROU (top 5)** · **RISCOS (top 3)** · **OPORTUNIDADES (top 3)** · **DECISÃO SUGERIDA**.
- Mantém ≤500 palavras (texto truncado se exceder).
- Reaproveita `compute_corporate_health/risks/opportunities` já existentes.

### PR3 — 2 endpoints CEO + cron 08h
- `POST /api/ceo/briefing/now` (`auth=CEO`) → roda `snapshot_today` + `build_briefing_text` + persiste.
- `GET /api/ceo/memory?days=30` → array compacto `[{date, clientes, mrr, ...}]` (zero PII bruta).
- Set `conselho_ia_settings.cron_hour_utc=11` + `presidente_briefing_enabled=true` (`co-demo` apenas, gated).
- Payload para ChatGPT: `{briefing, executive_memory_30d, metas}` — exatamente conforme ordem.

## 5. Estimativa de esforço

| PR | Tempo dev | Risco | Reversibilidade |
|---|---|---|---|
| PR1 (módulo + backfill) | 3h | baixo (read-only writes em coleção já existente, campo novo) | total |
| PR2 (briefing expandido) | 2h | baixo (substituição idempotente de texto) | total (git revert) |
| PR3 (endpoints + cron) | 2h | baixo (endpoints CEO-only, cron gated por flag) | total |
| **Total** | **~7h** | — | — |

## 6. Riscos

| # | Risco | Severidade | Mitigação |
|---|---|---|---|
| R1 | Backfill 30d puxar dados sintéticos | 🟢 baixo | filtro `$nin SYNTHETIC_TENANTS` em todas as queries do módulo |
| R2 | Briefing diário gerar custo de token alto via ChatGPT | 🟡 médio | payload limitado a `{briefing≤500w, memory_30d, metas}` ≈ 3-4k tokens · 1× / dia / CEO |
| R3 | Cron disparar duplicado se restart do scheduler | 🟢 baixo | chave `(company_id, date_key)` idempotente · upsert |
| R4 | `president_daily.metas` poderia conflitar com schema atual | 🟢 baixo | já tem campo `metas` (vide doc atual em co-demo) |
| R5 | Endpoint CEO sem auth correta | 🔴 alto | usar dependency `require_role("ceo")` já existente; testar 401/403 antes de publicar |

## 7. Rollback

```bash
# PR1
python3 scripts/executive_memory_rollback.py  # $unset campos _em_added_by
# PR2
git revert <commit-pr2>
# PR3
git revert <commit-pr3>
# desligar cron
db.conselho_ia_settings.update_one({"company_id":"co-demo"},
                                   {"$set":{"presidente_briefing_enabled":False}})
```

Nada físico é deletado. Nenhuma feature flag de Customer Intelligence/Isabella/Pamela é ligada.

## 8. Critério de aceite (auto-teste)

Se eu rodar `curl /api/ceo/briefing/now`, o CEO recebe em ≤30s:
- Estado da empresa (4 linhas)
- Top 5 melhoraram + Top 5 pioraram
- Top 3 riscos + Top 3 oportunidades
- 1 decisão sugerida
- Tudo em ≤500 palavras
- `executive_memory_30d` com 30 datas
- `metas` estáticas

Sem abrir dashboard. Sem consultar relatório. Sem interpretar gráfico.

---

## ⏳ AGUARDANDO `VOCÊ AUTORIZA?`

Próximo passo após autorização: implementar **PR1** primeiro (módulo + backfill em `president_daily`), validar com `curl` que o snapshot do dia bate com o `one_truth_audit`, depois PR2 e PR3.

**Nada será escrito em produção sem autorização.**
