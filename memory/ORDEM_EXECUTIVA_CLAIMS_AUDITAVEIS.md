# Ordem Executiva — Afirmações Auditáveis (Implementação completa)
*17/02/2026 · CEO*

## Princípio implantado
**"Se não consegue provar, não pode afirmar."**

## Arquitetura

### Novo módulo central
`services/isabella_factual_claims.py` — padrão institucional **único**
para toda afirmação factual. Substitui (e estende) o
`isabella_financial_audit` legado.

#### API pública
```python
from services.isabella_factual_claims import claim, ClaimDomain

claim_doc = await claim(
    domain=ClaimDomain.FINANCIAL,     # | TECHNICAL | CADASTRO | ESTOQUE
    entity_type="subscriber",
    entity_id=subscriber["id"],
    company_id=cid,
    checks=[
        {"name": "identification", "ok": True, "ext": "ATLAZ-..."},
        {"name": "primary_count",  "ok": True, "paid": 3, "open": 0},
        {"name": "sync_freshness", "ok": True, "stale_h": 6.8},
    ],
    warnings=[],
    evidence={...},   # snapshot dos fatos afirmados
)
# claim_doc["id"]            → evidence_id (claim-financial-9ca6d613fd)
# claim_doc["audit_passed"]  → True SSE todos checks ok + zero warnings
```

#### Schema persistido (collection `isabella_factual_claims`)
```
{ id, domain, entity_type, entity_id, company_id, audited_at,
  checks: [{name, ok, ...}], warnings: [str], evidence: {...},
  audit_passed: bool, ttl_minutes: int, consumed_by: null|wa_msg_id }
```

### Integração ativa
- ✅ **Financeiro** (`boleto_flow.py`): toda mensagem "em dia"/"em
  débito" gera 1 claim. **Sem claim_passed → não afirma.**
- 🟡 **Técnico** (futuro): `smartolt_status` deve gerar claim em
  `ClaimDomain.TECHNICAL` antes de afirmar potência ótica / online.
- 🟡 **Cadastro** (futuro): mudança de plano / endereço.
- 🟡 **Estoque** (futuro): "está com o técnico X".

### Endpoints admin (gestor/admin/auditor)
- `GET /api/isabella/learning-health/factual-claims/stats` — KPI de
  trust rate 24h, breakdown por domínio, top warnings.
- `GET /api/isabella/learning-health/factual-claims?domain=X&passed=Y`
  — drill-down nas claims com seus checks + evidence.

### Prompt da Isabella
Seção **1.5 — REGRA DE OURO** adicionada ao `isabella_v13.md`:
- Princípio "se não consegue provar, não pode afirmar"
- Lista de 7 afirmações proibidas sem evidência
- Padrão de evidência por domínio (financial/technical/cadastro/estoque)
- Resposta obrigatória quando falta evidência: *"Vou conferir essa
  informação com mais cuidado. Só um instante."*
- Reload aplicado: prompt sha `e0c276ef...`

## Validação end-to-end

```
JOELVALDO (sub-7de424b4f29a, cliente REAL)
   ↓
_audit_subscriber_financial_status(cid, subscriber)
   ↓
3 checks: identification OK · primary_count OK (paid=3, open=0) · sync 6.8h OK
warnings: []
audit_passed: True
   ↓
claim() persiste:
  id=claim-financial-9ca6d613fd
  evidence={paid_count: 3, last_paid: 11/06, next_due: 10/07, sync: 6.8h}
   ↓
format_invoices_message detecta audit_passed=True
   ↓
Mensagem ao cliente COM PROVA:
  "✅ Última fatura paga em *11/06/2026*"
  "📅 Próxima fatura vence em *10/07/2026*"
  "Se algo não bate, me avisa"
   ↓
GET /factual-claims/stats: trust_rate_pct=100.0%
```

## KPI sugerido para Watchtower
`trust_rate_pct` = `passed_24h / total_24h`. **Meta: ≥ 99%.**
Se cair abaixo: warnings indicam onde corrigir (sync stale → cron sync;
unidentified → backfill subscriber_phones; etc).

## Extensão prática para os outros domínios

### Técnico (próximo a fazer)
```python
# Em smartolt_status.py / antes de afirmar "ONU online":
claim_doc = await claim(
    domain=ClaimDomain.TECHNICAL,
    entity_type="onu", entity_id=onu_sn, company_id=cid,
    checks=[
        {"name": "olt_reachable", "ok": olt_resp_ok},
        {"name": "rx_power_in_range", "ok": -30 < rx_dbm < -8,
         "rx_dbm": rx_dbm},
        {"name": "snapshot_fresh", "ok": age_min < 5},
    ],
    warnings=[...] if [...] else [],
    evidence={"rx_dbm": rx_dbm, "uptime_days": uptime},
)
if not claim_doc["audit_passed"]:
    return "Vou conferir o sinal do seu equipamento."
return f"✅ ONU online · 📶 {rx_dbm:.1f} dBm"
```

### Cadastro
Antes de afirmar plano contratado: validar `subscribers.id`,
`subscribers.plan_id != null`, `plan_id` resolve em `plans`,
`plans.active=True`.

### Estoque
Antes de afirmar "equipamento com o técnico João": validar `inventory.location_type=field_op`, `inventory.owner_id=tec-joao`, `last_movement_at <= 24h`.

## Cleanup pendente
- `isabella_financial_audit` mantido durante migração (retrocompat) —
  remover após Sprint 5.
- Adicionar índice em `isabella_factual_claims`:
  `(company_id, audited_at desc)` + `(domain, audit_passed)`.

## Princípio final
A confiança no chatbot **não depende mais de fé na IA**. Depende das
**evidências persistidas que a IA produz**. Toda mensagem importante
tem um `evidence_id` que o gestor (ou o próprio cliente, se quisermos
abrir esse direito) pode reabrir e auditar.
