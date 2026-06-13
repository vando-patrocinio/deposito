# IAM v2 — Matriz de Permissões (ETAPA 2.1 P3)

**Data:** 13/06/2026
**Status:** Proposta CTO. Aprovação obrigatória ANTES de iniciar ETAPA 2.5.

---

## Princípios

1. **Granularidade `module.action`** — sem cargo em string.
2. **Wildcard explícito** — `tickets.*` libera todas as actions do módulo.
3. **Super admin = `*` literal** — único símbolo que libera tudo.
4. **Sempre indicar risco** — liberar demais e liberar de menos têm impacto.
5. **Default seguro (deny)** — permission fora do catálogo é negada com log.

---

## Tabela mestre — 9 perfis canônicos

| Perfil | Módulos liberados | Quantidade de permissions | Mobile? | Web? | Risco se liberar demais | Risco se restringir demais |
|---|---|---:|:-:|:-:|---|---|
| **Administrador** | Todos (`*`) | 1 | ✅ | ✅ | Pode apagar empresa inteira, desfazer pagamentos, ver folha de todos | Operação trava — não consegue corrigir nada |
| **Auditor** | Todos (`*`) — convenção read-only | 1 | ✅ | ✅ | Vê PII de todos clientes/colaboradores | Não consegue auditar / vazar nada útil |
| **Diretoria** | dashboard.executive + financeiro.view.* + audit.view_all | ~12 | ✅ | ✅ | Vê estratégia + folha, mas não pode editar | Diretor cego sobre o negócio |
| **Gestor** | tickets.* clients.* estoque.* lousa.* frota.* whatsapp.* cadastro.* propostas.* sales.* dashboards | ~45 | ✅ | ✅ | Pode bloquear cliente errado, mandar disparo em massa | Time precisa pedir tudo pro admin |
| **Financeiro** | financeiro.* + clients.view + clients.view.overdue + dashboard.financial + rh.view_holerite_all | ~12 | ✅ | ✅ | Vê pagamentos, pode estornar errado, ver holerite de todos | Não fecha caixa |
| **Comercial** | tickets.view tickets.create clients.* propostas.* sales.* whatsapp.send whatsapp.view_conv | ~15 | ✅ | ✅ | Pode mexer em base de clientes | Não fecha venda |
| **Técnico** | lousa.view lousa.finalize tickets.view tickets.close estoque.view frota.view rede.view rede.run_tests rh.view_holerite_own | ~12 | ✅ | ✅ (limitado) | Pode finalizar OS de outro técnico (precisa scope `own_only` no futuro) | Não consegue fechar OS no campo |
| **Suporte** (atendimento) | tickets.view tickets.create tickets.edit tickets.assign clients.view clients.view.overdue clients.create clients.edit whatsapp.send whatsapp.view_conv | ~12 | ✅ | ✅ | Pode editar dados de cliente | Não consegue abrir chamado |
| **RH / Estoque** (dois perfis distintos) | rh.* / estoque.* | ~6 + ~5 | ✅ | ✅ | Vê dados sensíveis de folha; pode zerar estoque | Não consegue rodar mês / não ajusta saldo |
| **Colaborador** (base) | lousa.view lousa.finalize rh.view_holerite_own | 3 | ✅ | mínimo | Mínimo possível | Cego no app |

---

## Tabela detalhada por perfil

### 1. Administrador

| Permission | Liberada? | Justificativa |
|---|:-:|---|
| `*` | ✅ | Único perfil com curinga absoluto. |

**Rotas impactadas:** todas (1.885 endpoints).
**Risco liberar demais:** existencial — pode dropar collections, vazar PII.
**Mitigação:** **2-eyes** obrigatório em ações `system.kill_switch`, `audit.restore_deleted`, `system.deploy`, `colaboradores.terminate`.

### 2. Auditor

Igual ao Administrador (`*`) **por convenção** — espera-se que não escreva, apenas leia. **Sem hard enforce hoje.**

**Próximo passo (ETAPA 3):** introduzir `read_only: bool` no Profile que filtra writes em runtime. Senão, virar `[X.view, X.view.*, audit.*, dashboard.*]` explícito.

### 3. Diretoria

```
dashboard.executive
dashboard.operational
dashboard.financial
dashboard.technical
financeiro.view.aging
financeiro.view.dre
financeiro.view.daily
audit.view_all
sales.view_funnel
clients.view
```

**Risco liberar demais:** vê folha de pagamento, dados de clientes.
**Risco restringir demais:** dono não vê próprio negócio.

### 4. Gestor

```
# Tickets / OS
tickets.*  lousa.*

# Clientes
clients.view  clients.view.overdue  clients.view.blocked
clients.create  clients.edit  clients.suspend  clients.reactivate

# Estoque / Frota
estoque.*  frota.view  frota.edit_vehicle  frota.assign_driver
frota.view_tracking  frota.view_costs

# WhatsApp / Mensagens
whatsapp.send  whatsapp.view_conv  whatsapp.manage_campaigns

# IA (consumo)
ai.view_insights  ai.view_corrections

# Dashboard
dashboard.operational  dashboard.executive  dashboard.financial

# Cadastros
cadastro.*  pracas.manage  feriados.manage  plans.manage
colaboradores.view  colaboradores.edit
colaboradores.deactivate  colaboradores.assign_profile

# Propostas / Vendas
propostas.*  sales.*

# RH (visualização)
rh.view_holerite_all  rh.view_timesheets  rh.approve_timesheets

# Indique e Ganhe
referrals.*  audit.view_all
```

**Risco liberar demais:** disparo em massa via WhatsApp pode queimar número Meta.
**Risco restringir demais:** gestor pede tudo pro admin — fricção operacional.

### 5. Financeiro

```
financeiro.view.aging
financeiro.view.dre
financeiro.view.daily
financeiro.charge.dispatch
financeiro.refund
financeiro.payment.confirm
financeiro.payment.reverse
financeiro.banking
clients.view  clients.view.overdue
dashboard.financial
rh.view_holerite_all  rh.view_timesheets
```

**Risco liberar demais:** estornar pagamento errado, ver folha de todos.
**Risco restringir demais:** caixa não fecha.

### 6. Comercial

```
tickets.view  tickets.create
clients.view  clients.view.overdue
clients.create  clients.edit
propostas.*  sales.*
whatsapp.send  whatsapp.view_conv
dashboard.operational
```

**Risco liberar demais:** vendedor edita base de clientes alheia.
**Risco restringir demais:** não fecha venda.

### 7. Técnico

```
lousa.view  lousa.finalize
tickets.view  tickets.close
estoque.view
frota.view  frota.view_tracking
rede.view  rede.run_tests
rh.view_holerite_own
```

**Risco liberar demais:** técnico A finaliza OS do técnico B (precisa `lousa.finalize.own_only` no futuro).
**Risco restringir demais:** preso no campo sem fechar OS.

**TODO ETAPA 5:** Implementar scope `own_only` na função `has_permission`.

### 8. Suporte (atendimento)

```
tickets.view  tickets.create  tickets.edit  tickets.assign
clients.view  clients.view.overdue
clients.create  clients.edit
whatsapp.send  whatsapp.view_conv
dashboard.operational
propostas.view  propostas.create
referrals.view
```

### 9. RH

```
colaboradores.view  colaboradores.edit
colaboradores.deactivate
colaboradores.view.clock
rh.view_holerite_all  rh.upload_holerite
rh.view_timesheets  rh.approve_timesheets
dashboard.operational
```

### 10. Estoque

```
estoque.*
cadastro.view
dashboard.operational
```

### 11. Colaborador (base)

```
lousa.view  lousa.finalize
rh.view_holerite_own
```

---

## Mapeamento de rotas críticas → permissions (sample)

| Rota | Hoje (legacy) | IAM v2 (proposta) |
|---|---|---|
| `POST /api/lousa/public/tickets/{tid}/finalize` | role∈{colaborador,...} | `lousa.finalize` |
| `POST /api/lousa/tickets/{tid}/admin-open` | role=gestor | `tickets.assign` OR `lousa.override_geofence` |
| `GET /api/financeiro/aging` | role∈{financeiro,gestor,auditor} | `financeiro.view.aging` |
| `POST /api/financeiro/charges/dispatch` | role∈{financeiro,gestor} | `financeiro.charge.dispatch` |
| `POST /api/payments/{id}/refund` | role∈{financeiro,gestor} | `financeiro.refund` |
| `PUT /api/collaborators/{id}` | role=gestor | `colaboradores.edit` (+ `colaboradores.assign_profile` SE muda profile_id) |
| `DELETE /api/collaborators/{id}` | is_super_admin | `colaboradores.terminate` + 2-eyes |
| `POST /api/whatsapp-campaigns/{id}/send` | role=gestor | `whatsapp.mass_dispatch` |
| `GET /api/audit-log` | role=auditor | `audit.view_all` |
| `POST /api/admin/reset-super-admin-password` | env token | `system.manage_secrets` |
| `POST /api/admin/kill-switch` | is_super_admin | `system.kill_switch` + 2-eyes |
| `POST /api/holerites/upload` | role=financeiro | `rh.upload_holerite` |
| `GET /api/holerites/me` | qualquer auth | `rh.view_holerite_own` |
| `GET /api/holerites?collab_id=X` | role=financeiro | `rh.view_holerite_all` |

**Cobertura ETAPA 2.5:** ~95% das 1.885 rotas via legacy_role_mapping (shim). 5% precisam de migração manual (`user.role == "..."` hardcoded em handler).

---

## 2-eyes (dual-confirmation) — operações críticas

Algumas permissions exigem **2 super admins distintos** confirmando em 5 minutos:

- `system.kill_switch`
- `system.manage_secrets` (rotate JWT_SECRET, OWNER_PASSWORD)
- `audit.restore_deleted` (>10 docs por vez)
- `colaboradores.terminate` (estado terminal)
- `financeiro.refund` (>R$ 1.000)
- `clients.delete` (todo delete de cliente exigirá)

Implementação prevista em ETAPA 7. Schema na coleção `dual_approvals`:

```python
{
  id: "dap-XXXX",
  permission: "system.kill_switch",
  proposer_identity_id, proposed_at, proposer_session_id,
  approver_identity_id, approved_at,
  expires_at: proposed_at + 5min,
  status: "pending" | "approved" | "rejected" | "expired",
  payload: {...},        # ação proposta
  outcome: "executed" | None
}
```

---

## Status da matriz

- ✅ 11 perfis canônicos definidos
- ✅ ~80 permission keys mapeadas no catálogo (`iam_v2/permissions_catalog.py`)
- ✅ Mapping legacy_role → perfil em `LEGACY_ROLE_PERMISSIONS`
- ⏳ Aguardando aprovação CTO: **APROVA esta matriz como base da ETAPA 2.5?**
- ⏳ 2-eyes ainda não implementado (ETAPA 7)
- ⏳ Scopes (`own_only`, `cost_center`) não implementados (futuro)
