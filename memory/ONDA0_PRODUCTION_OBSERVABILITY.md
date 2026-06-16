# ONDA 0 — OBSERVABILIDADE DE PRODUÇÃO (Estoque Operacional SmartProv V2)

**Tipo:** Documento operacional + SLO.
**Data início:** 16/Fev/2026
**Janela de observação:** 7 dias corridos a partir do deploy de `auto_close_legacy_observability`.
**Decisão CEO:** Nenhum código legado é removido nesta fase. Apenas observabilidade, logs, flags, métricas e marcação `@deprecated`.

---

## §1. PATCHES APLICADOS NESTA ONDA

| Onda | Arquivo | Função | Status |
|------|---------|--------|--------|
| **0a** | `routes/lousa.py` | `finalize_ticket` (JWT privado) | ✅ Chokepoint ativo |
| **0d** | `routes/lousa.py` | `_revert_ticket_side_effects` (reopen) | ✅ Movimento reverso `ticket_reopen_revert` gravado antes de mutar `stok_onts` |
| **0b** | `routes/stok.py` | `auto_close_service_from_ticket` | ✅ Observabilidade ativa; legado NÃO removido |

Novo `movement_type` registrado na whitelist canônica (`services/inventory_movements.py`):
- `ticket_reopen_revert` — emitido sempre que `_revert_ticket_side_effects` reverte `stok_onts`.

---

## §2. FLAG DE AMBIENTE

```bash
AUTO_CLOSE_LEGACY_DEPRECATED=true   # default ON
```

Quando `true`, toda chamada a `auto_close_service_from_ticket(...)` grava 1 doc em
`db.auto_close_legacy_observability` com:

| Campo | Significado |
|-------|-------------|
| `ticket_id` | Ticket que disparou |
| `company_id` | Empresa |
| `caller` | Origem da chamada (rota Python) — ver §3 |
| `technician_id` / `technician_name` | Técnico passado pelo caller |
| `completion_data_keys` | Chaves presentes (até 50, ordenadas) |
| `has_ont` / `has_ont_sn` | Indicadores de movimento físico |
| `called_at` | Timestamp ISO UTC |

Para desligar a observabilidade (não recomendado durante a janela): `AUTO_CLOSE_LEGACY_DEPRECATED=false`.

---

## §3. MAPA DE CALLERS CONHECIDOS (após este deploy)

| Caller string | Onde está | Tipo de OS | Frequência esperada (30d) |
|---------------|-----------|------------|---------------------------|
| `lousa.public_finalize_ticket` | `routes/lousa.py` (PWA público técnico) | Todas físicas | ~120/30d |
| `lousa.admin_close_ticket.retirada` | `routes/lousa.py` (gestor admin-close) | Retirada | ~3/30d |
| `lousa.admin_close_ticket.instalacao_troca` | `routes/lousa.py` (gestor admin-close) | Instalação/Troca | ~2/30d |
| `stok.retry_erro_estoque` | `routes/stok.py` (retry endpoint) | Reprocessamento | Esporádico |
| `unknown` | Qualquer outro caller não-instrumentado | Auditar! | **Deve ser 0** |

> Se aparecer `caller=unknown` na collection, **temos chamador escondido**. Investigar imediatamente.

---

## §4. MÉTRICAS DA JANELA DE 7 DIAS

| # | Métrica | Meta | Como medir |
|---|---------|------|------------|
| 1 | Finalizações OS (`outcome=sucesso`) | 100% auditadas | `tickets.count({"status":"finalizada","outcome":"sucesso","os_inventory_guardrail":{"$exists":true}})` / `tickets.count({"status":"finalizada","outcome":"sucesso","closed_at":{"$gte":patch_date}})` = `1.0` |
| 2 | Reaberturas (`reopen`) | 100% auditadas | `inventory_os_movements_audit.count({"movement_type":"ticket_reopen_revert"})` ≥ `tickets.count({"reopened_at":{"$gte":patch_date}, "type":{"$in":["instalacao","troca","retirada"]}})` |
| 3 | Movimentos pelo helper canônico | 100% | `inventory_os_movements_audit.count({"audit_hash":{"$exists":true}, "created_at":{"$gte":patch_date}})` deve crescer ≥ ritmo histórico |
| 4 | Ranking de chamadas ao legado | Distribuição esperada (§3) | `auto_close_legacy_observability.aggregate([{$group:{_id:"$caller", n:{$sum:1}}}])` |
| 5 | Tickets sem trilha | `0` | `tickets.count({"status":"finalizada","outcome":"sucesso","closed_at":{"$gte":patch_date},"os_inventory_guardrail":{"$exists":false}})` |
| 6 | Tempo médio de finalização | ≤ baseline +10% | `avg(closed_at - opened_at)` antes/depois do patch |

### Query de painel (mongo shell)

```javascript
// 1) Cobertura do guardrail
const patch = new Date("2026-02-16T00:00:00Z");
const total = db.tickets.count({ status:"finalizada", outcome:"sucesso", closed_at:{$gte: patch.toISOString()} });
const audited = db.tickets.count({ status:"finalizada", outcome:"sucesso", closed_at:{$gte: patch.toISOString()}, os_inventory_guardrail:{$exists:true} });
print({ total, audited, coverage: audited/total });

// 4) Ranking de callers do legado
db.auto_close_legacy_observability.aggregate([
  { $match: { called_at: { $gte: patch.toISOString() } } },
  { $group: { _id: "$caller", n: { $sum: 1 } } },
  { $sort: { n: -1 } }
]);

// 5) Tickets sem trilha (alerta)
db.tickets.find({
  status: "finalizada", outcome: "sucesso",
  closed_at: { $gte: patch.toISOString() },
  os_inventory_guardrail: { $exists: false }
}, { id:1, company_id:1, type:1, closed_at:1, closed_by:1 }).limit(50);
```

---

## §5. CRITÉRIO DE PASSAGEM ONDA 0 → ONDA 1

A Onda 0 pode ser declarada **CONCLUÍDA** quando, na janela de 7 dias:

1. ✅ Métrica 1 = `1.0` (100% das finalizações auditadas)
2. ✅ Métrica 2 ≥ `1.0` (todas reaberturas geraram trilha reversa)
3. ✅ Métrica 4 sem `caller=unknown` (zero chamador escondido)
4. ✅ Métrica 5 = `0` (zero ticket sem trilha)
5. ✅ Métrica 6 dentro de +10% do baseline

Somente após **todos os 5 critérios verdes por 7 dias seguidos**, o CEO autoriza:
- Onda 0c: investigar `/api/stok/services/{id}/close` (rota direta legada).
- Sunset físico do `auto_close_service_from_ticket` (remoção do código).
- Início da Onda 1 (Destrutivos: `stok_admin_reset`).

---

## §6. O QUE NÃO É FEITO NESTA FASE

- ❌ Remoção do `auto_close_service_from_ticket`.
- ❌ Remoção de `/api/stok/services/{id}/close`.
- ❌ Fase 3 (Owner & Location).
- ❌ Migração de schema.
- ❌ Migração das 1.828 ONTs.
- ❌ Limpeza histórica.
- ❌ Refatoração de `_move_ont_for_install` / `_move_ont_for_withdraw`.

Razão: o problema atual é **portas paralelas abertas**, não modelagem. Fechar as portas primeiro; depois reestruturar.

---

## §7. CONTATO / ESCALAÇÃO

- Alerta automático: qualquer `tickets.find({...os_inventory_guardrail:{$exists:false}, status:"finalizada"})` > 0 nas últimas 24h após patch.
- Painel a ser construído na Onda 1: aba "Auditoria Estoque OS" no frontend.
