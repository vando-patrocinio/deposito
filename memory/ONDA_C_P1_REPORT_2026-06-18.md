# ONDA C P1 — Watchtower Diagnóstico + Auditoria Praça x Técnico
**Data**: 18/06/2026 · **Status**: ✅ ENTREGUE · **Testes**: 33/33 PASS (7 novos + 26 regressão)

---

## 📊 Antes / Depois — Saúde da Lousa Mobile

### ❌ ANTES (pré-Onda C)

| Dimensão                        | Visibilidade       | Auditoria        | Ação operacional |
|---------------------------------|--------------------|------------------|-------------------|
| Falha na finalização de OS      | logs supervisor    | nenhuma          | grep manual       |
| Em qual das 6 fases falhou      | **invisível**      | **inexistente**  | impossível        |
| Latência do fluxo               | **desconhecida**   | nenhuma          | sem SLA           |
| late_close_worker rodou?        | tail -f log        | nenhuma          | sem confiança     |
| stok_reconcile_job rodou?       | tail -f log        | nenhuma          | sem confiança     |
| Troca de ONT sem registro       | **possível**       | **inexistente**  | vazamento patrim. |
| ONT swap pendente confirmação   | **invisível**      | **inexistente**  | impossível        |
| Saldos negativos / IDs misturados | manual grep      | **inexistente**  | só descobre quando quebra |

**Vazamento de patrimônio** = aceitável até que alguém reclamasse.

### ✅ DEPOIS (Onda C P1 entregue)

| Dimensão                        | Visibilidade                          | Auditoria                                       | Ação operacional        |
|---------------------------------|---------------------------------------|--------------------------------------------------|--------------------------|
| Falha na finalização de OS      | Card "Erros recentes" (top 20)        | `lousa_finalize_trace` (TTL 30d)                | clique → ticket          |
| Em qual das 6 fases falhou      | EKG 6-phase (success_rate + last_error) | mesma collection                                | filtra por fase          |
| Latência do fluxo               | **p50 / p95 / max** por janela        | derivado de trace                               | SLA mensurável          |
| late_close_worker rodou?        | Card "runs_7d + último run"           | `late_close_runs` (Onda B)                      | confiança 7d             |
| stok_reconcile_job rodou?       | Card "runs_7d + órfãs marcadas"       | `stok_reconcile_runs` (Onda B)                  | confiança 7d             |
| Troca de ONT sem registro       | **bloqueada** (Bug #6 auto-detect)    | `auto_ont_swap_events` (idempotente)            | confirmação obrigatória  |
| ONT swap pendente confirmação   | Card "Trocas pendentes" + top 5 técnicos | mesma collection                                | drill-down               |
| Saldos negativos / IDs misturados | `/app/memory/PRAÇA_TECNICO_AUDIT.md`  | snapshot read-only on-demand                     | review humano + Sprint 5 |

**Vazamento de patrimônio** = detectado em ≤24h, atribuído ao técnico, ação operacional clara.

---

## 🚀 Entregas

### 1) Watchtower Diagnóstico (sub-aba Lousa Mobile)
- **Backend novo**: `GET /api/watchtower/estoque/diagnostico?window_hours=1..168` (`routes/watchtower_estoque_diagnostico.py`).
  - 6 aggregations paralelas via `asyncio.gather` — read-only.
  - Confirmado **ZERO writes** (apenas `.find / .aggregate / .count_documents`).
  - Auth: `require_role('gestor','administrador','auditor')`.
- **Frontend novo**: `WatchtowerEstoqueDiagnostico.jsx` + tabs em `WatchtowerEstoque.jsx`.
  - 5 cards: 6-Phase EKG · ONT Swap Pendente · late_close · reconcile · erros recentes.
  - Janela ajustável (1h/6h/24h/72h/7d).
  - data-testids completos: `diagnostico-root`, `diagnostico-card-{phases,swap,late-close,reconcile,errors}`, `diagnostico-phase-{phase}-last-error`, `diagnostico-swap-tech-{id}`, etc.

### 2) Auditoria Praça x Técnico (read-only)
- **Script novo**: `/app/backend/scripts/audit_praca_tecnico.py`.
- **Saída**: `/app/memory/PRAÇA_TECNICO_AUDIT.md` (geração on-demand).
- **Mapeamento**: empresa → técnicos → praças → stocks → ONTs → services (ativos + órfãos).
- **Detecção de 7 categorias de inconsistência**:
  1. 🔴 Saldos negativos por consumível + location.
  2. 🟠 `stok_stock` documents duplicados na mesma location.
  3. 🚨 Praça MISTURADA com técnico (mesmo ID).
  4. 🟡 ONTs órfãs (location_id inexistente em collaborators/pracas).
  5. 🟠 Serviços ativos sem técnico atribuído.
  6. 🟡 ONTs defeituosas sem `defective_reason`.
  7. ⚪ `stok_services` órfãos remanescentes (status `orfa_sem_ticket`).
- **Modos**: default (`--company-id X`), `--print-only` (não escreve arquivo).
- **Garantia**: 0 writes confirmados pelo testing agent.

### 3) Alerta auto_ont_swap_events pending_confirmation
- Aprovado posicionar dentro do **Watchtower Diagnóstico** (não no IA Presidente — concordo: é operação de campo, não saúde de IA).
- Card amarelo destacado + total pendente + top 5 técnicos + últimos 10 eventos.

---

## ✅ Critérios CEO atendidos

| Critério                              | Status      | Evidência                                            |
|----------------------------------------|-------------|-------------------------------------------------------|
| P1 sem quebrar fluxo atual             | ✅          | 26/26 regressão Onda A+B+C verde                    |
| Nenhum delete                          | ✅          | Code review + testing agent confirmaram read-only   |
| Testes verdes                          | ✅          | 33/33 (7 novos + 26 regressão)                       |
| Relatório executivo antes/depois       | ✅          | Este documento                                        |

---

## Files
- `/app/backend/routes/watchtower_estoque_diagnostico.py` (NOVO · 310 linhas)
- `/app/backend/scripts/audit_praca_tecnico.py` (NOVO · 360 linhas)
- `/app/frontend/src/WatchtowerEstoqueDiagnostico.jsx` (NOVO · 358 linhas)
- `/app/frontend/src/WatchtowerEstoque.jsx` (modificado · tabs adicionadas)
- `/app/backend/server.py` (modificado · include_router)
- `/app/backend/tests/test_onda_c_p1_diagnostico.py` (NOVO · 7 testes pelo testing agent)
- `/app/memory/PRAÇA_TECNICO_AUDIT.md` (gerado on-demand)

## Code review crítico (P2 backlog)
- `_iso()` helper duplicado — extrair para `services/datetime_utils.py`.
- `audit_praca_tecnico.py` parser `.env` manual frágil se valor tiver `=` — trocar por `python-dotenv`.
- `WatchtowerEstoque.jsx` continua sem rotas próprias — Sprint 5 deve criar `/watchtower/estoque/{patrimonio|diagnostico}` no router para deep-link.

## Próximos (P1 continuação se necessário)
- Watchtower Patrimônio Consolidado (todas as praças num single view).
- Export CSV drill-down em `PayersComponents.jsx`.

## Sprint 5 (P1 futuro — estrutural)
- Owner & Location Normalization (mover IDs misturados para `owner_type/owner_id`).
- Reescrever `stok_stock` para schema canônico baseado no audit deste documento.
