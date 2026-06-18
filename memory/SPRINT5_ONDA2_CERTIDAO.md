# SPRINT 5 · ONDA 2 — CERTIDÃO DE SWAP EVENTS REAIS

**Empresa**: `co-demo` · **Executado**: 2026-02-19 22:24 UTC
**Mandato**: ORDEM EXECUTIVA CEO 19/02/2026
**Wave**: Sprint 5 Onda 2 — Swap Events Reais
**Status**: ✅ **CONCLUÍDO** · 5/5 gates oficiais atingidos · gate_overall = true

## 1. OBJETIVO

Criar a trilha oficial de troca patrimonial. Cada ONU deve responder
(sem consultar descrição textual):

* Qual ONU saiu? · Qual ONU entrou?
* Quem realizou a troca? (collaborator_id)
* Em qual OS? (ticket_id + service_id)
* Em qual cliente? (subscriber_id)
* Em qual CTO? Em qual porta? *(parcial — depende da Onda 3)*
* Em qual data? (created_at)
* Qual motivo? (swap_reason)
* Quem confirmou? (confirmed_by_user_id)

## 2. COLLECTION OFICIAL: `auto_ont_swap_events`

Campos persistidos (schema_version=sprint5_onda2):
event_id · event_type · company_id · ticket_id · service_id ·
subscriber_id · collaborator_id · cto_id · port_number · ont_old_sn ·
ont_old_mac · ont_new_sn · ont_new_mac · swap_reason · created_at ·
created_by · audit_hash (SHA-256) · confirmation_status ·
confirmation_at · smartolt_snapshot · stok_history_id

## 3. RESULTADO DO BACKFILL RETROATIVO

| Métrica | Valor |
|---------|------:|
| Universo (stok_history com OS finalizadas) | 87 |
| Swap_events criados | 87 |
| Cobertura vs Expected | **100.00%** |
| Eventos eligible (não-irrecuperáveis) | 51 |
| Eventos irrecuperáveis (fonte destruída) | 36 |

### Distribuição por event_type
| Tipo | Qtd |
|------|----:|
| install | 33 |
| swap (reparo com troca) | 36 |
| removal (retirada) | 18 |

## 4. GATES OFICIAIS (CEO 19/02/2026)

| Gate | Meta | Atingido | Status |
|------|-----:|---------:|:------:|
| Cobertura swap vs expected | ≥95% | **100.00%** | ✅ |
| Ticket linkage (eligible) | ≥95% | **100.00%** | ✅ |
| Subscriber linkage | ≥95% | **100.00%** | ✅ |
| Collaborator linkage | ≥95% | **100.00%** | ✅ |
| Estoque linkage (`stok_history_id`) | ≥95% | **100.00%** | ✅ |
| SmartOLT linkage | ≥95% | **100.00%** | ✅ |
| **GATE OVERALL** | — | **TRUE** | ✅ |

## 5. CASOS IRRECUPERÁVEIS (não contam no gate — fonte destruída)

| Categoria | Qtd | Motivo |
|-----------|----:|--------|
| `terminal_source_destroyed` | 20 | `stok_services` removido — não há svc nem ticket pra recuperar |
| `no_ticket_in_source` | 16 | `stok_services` existe mas nasceu sem ticket_id (auto_opened legado) |

**Justificativa técnica**: a Onda 2 não pode reconstruir dados que JÁ
não existem na fonte. Esses 36 docs ficam preservados (Golden Rule:
zero deletes) com `data_quality` marcado e `irrecoverable=true`,
servindo para auditoria histórica mas excluídos do cálculo do gate.

## 6. CROSS-LINK BIDIRECIONAL (Estoque ↔ Swap ↔ Ticket ↔ Subscriber)

Cada swap_event contém:
- `stok_history_id` → aponta para o evento de estoque
- `ticket_id` → aponta para o ticket
- `subscriber_id` → aponta para o cliente
- `collaborator_id` → aponta para o técnico

Cada `stok_history` correspondente recebe:
- `swap_event_id` (cross-link reverso)
- `swap_event_audit_hash` (integridade)

## 7. AUDIT HASH SHA-256

Cada swap_event tem `audit_hash` calculado deterministicamente sobre
os 14 campos canônicos. Qualquer alteração posterior é detectável.

## 8. CONFIRMATION STATES (CEO list — não criar novos)

`pending_confirmation` · `sent_to_technician` · `confirmed` ·
`disputed` · `needs_review` · `overdue_confirmation`

Distribuição atual:
- pending_confirmation: 86
- confirmed: 1 (teste manual via endpoint)

## 9. INTEGRAÇÃO SMARTOLT

Captura snapshot best-effort de cada swap (ONU old + ONU new) na
collection `smartolt_onus`. Snapshots em todos os 51 eligible (100%).

## 10. INTEGRAÇÃO LOUSA AUTO-FINALIZE

`/app/backend/routes/stok.py::auto_close_service_from_ticket` agora
emite `swap_event` automaticamente ao fechar a OS. Toda nova OS
finalizada gera trilha completa **automaticamente** — sem dependência
de backfill futuro.

## 11. ENDPOINTS REST

| Rota | Método | Acesso |
|------|:------:|:------:|
| `/api/sprint5/swap-events/status` | GET | admin/gestor/auditor |
| `/api/sprint5/swap-events/preview-backfill` | GET | admin/gestor/auditor |
| `/api/sprint5/swap-events/backfill-from-history` | POST | admin/gestor |
| `/api/sprint5/swap-events/metrics-operational` | GET | admin/gestor/auditor |
| `/api/sprint5/swap-events/{id}/confirm` | POST | admin/gestor/tec/auditor |
| `/api/sprint5/swap-events/{id}/dispute` | POST | admin/gestor/tec/auditor |
| `/api/sprint5/swap-events/audit-log` | GET | admin/gestor/auditor |
| `/api/sprint5/swap-events/certidao` | GET | admin/gestor/auditor |

Super admin bypass ativo.

## 12. WATCHTOWER (sem novo dashboard)

Endpoint `/metrics-operational` expõe os números pedidos pelo CEO:
* swaps_today, swaps_month, swaps_confirmed_total,
  swaps_disputed_total, swaps_pending_total, swaps_overdue_total.

Para consumo de telas já existentes — **nenhum dashboard novo
foi criado**, em respeito à regra de ouro.

## 13. IDEMPOTÊNCIA

- 1ª execução: 87 candidates → 87 criados.
- 2ª execução: 0 candidates → 0 criados.
- Confirmado idempotente.

## 14. PRÓXIMA ONDA

**Onda 3** — CTO + Porta obrigatórios no completion_data da Lousa.
Vai elevar `cto_linkage_pct` e `port_linkage_pct` (hoje 1.96% e 0%
no eligible) — esses **não eram gates da Onda 2** conforme a ordem
do CEO; são gates da Onda 3.

---

**Certidão emitida automaticamente** por
`/api/sprint5/swap-events/certidao` em 2026-02-19 22:24 UTC.
Último batch aplicado: `o2sb-e94eec80d8ea47`.
