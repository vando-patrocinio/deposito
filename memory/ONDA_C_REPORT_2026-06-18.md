# ONDA C — Lousa Mobile Finalize Hardening
**Data**: 18/06/2026 · **Status**: ✅ ENTREGUE · **Testes**: 20/20 PASS (10 locais + 10 HTTP)

## Escopo
Eliminar dois vetores de vazamento de patrimônio no fluxo `public_finalize_ticket`:
- **Bug #4**: técnico fecha OS de sucesso sem registrar materiais consumidos.
- **Bug #6**: troca silenciosa de ONT (sem auditoria).

## Bug #4 — Mandatory Consumables Validation
**Endpoint**: `POST /api/lousa/public/tickets/{ticket_id}/finalize`
**Trigger**: `outcome="sucesso"` AND `not is_admin_test`.

| Tipo OS    | Obrigatório                                          | Fallback (justificativa ≥10 chars) |
|------------|------------------------------------------------------|-------------------------------------|
| instalacao | ONT (sempre) + qtd_drop>0 + (conectores_fast>0)      | conector → observacoes              |
| reparo     | qtd_drop>0 OR conectores>0 OR new_ont_sn/old_ont_sn  | qualquer um → observacoes           |
| retirada   | ont OR ont_sn + asset_recovered                       | asset_recovered → observacoes        |

**Response (400)**:
```json
{
  "detail": {
    "error": "consumiveis_obrigatorios_faltando",
    "missing": ["DROP (metragem usada)", "Conector (ou justificativa...)"],
    "human_reason": "Não é possível finalizar. Material obrigatório não informado: ..."
  }
}
```

## Bug #6 — Auto-detect ONT Swap
**Gatilho**: `t["type"] in ("reparo","instalacao","troca_endereco")` AND `normalize(client_snapshot.current_ont) != normalize(cd.ont|cd.ont_sn)`.

**Side effects**:
1. **Upsert** em `db.auto_ont_swap_events` por `(company_id, ticket_id)`:
   ```json
   {
     "id": "auto-swap-xxx",
     "ticket_id": "...",
     "ont_anterior": "ALCL11112222",
     "ont_atual": "ALCL99998888",
     "detected_by": "auto_detect_v1",
     "status": "pending_confirmation",
     "detected_at": "ISO",
     "ticket_type": "reparo|instalacao|troca_endereco"
   }
   ```
2. `equipment_swap` inicializado com `source="auto_detect_snapshot"`.
3. Ao chegar no bloco `_detect_equipment_swap` (SmartOLT), MERGE — não sobrescreve. `source` vira `auto_detect_snapshot+smartolt` se ambos confirmam.
4. `_persist_equipment_swap` registra em `equipment_swaps` (audit global mensal).
5. Notification ao gestor (`equipment_swap` ou `equipment_swap_suspect` se uptime < threshold).

**Idempotência**: upsert garante 1 documento por ticket mesmo com finalize chamado N vezes.

## Regra de Ouro respeitada
- ✅ Zero deletes (apenas upserts/inserts).
- ✅ Zero history loss (`previous_status` preservado em `equipment_swaps`).
- ✅ Auditoria viva: `auto_ont_swap_events` + `equipment_swaps` + `lousa_finalize_trace` (6 phases).
- ✅ Sem silent try/except — `logger.exception` no auto_close, `logger.warning` apenas em ramos best-effort de notificação.

## Files alterados
- `/app/backend/routes/lousa.py`:
  - Linha ~4084: `ticket_company_id` resolvido cedo (necessário para Bug #4 + #6).
  - Linhas 4214-4262: Bug #4 gate.
  - Linhas 4267-4318: Bug #6 auto-detect + persistence.
  - Linha ~4690: `_detect_equipment_swap` merge sem sobrescrita.

## Testes
- `/app/backend/tests/test_onda_c_lousa.py` — 10/10 chamadas diretas.
- `/app/backend/tests/test_onda_c_lousa_http.py` — 10/10 HTTP REST via testing agent.
- `tests/test_onda_a_stok.py` + `tests/test_onda_b_late_close.py` — 16/16 mantidos (regressão zero).

## Próximos (P1)
1. Script Auditoria Praça x Técnico → `/app/memory/PRAÇA_TECNICO_AUDIT.md` (read-only).
2. Watchtower Diagnóstico (sub-aba EKG Lousa Mobile).

## Code review crítico (P2)
- `lousa.py` >9k linhas → split em sub-routers.
- `public_finalize_ticket` >700 linhas → extrair gates para `services/`.
- Endpoint público sem JWT → adicionar rate-limit por collaborator_id.
