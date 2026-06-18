# SPRINT 5 · ONDA 5 — GENESIS CERTIDÃO QUARENTENA

**Empresa**: `co-demo` · **Executado**: 2026-02-19 23:36 UTC
**Mandato**: ORDEM EXECUTIVA CEO 19/02/2026 · **Opção D — Duas Camadas**
**Tier**: `quarantine` · **Status**: PRESERVADAS · **Excluídas do balanço oficial**

## 1. RESULTADO

| Métrica | Valor |
|---------|------:|
| ONUs em quarentena | **387** |
| % com subscriber vinculado | 0% |
| % com data_confidence ≥0.90 | 0% |
| asset_status | `pending_validation` |
| exclude_from_balance | **true** |
| Onda 6 elegível | ❌ **FALSE** (correto) |

## 2. POR QUE ESTÃO AQUI

Estas 387 ONUs têm:
- SN ou MAC válido em `smartolt_onus`
- MAS `name` não permitiu fuzzy match com nenhum subscriber ativo
- `data_confidence = 0.70` (inferência baixa)

## 3. METADATA PRESERVADA

Cada doc em `stok_onts` da quarentena possui:

```json
{
  "origin": "smartolt_genesis",
  "import_batch_id": "o5g-qua-661cec24a034",
  "imported_at": "2026-02-19T23:36:31Z",
  "imported_by": "usr-2100548587",
  "genesis_version": "sprint5_onda5_v1",
  "data_confidence": 0.70,
  "data_confidence_path": "inventory_only_no_client",
  "tier": "quarantine",
  "asset_status": "pending_validation",
  "exclude_from_balance": true
}
```

## 4. FASE 5.2C — WORKER DE PROMOÇÃO

Implementado em `POST /api/sprint5/onda5/promote-pending?confirm=true`.

**Execução pós-genesis** (2026-02-19 23:36 UTC):
- Promoted: **0**
- Still pending: **387**

**Por quê 0?** O worker re-classifica cada ONU contra:
- `subscriber_access_points` (pppoe_user) — SmartOLT continua com 0 pppoe
- `network_access_canonical` (ont_sn/ont_mac → subscriber) — 0 links com essas SNs
- name fuzzy match — já foi aplicado e falhou

Promoção automática ocorrerá quando:
1. Time de infra preencher `pppoe_user` no SmartOLT (re-sync futura)
2. Técnico realizar OS via Lousa (vincula via canonical)
3. Operador associar manualmente o subscriber

## 5. REGRA DE OURO RESPEITADA

**Zero deletes**: as 387 ONUs estão preservadas em `stok_onts` com
`exclude_from_balance=true`. Não contaminam o Auto Balanço da Onda 6,
mas continuam visíveis e auditáveis para revisão futura.

## 6. AUDIT TRAIL

Batch: `o5g-qua-661cec24a034`
Audit: `sprint5_audit_log.id = o5a-2a3eb2ad40c549`
Action: `genesis_import.completed.quarantine`

## 7. CRESCIMENTO ESPERADO

Conforme a operação real avança (Onda 3 enforcement + Lousa
finalizações), espera-se promoção orgânica:

| Mês | ONUs promovidas (estimativa) |
|----:|------------------------------:|
| Mês 1 | 50-80 |
| Mês 3 | 150-200 |
| Mês 6 | 300+ (potencialmente 100% dependendo do esforço operacional) |

---
**Certidão emitida automaticamente** por
`/api/sprint5/onda5/certidao?tier=quarantine` em 2026-02-19 23:36 UTC.
Status: **PRESERVADAS**. Hash do batch: `o5g-qua-661cec24a034`.
