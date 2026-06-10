# RELATÓRIO — OPERAÇÃO REGISTRO AUTOMÁTICO DE ATRIBUIÇÃO

**Data:** 10/02/2026
**Política:** Tempo real · Idempotência absoluta · Zero coleção nova

---

## 1. ARQUIVOS ALTERADOS

| Arquivo | Mudança |
|---|---|
| `services/presidente_financeiro.py` | + status `pending_confirmation` / `confirmed` · + `confirm_ledger_entry` · + 5 categorias (ISABELLA_OS_CREATED, ISABELLA_OS_RESOLVED, ISABELLA_TRUCK_ROLL_BLOCKED, ALVARO_INCIDENT_DETECTED, ALVARO_CLIENTS_PROTECTED) |
| `services/truck_roll_guard.py` | Hook automático ao final de `evaluate()` → atribui TRUCK_ROLL_AVOIDED quando decisão é DO_NOT_DISPATCH ou PREVENTIVA |
| `services/lousa_coo.py` | 3 hooks: `enforce_preventive_ratio` (PREVENTIVE_AVOIDED_VISIT pending) · `alvaro_command_loop` para CTO/ONU (PREVENTIVE_AVOIDED_VISIT) · escala incidente (INCIDENT_REVENUE_PROTECTED + ALVARO_*) · projeção corrigida para incluir `cto_id`/`olt_name` |
| `services/smart_field_v2.py` | Hook em `track_equipment_stage` quando `stage=REAPROVEITAMENTO` → EQUIPMENT_REUSED |
| `services/isabella_lousa_scheduler.py` | Hook em `confirm_and_create_os` (ISABELLA_OS_CREATED pending) · `decide_action` quando NO_OS (ISABELLA_TRUCK_ROLL_BLOCKED) · novo helper `mark_isabella_os_resolved` |

### Arquivos novos
| Arquivo | LoC |
|---|---|
| `scripts/test_atribuicao_automatica.py` | 280 — 8 cenários reais com setup limpo |

---

## 2. HOOKS CONECTADOS

| Fluxo operacional | Hook | Categoria | Status inicial |
|---|---|---|---|
| `truck_roll_guard.evaluate` DO_NOT_DISPATCH/PREVENTIVA | `attribute_truck_roll_avoided(source=truck_roll_guard)` | TRUCK_ROLL_AVOIDED | confirmed |
| `isabella.decide_action` NO_OS | `attribute_truck_roll_avoided(source=isabella)` | ISABELLA_TRUCK_ROLL_BLOCKED | confirmed |
| `isabella.confirm_and_create_os` | `attribute_isabella_os` | ISABELLA_OS_CREATED | **pending** |
| `isabella.mark_isabella_os_resolved` | `attribute_isabella_os_resolved` + promove pending→confirmed | ISABELLA_OS_RESOLVED | confirmed |
| `lousa_coo.enforce_preventive_ratio` cria preventiva | `attribute_preventive` | PREVENTIVE_AVOIDED_VISIT | **pending** |
| `alvaro_command_loop` cria preventiva CTO/ONU | `attribute_preventive` | PREVENTIVE_AVOIDED_VISIT | **pending** |
| `alvaro_command_loop` escala incidente | `attribute_incident_protection(source=alvaro)` | INCIDENT_REVENUE_PROTECTED · ALVARO_INCIDENT_DETECTED · ALVARO_CLIENTS_PROTECTED | confirmed |
| `smart_field_v2.track_equipment_stage(REAPROVEITAMENTO)` | `attribute_reuse` | EQUIPMENT_REUSED | confirmed |
| OS sem retorno em 30d (batch ou trigger) | `attribute_os_no_return_30d` | OS_NO_RETURN_30D | confirmed |

---

## 3. CATEGORIAS REGISTRADAS (10)

```
PREVENTIVE_AVOIDED_VISIT       — preventiva cria expectativa pending
EQUIPMENT_REUSED               — reaproveitamento confirma R$ 120
TRUCK_ROLL_AVOIDED             — TRG bloqueia visita R$ 80
INCIDENT_REVENUE_PROTECTED     — receita protegida em incidente
OS_NO_RETURN_30D               — OS resolvida sem retrabalho
ISABELLA_OS_CREATED            — OS criada pela Isabella (pending)
ISABELLA_OS_RESOLVED           — OS Isabella concluída
ISABELLA_TRUCK_ROLL_BLOCKED    — Isabella decidiu NO_OS
ALVARO_INCIDENT_DETECTED       — detecção autônoma
ALVARO_CLIENTS_PROTECTED       — agregado financeiro de clientes
```

---

## 4. FÓRMULAS

| Categoria | Fórmula |
|---|---|
| PREVENTIVE_AVOIDED_VISIT | **R$ 80** por visita corretiva evitada |
| EQUIPMENT_REUSED | **R$ 120** por ONU/equipamento reaproveitado |
| TRUCK_ROLL_AVOIDED | **R$ 80** por visita evitada (TRG) |
| ISABELLA_TRUCK_ROLL_BLOCKED | **R$ 80** por visita evitada (decisão Isabella) |
| ISABELLA_OS_CREATED | **R$ 80** estimativa pending |
| ISABELLA_OS_RESOLVED | **R$ 80** confirma resolução sem retrabalho |
| INCIDENT_REVENUE_PROTECTED | `clientes_impactados × ticket_avg × 30%` |
| ALVARO_CLIENTS_PROTECTED | mesma fórmula (espelho) |
| OS_NO_RETURN_30D | `ticket_mensal × meses_protegidos` |

---

## 5. IDEMPOTÊNCIA

Chave única upsert (`$setOnInsert`) em `executive_ledger`:

```
unique = (company_id, action_id, kind)
```

Onde `action_id` é estável por tipo:
- `preventive::{ticket_id}`
- `reuse::{equipment_id}`
- `truck_roll_avoided::{subscriber_id}::{YYYY-MM-DD}`
- `isabella_truck_roll_blocked::{subscriber_id}::{YYYY-MM-DD}`
- `incident::{incident_id}` / `alvaro_incident::{incident_id}` / `alvaro_clients::{incident_id}`
- `isabella_os::{ticket_id}` / `isabella_os_resolved::{ticket_id}`
- `os_noret::{ticket_id}`

Re-execução do mesmo evento → `update_one` com `$setOnInsert` não toca o doc existente. **Não duplica jamais.**

A função `confirm_ledger_entry()` promove pending → confirmed sem duplicar.

---

## 6. TESTES EXECUTADOS — 8/8 ✅

Script: `backend/scripts/test_atribuicao_automatica.py` · Tenant: `co-attribution-test`

| # | Cenário | Resultado |
|---|---|---|
| 1 | truck_roll_guard.evaluate DO_NOT_DISPATCH | ✅ TRUCK_ROLL_AVOIDED criado |
| 2 | smart_field_v2 REAPROVEITAMENTO | ✅ EQUIPMENT_REUSED R$ 120 |
| 3 | alvaro_command_loop escala incidente | ✅ INCIDENT_REVENUE_PROTECTED + ALVARO_INCIDENT_DETECTED + ALVARO_CLIENTS_PROTECTED (R$ 899,10) |
| 4 | confirm_and_create_os | ✅ ISABELLA_OS_CREATED (pending) |
| 5 | mark_isabella_os_resolved | ✅ pending→confirmed + ISABELLA_OS_RESOLVED |
| 6 | decide_action NO_OS | ✅ ISABELLA_TRUCK_ROLL_BLOCKED |
| 7 | enforce_preventive_ratio | ✅ 2 PREVENTIVE_AVOIDED_VISIT (pending) |
| 8 | reexecução não duplica | ✅ delta=0 nos kinds idempotentes |

---

## 7. EXECUTIVE LEDGER — ANTES vs DEPOIS

```
LEDGER ENTRIES ANTES DOS HOOKS: 0
LEDGER ENTRIES DEPOIS:          10
AUTO-ATRIBUÍDAS EM TEMPO REAL:  10   ← origem principal
PENDING (aguardando confirmação): 2
CONFIRMED:                        8
```

### Breakdown final (1 ciclo de teste)
| Kind | Count | R$ |
|---|--:|--:|
| INCIDENT_REVENUE_PROTECTED | 1 | 899,10 |
| ALVARO_CLIENTS_PROTECTED | 1 | 899,10 |
| PREVENTIVE_AVOIDED_VISIT | 2 | 160,00 |
| EQUIPMENT_REUSED | 1 | 120,00 |
| TRUCK_ROLL_AVOIDED | 1 | 80,00 |
| ISABELLA_OS_CREATED | 1 | 80,00 |
| ISABELLA_TRUCK_ROLL_BLOCKED | 1 | 80,00 |
| ISABELLA_OS_RESOLVED | 1 | 80,00 |
| ALVARO_INCIDENT_DETECTED | 1 | 0,00 (evento puro) |
| **TOTAL** | **10** | **R$ 2.398,20** |

### Batch reconciliação
- `POST /api/colosso/financeiro/run-attribution` rodou DEPOIS dos hooks.
- **Delta de novas entries criadas pelo batch = 0** → batch agora é apenas
  reconciliação, não origem principal. ✅

---

## 8. R$ ATRIBUÍDO AUTOMATICAMENTE vs RECONCILIADO

| Origem | R$ | %
|---|--:|--:|
| **Tempo real (hooks)** | **R$ 2.398,20** | 100% |
| Batch reconciliação | R$ 0,00 | 0% |

Hoje o dinheiro nasce no fluxo operacional — o endpoint `run-attribution`
sobrevive apenas como rede de segurança para eventuais quedas.

---

## 9. GARGALOS RESTANTES

1. **`enforce_preventive_ratio` continua criando novas preventivas a cada
   chamada** — comportamento correto operacionalmente (cobre novas ONUs
   degradadas), mas para idempotência semântica completa seria útil
   marcar ONUs já cobertas por preventiva ativa.
2. **OS_NO_RETURN_30D ainda depende do batch** — o evento "30 dias se
   passaram sem retrabalho" naturalmente exige um job periódico. Solução
   recomendada: APScheduler diário `run_attribution_cycle(window_days=1)`
   apenas para OS_NO_RETURN_30D.
3. **ALVARO_INCIDENT_DETECTED carrega R$ 0,00** — é evento puro (o R$
   real está em INCIDENT_REVENUE_PROTECTED). Decisão de design: facilita
   contagem de eventos sem inflar valor financeiro.

---

## 10. CRITÉRIOS DE ACEITE — 6/6 ✅

| Critério | Status |
|---|---|
| 100% dos hooks registram no executive_ledger | ✅ 10 entries criados em tempo real |
| 0 duplicidade em execução repetida | ✅ Cenário 8: delta=0 |
| Batch manual vira apenas reconciliação | ✅ run_attribution_cycle delta=0 após hooks |
| Status pending e confirmed funcionam | ✅ ISABELLA_OS_CREATED (pending) → ISABELLA_OS_RESOLVED (confirmed) |
| Relatório mostra R$ por origem | ✅ Breakdown por kind |
| Testes passam | ✅ 8/8 cenários |
