# TRANSFER FLOW MATRIX — LIGO ESTOQUE OS V2

**Tipo:** Matriz operacional read-only. Complementa `TRANSFER_AUDIT.md`.
**Data:** 16/Fev/2026
**Mandato:** Visualizar o grafo completo de transições de owner permitidas e mapear quais rotas implementam cada aresta.

---

## §1. GRAFO DE OWNERSHIP

```
                       ┌──────────────┐
                       │   COMPRA     │
                       │  (genesis)   │
                       └──────┬───────┘
                              │
                              ▼
                       ┌──────────────┐
              ┌────────│   EMPRESA    │◀────────┐
              │        │  (estoque)   │         │
              │        └──┬──────┬────┘         │
              │           │      ▲              │
              │           │      │              │
              │           ▼      │              │
              │    ┌──────────────┐             │
              ├────│   TÉCNICO    │             │
              │    │  (em campo)  │             │
              │    └──┬──────┬────┘             │
              │       │      ▲                  │
              │       │      │                  │
              │       ▼      │                  │
              │    ┌──────────────┐             │
              │    │   CLIENTE    │             │
              │    │ (instalada)  │             │
              │    └──────────────┘             │
              │                                 │
              └─────► ┌──────────────┐ ─────────┘
                      │   DEFEITO    │
                      │ (em análise) │
                      └──────┬───────┘
                             │
                             ▼
                      ┌──────────────┐
                      │  DESCARTE    │
                      │ (sucateada)  │
                      └──────────────┘
```

---

## §2. MATRIZ DE TRANSIÇÕES PERMITIDAS

| Origem → Destino | Movement Type (canônico) | Rotas que implementam | Classificação atual |
|------------------|--------------------------|------------------------|---------------------|
| `(nada)` → empresa | `genesis_purchase` | `purchases.py:_confirm_purchase`, `stok.py:_register_ont` | 🔴 Sem trilha hoje |
| empresa → tecnico | `transfer_empresa_tecnico` | `stok.py:transfer-to-tech`, `stok.py:transfer-to-tech/bulk` | 🔴 BYPASS |
| tecnico → empresa | `transfer_tecnico_empresa` | `stok.py:return-to-company` | 🔴 BYPASS |
| tecnico → cliente | `transfer_tecnico_cliente` (= instalação) | `lousa.py:public_finalize_ticket` (com guardrail), `stok_transfers.py:pending-transfers/approve` | 🟢/🔴 |
| cliente → tecnico | `transfer_cliente_tecnico` (= retirada) | `lousa.py:public_finalize_ticket` (com guardrail), `field_ops.py:equipment/return`, `stok.py:manual-withdraw` | 🟢/🔴 |
| tecnico → defeito | `transfer_tecnico_defeito` | `field_ops.py:equipment/return` (status=defeito), `stok_transfers.py:confirm-return` | 🔴 BYPASS |
| defeito → empresa | `transfer_defeito_empresa` | `stok_transfers.py:revert-defective-ont` (Onda 1.4 — destructive_audit), `stok_transfers.py:confirm-return` | 🟡 |
| defeito → descarte | `disposal` | `stok_transfers.py:scrap-defective-ont` (Onda 1.4) | 🟡 |
| cliente → empresa | (não permitido diretamente) | — | — |
| empresa → cliente | (não permitido diretamente) | — | — |

> ⚠ As transições "cliente ↔ empresa" só podem acontecer via técnico intermediário. Qualquer rota que faça shortcut deve ser BLOQUEADA.

---

## §3. RANKING POR FREQUÊNCIA DE USO (preview · projeção produção)

| Transição | Volume/dia preview | Estimativa produção (1.828 ONTs) |
|-----------|---------------------|----------------------------------|
| empresa → tecnico (bulk) | 0,1 | ~4-8 ONTs/dia |
| empresa → tecnico (unitário) | 0,05 | ~1-2 ONTs/dia |
| tecnico → empresa (devolução) | 0,02 | ~0,5/dia |
| tecnico → cliente (instalação OS) | 0,07 | ~3-4/dia (já com guardrail) |
| cliente → tecnico (retirada OS) | 0,02 | ~1/dia |
| tecnico → defeito | 0 (preview) | esporádico |
| defeito → empresa (devolução) | 0 | semanal |
| defeito → descarte | 0 | mensal |
| cliente → tecnico (manual_withdraw) | 0 | esporádico (alerta!) |

**Observações:**
- A transição via OS (`public_finalize_ticket`) é **a única** que hoje gera trilha.
- Todas as demais 12 rotas são BYPASS.

---

## §4. SCHEMA UNIFICADO PARA `transfer_engine.execute_transfer`

```python
{
    "movement_id": "mov-<uuid>",
    "audit_hash": "<sha256 64 hex>",
    "company_id": str,
    "movement_type": "transfer_empresa_tecnico" | ... | "disposal",
    "ticket_id": Optional[str],                   # vincula a uma OS quando houver
    "destructive_audit_id": Optional[str],        # cross-ref com Onda 1 (scrap/revert)
    "sn": str,
    "mac": Optional[str],
    "equipment_id": Optional[str],
    "origin_type": Literal["empresa","tecnico","cliente","defeito","descarte"],
    "origin_id": Optional[str],
    "origin_owner_label": str,
    "destination_type": same,
    "destination_id": Optional[str],
    "destination_owner_label": str,
    "actor_id": str,
    "actor_email": str,
    "actor_role": str,
    "actor_origin": "guardrail" | "gestor_ui" | "tecnico_app" | "smartolt_sync" | ...,
    "reason": Optional[Dict],                     # {"code": "...", "details": "..."}
    "performed_at": ISO,
    "physical_attendance": bool,
    "metadata": {                                  # opcional, livre
        "previous_state": {...},
        "smartolt_serial": Optional[str],
        ...
    }
}
```

---

## §5. QUERIES MONGO PARA WATCHTOWER (futuras)

### Q1: ONTs em movimento sem trilha
```javascript
db.stok_onts.find({
  location_type: { $in: ["tecnico", "cliente"] }
}).forEach(o => {
  const t = db.inventory_os_movements_audit.findOne({mac: o.mac});
  if (!t) print(JSON.stringify(o));
});
```

### Q2: Volume de transferências por tipo (30d)
```javascript
db.inventory_os_movements_audit.aggregate([
  { $match: { created_at: { $gte: new Date(Date.now() - 30*86400e3).toISOString() } } },
  { $group: { _id: "$movement_type", n: { $sum: 1 } } },
  { $sort: { n: -1 } }
])
```

### Q3: Top 10 técnicos (origem ou destino)
```javascript
db.inventory_os_movements_audit.aggregate([
  { $match: { $or: [
      { origin_type: "tecnico" },
      { destination_type: "tecnico" }
  ]}},
  { $project: { tech_id: { $cond: [
      { $eq: ["$origin_type", "tecnico"] }, "$origin_id", "$destination_id"
  ]}}},
  { $group: { _id: "$tech_id", n: { $sum: 1 } } },
  { $sort: { n: -1 } }, { $limit: 10 }
])
```

### Q4: Discrepância owner ↔ trilha
```javascript
db.stok_onts.aggregate([
  { $lookup: {
      from: "inventory_os_movements_audit",
      let: { mac: "$mac" },
      pipeline: [
        { $match: { $expr: { $eq: ["$mac", "$$mac"] } } },
        { $sort: { created_at: -1 } },
        { $limit: 1 }
      ],
      as: "last_mov"
  }},
  { $project: {
      mac: 1, current: "$location_type",
      last_trail: { $arrayElemAt: ["$last_mov.destination_type", 0] }
  }},
  { $match: { $expr: { $ne: ["$current", "$last_trail"] } } }
])
```

---

## §6. PRÉ-REQUISITOS TÉCNICOS PARA ONDA 2

| Item | Estado atual | Bloqueia Onda 2? |
|------|--------------|------------------|
| `services/inventory_movements.write_movement` | ✅ existe | Não |
| `services/os_inventory_guardrail.enforce_*` | ✅ existe | Não |
| Helper `record_destructive_action` (Onda 1) | ✅ existe | Não |
| Helper `transfer_engine.execute_transfer` | 🔴 INEXISTENTE | **SIM** — é a Etapa 2.1 |
| Índice Mongo `{company_id, created_at}` em `inventory_movements` | 🟡 a verificar | Não, só performance |
| Decisão CEO sobre 11 órfãos | 🟡 pendente | **SIM** — define política de backfill |
| Decisão sobre `reason` opcional vs obrigatório | 🟡 pendente | Não (defaults possíveis) |

---

## §7. RISCOS IDENTIFICADOS

| Risco | Probabilidade | Mitigação proposta |
|-------|---------------|--------------------|
| Refatoração quebra fluxo de OS em produção | Média | Cada PR sai com smoke + E2E. Mesma cadência da Onda 1 (1.1→1.4). |
| `pending-transfers/approve` em paralelo com `finalize_ticket` cria double-write | Alta | A 1ª refatoração já isola — helper é idempotente por audit_hash |
| `manual-withdraw` cria movimento sem OS | Alta | Helper aceita `ticket_id=None` mas marca `actor_origin="gestor_manual"` para rastrear no Watchtower |
| Migração das 11 ONTs órfãs gera 11 trilhas sintéticas que poluem o relatório | Baixa | Marcar movement_type="onda2_orphan_backfill" + filtrar por padrão na Watchtower |
| `stok_history.action=null` continua poluindo ranking | Média | Etapa 2.4 explícita; não bloqueia o motor canônico |

---

## §8. CHECKLIST PRÉ-IMPLEMENTAÇÃO

Antes de iniciar PR 2.1 (helper) o CEO precisa:

- [ ] Aprovar plano §5 do `TRANSFER_AUDIT.md`.
- [ ] Decidir política B1/B2/B3 sobre os 11 órfãos.
- [ ] Decidir `reason` opcional vs obrigatório em transfer_engine.
- [ ] Confirmar que Etapa 2.4 (cleanup `stok_history`) sai do escopo principal.

---

## §9. CONCLUSÃO OPERACIONAL

- Grafo de ownership documentado com **5 transições principais permitidas**.
- 12 rotas BYPASS identificadas, ranqueadas por gravidade.
- Schema único pronto para `transfer_engine`.
- 4 queries mongo prontas para alimentar futura Watchtower.
- 4 decisões pendentes do CEO antes de iniciar PR 2.1.
