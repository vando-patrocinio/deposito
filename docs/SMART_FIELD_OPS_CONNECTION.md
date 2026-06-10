# SMART FIELD OPS — Contrato de Conexão App Colaborador Externo ↔ SmartProv

> **Regra central**: o App é a mão, o SmartProv é o cérebro. O App Colaborador
> Externo NÃO tem banco próprio, API paralela, login próprio ou identidade
> visual separada. Ele é uma extensão mobile do SmartProv.
>
> Implementado em 06/2026. Backend: `/app/backend/routes/field_ops.py`.
> Frontend: `FieldOps.js`, `FieldOpsFrota.js`, `FieldOpsEstoque.js` (técnico,
> dentro do `CollaboratorApp`) e `FieldOpsManagerPanel.js` (gestor, sidebar
> "Field Ops (Campo)").

---

## 1. Autenticação e segurança (TODOS os endpoints)

| Camada | Implementação |
|---|---|
| JWT obrigatório | `Depends(get_current_user)` — mesmo JWT do SmartProv (`/api/auth/login`). Sem token → **401**. |
| Vínculo colaborador | `users.collaborator_id` OU `users.email == collaborators.email` (mesma empresa). Sem vínculo → **403**. |
| RBAC | Técnico (colaborador) age apenas no próprio contexto. Gestor/admin/auditor pode LER outro técnico via `?cid=` (modo somente leitura). Escrita cross → **403**. |
| company_id | Toda query filtra `company_id` do JWT. OS de outra empresa → **404** (não vaza existência). |
| Ownership | `tickets.assigned_collaborator_id == colaborador do JWT`, senão **404**. |
| Rate limit | slowapi — `field_read` 240/min, `field_action` 60/min (10× em DEV). |
| Auditoria | Toda ação grava `db.audit_log` com `source=field_ops`, `kind=FIELD_*`, user, colaborador, ticket. |
| Zero mock | Nenhum dado sintético. Tudo lê/escreve nas collections reais. |

## 2. Rotas

### Leitura
| Rota | Retorna |
|---|---|
| `GET /api/field/me` | user + colaborador vinculado + empresa + `read_only` |
| `GET /api/field/dashboard` | OS do dia, OS ativa, próxima OS, contadores (pendentes/atrasadas/feitas), estoque (consumíveis + ONUs), ponto (`_today_clock_state` da Lousa), frota (vistoria pendente?), GPS ativo (ping < 10min em `tech_locations`), toggles |
| `GET /api/field/os/today` | OS do dia do técnico (grade America/Sao_Paulo) |
| `GET /api/field/os/{id}` | ticket + cliente (`subscribers`) + CTO/porta (`ctos` via `_find_client_cto_port`) + ONU/MAC/SN (`stok_onts`) + plano + histórico (`ticket_logs`) + testes de sinal + materiais + toggles de validação |
| `GET /api/field/stock/me` | consumíveis (`stok_stock`) + ONUs (`stok_onts` location_type=tecnico) |
| `GET /api/field/materials/catalog` | catálogo oficial de consumíveis do Estoque |
| `GET /api/field/vehicle/status` | última vistoria, pendência, próximo vencimento |
| `GET /api/field/settings` | toggles da empresa |
| `GET /api/field/admin/overview` | painel do gestor (RBAC gestor/admin/auditor) |

### Ações (escrita — bloqueadas em modo gestor)
| Rota | Payload | Efeito no SmartProv | Evento |
|---|---|---|---|
| `POST /api/field/os/{id}/start` | `{latitude?, longitude?}` | Delega a `lousa.public_open_ticket` → bolha vira **aberta**, mesmas travas (ponto de entrada, 1 OS ativa por vez, bridge estoque `auto_open_service_for_ticket`). Gates extras: GPS (toggle) e vistoria de frota (toggle) → **412**. | `field.os.started` |
| `POST /api/field/os/{id}/arrive` | `{latitude, longitude, accuracy?}` (GPS sempre obrigatório) | `tickets.field_arrived_at` + `field_arrive_location` + `ticket_logs` | `field.os.arrived` |
| `POST /api/field/os/{id}/photo` | `{data_url, label?, kind?}` | push em `tickets.field_photos` (máx 40) + `ticket_logs` | `field.photo.uploaded` |
| `POST /api/field/os/{id}/signal-test` | `{dbm, phase: before/after, notes?}` | push em `tickets.field_signal_tests` + `ticket_logs`. dBm < −27 → severidade **alta** | `field.signal.registered` |
| `POST /api/field/os/{id}/material-used` | `{items:[{consumable_id, quantity}]}` | `_decrement_tech_stock` (baixa REAL em `stok_stock`) + `stok_history` + push `tickets.field_materials`. Quebra → notificação gestor; toggle `block_material_without_stock` ON → **409** | `field.material.used` + `field.stock.updated` |
| `POST /api/field/os/{id}/finish` | `{completion_data, latitude, longitude, outcome, bad_signal_auth_id?}` | Delega a `lousa.public_finalize_ticket` → TODAS as regras valem: checklist (CompletionData), foto obrigatória em instalação, CTO/porta obrigatória (toggle `cto_port_required`), SN/SmartOLT, sinal ruim, estoque, troca de ONT, NPS, WhatsApp. Gate extra: GPS (toggle) → **412** | `field.os.finished` |
| `POST /api/field/os/{id}/reschedule` | `{new_date, new_time, motivo}` | Técnico PROPÕE → `lousa_manager_callback_requests` (kind=reschedule) + `needs_manager_action` + notificação. Gestor confirma no SmartProv. | `field.os.rescheduled` |
| `POST /api/field/os/{id}/block-reason` | `{motivo, latitude?, longitude?}` | `lousa_manager_callback_requests` (kind=blocked) + `manager_callback_required` + notificação gestor | `field.os.blocked` |
| `POST /api/field/vehicle/inspection` | `{plate, km, photo_front, photo_rear, photo_left, photo_right, notes?}` | insert `field_vehicle_inspections` (KM + 4 fotos obrigatórias, week_key) | `field.vehicle.inspection.done` |
| `POST /api/field/equipment/return` | `{ticket_id?, mac?, sn?, recovered, physical_state, notes?}` | Ver §5 Retirada | `field.equipment.returned` + `field.stock.updated` |
| `PUT /api/field/settings` | toggles | RBAC gestor/admin. Grava `aihub_settings key=field_ops_toggles` | — |

## 3. Eventos internos (`services/event_bus.py` → `motor_ia_events`)

`field.os.started · field.os.arrived · field.photo.uploaded ·
field.signal.registered · field.material.used · field.os.finished ·
field.os.rescheduled · field.os.blocked · field.vehicle.inspection.done ·
field.equipment.returned · field.stock.updated`

Todos com `company_id`, `user_id`, `source=field_ops`, `correlation_id` e
payload — consumidos pelo Sistema Nervoso (Presidente IA, Álvaro IA,
observabilidade, auditoria).

## 4. Collections usadas (NENHUMA tabela paralela de OS/cliente/estoque)

| Collection | Uso |
|---|---|
| `tickets` | OS (mesma da Lousa). Campos novos: `field_arrived_at`, `field_arrive_location`, `field_start_location`, `field_photos[]`, `field_signal_tests[]`, `field_materials[]` |
| `ticket_logs` | Timeline da Lousa — toda ação do App aparece para o gestor |
| `collaborators` / `users` | Identidade — mesma autenticação |
| `stok_stock` / `stok_onts` / `stok_history` / `stok_services` | Estoque real do técnico |
| `ctos` | Porta ocupada na instalação (via finalize) e liberada na retirada (`_free_cto_port`) |
| `subscribers` | Cliente real |
| `tech_locations` | GPS (ping do app continua em `/api/tech-tracking/public/ping`) |
| `lousa_manager_callback_requests` | Reagendamento/impedimento → fila do gestor |
| `notifications` | Avisos a gestor/financeiro |
| `aihub_settings` (key=`field_ops_toggles`) | Toggles por empresa |
| `field_vehicle_inspections` | NOVA — vistoria semanal (KM + 4 fotos, histórico p/ IA) |
| `field_equipment_returns` | NOVA — retiradas com impacto financeiro (lida pelo DRE/painel) |
| `audit_log` | Auditoria de toda ação |
| `motor_ia_events` | Eventos `field.*` |

## 5. Regras de negócio

### Bloqueios (na ordem em que disparam)
1. Sem JWT → 401. Sem vínculo colaborador → 403. Modo gestor escrita → 403.
2. OS de outro técnico/empresa → 404.
3. `gps_required` ON e sem lat/lng → 412 `GPS_REQUIRED` (start/finish).
4. `vehicle_inspection_required` ON e vistoria > `vehicle_inspection_max_age_days` dias → 412 `VEHICLE_INSPECTION_PENDING` (start).
5. Travas herdadas da Lousa no start: ponto de Entrada batido (se `clock_in_enabled`), uma OS ativa por vez.
6. Travas herdadas da Lousa no finish: checklist `CompletionData` completo (sinal, materiais), ≥1 foto em instalação, `cto_port_required`, `sn_smartolt_or_photo_required`, sinal ruim exige autorização, "informada" exige motivo e NÃO fecha (vai pro gestor).
7. `block_material_without_stock` ON e saldo insuficiente → 409 `INSUFFICIENT_STOCK`.

### Retirada financeira (`/equipment/return`)
- Recuperado (estado `bom`) → ONT volta a `stok_onts` como `retirada_com_tecnico` no estoque do técnico; `danificado/inutilizado` → `defeito_devolver_empresa`.
- Não cadastrado → entra no estoque com `source=field_equipment_return`.
- Porta da CTO do cliente é LIBERADA (`_free_cto_port`).
- Impacto financeiro: `equipment_default_cost` (toggle, default R$ 250) → `value_recovered` (bom/danificado) ou `value_lost` (não devolvido/inutilizado) gravado em `field_equipment_returns` (alimenta DRE/painel 30d).
- Perda → notificação `field_equipment_loss` para financeiro/gestor.

### Toggles por empresa (defaults DESLIGADOS — decisão CTO)
```json
{
  "vehicle_inspection_required": false,
  "vehicle_inspection_max_age_days": 7,
  "gps_required": false,
  "block_material_without_stock": false,
  "equipment_default_cost": 250.0
}
```

## 6. Fluxos

### App → SmartProv
Técnico age no App → endpoint `/api/field/*` (JWT) → regra delegada à
Lousa/Estoque → `tickets`/`stok_*`/`ctos` atualizados → `ticket_logs`
(bolha da Lousa muda em tempo real p/ o gestor) → `audit_log` →
`motor_ia_events` (Presidente IA/Álvaro IA) → notificações quando aplicável.

### SmartProv → App
Gestor cria/transfere/reagenda OS na Lousa → `tickets` → App lê via
`GET /api/field/dashboard` e `GET /api/field/os/today` (mesma collection,
sem fila intermediária). Toggles mudados no painel valem imediatamente.

## 7. Painel do gestor (`Field Ops (Campo)` no sidebar)
Técnicos em campo · OS andamento/atrasadas/finalizadas · GPS por técnico ·
estoque por técnico (ONUs + consumíveis) · frota pendente · retiradas +
impacto financeiro 30d · produtividade · Truck Roll Avoidance 30d
(`completion_data.resolution_kind == "remote"`) · toggles de bloqueio.

## 8. Testes (zero mock — Mongo + API reais)
`/app/backend/scripts/test_field_ops.py` — 12 cenários do contrato:
ownership, cross-company 404, 401 sem JWT, checklist bloqueia, foto
bloqueia, GPS bloqueia, material baixa estoque, retirada devolve ao
estoque, retirada gera impacto financeiro, Lousa atualiza, evento p/
Presidente IA, frota pendente bloqueia. Fixtures reais criadas e removidas
pelo próprio script.

---

# ISABELLA FIELD PRESIDENT (10/06/2026)

Isabella preside a operação de campo. Motor de decisão determinístico sobre
dados REAIS (`services/isabella_field.py`) + visão Álvaro IA (Claude Sonnet
vision via Emergent Key, fallback heurístico sobre dados reais).

## Rotas (`/api/field/isabella/*` — JWT, mesma segurança da camada field)
| Rota | Função |
|---|---|
| `GET /briefing` | Saudação + agenda + recomendação com motivos reais (SLA, distância GPS→CTO, reincidência, probabilidade histórica) + alertas de estoque + frota. Evento `recommendation.created` (throttle 10min). |
| `GET /route` | Rota recomendada (vizinho-mais-próximo ponderado por score real). Eventos `route.optimized` + `priority.changed`. |
| `GET /os/{id}/brief` | Instalação: CTO/porta sugeridas (cto_ports reais), previsão de sinal (média real), materiais (média de 90d), risco da região. Reparo: causas prováveis (histórico `isabella_root_cause`), reincidência, contexto CTO, roteiro de testes. Retirada: comodato, equipamentos do cliente, impacto. |
| `GET /lousa-analysis` (gestor) | Analisa TODAS as bolhas pendentes/abertas em lote e PERSISTE `tickets.isabella` {priority_rank, score, risk, analysis, prediction}. Pill `ISA #rank · risco` em cada bolha da Lousa admin. |
| `GET /president-summary` (gestor) | Indicadores consolidados p/ Presidente IA: produtividade/notas por técnico, retrabalho, truck-roll avoidance, frota, comodato. |

## Hooks automáticos
- `POST /api/field/os/{id}/finish` → `score_finish`: notas reais (qualidade=sinal,
  organização=fotos/testes, processo=duração, resultado=outcome) persistidas em
  `tickets.isabella_score` + causa raiz (reparo) em `tickets.isabella_root_cause`.
  Eventos `installation.scored`/`repair.scored` + `root_cause.detected` +
  `truck_roll_avoided` (resolution_kind=remote).
- `POST /api/field/vehicle/inspection` → nota Isabella imediata (KM delta real,
  4 fotos) + análise Álvaro vision em background gravada em
  `field_vehicle_inspections.alvaro` {score, risco_quebra, previsao_manutencao,
  custo_futuro_estimado_brl, avarias}. Evento `vehicle.scored`.

## Eventos novos (motor_ia_events ← Presidente IA)
`field.isabella.recommendation.created · route.optimized · installation.scored ·
repair.scored · vehicle.scored · stock.alert · priority.changed ·
root_cause.detected · truck_roll_avoided`

## Frontend
- `FieldOpsIsabella.js`: IsabellaCard (topo do dashboard do técnico) +
  IsabellaOsBrief (detalhe da OS). Nota Isabella exibida em OS finalizada.
- `FieldOpsManagerPanel.js`: IsabellaGovernance (summary do Presidente +
  botão "Analisar Lousa agora" + tabela top 10).
- `LousaAdminPanel.js`: pill `isabella-pill-{id}` em toda bolha analisada.

## Testes zero-mock
`scripts/test_isabella_field.py` — 11/11 (briefing, eventos, rota reordenada,
estoque, briefs, finish real com notas+causa raiz, frota+Álvaro, Lousa
presidida em 865 bolhas reais, president-summary, RBAC). Regressão
`test_field_ops.py` 13/13. E2E frontend iteration_226 — 7/7.
