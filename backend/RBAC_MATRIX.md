# RBAC Matrix — SmartProv (Sprint 2)

> Gerado automaticamente em **2026-06-08T00:57:30.529850+00:00** por `scripts/generate_rbac_matrix.py`.
> Não edite à mão — a fonte da verdade é `rbac_policy.py`.

## Sumário executivo

- **Total de endpoints `/api/*`:** 1357
- **Públicos (sem auth):** 29
- **Endpoints com auth não-staff (portais cliente/parceiro/segurança/frota):** 73
- **Staff privados (sob RBAC corporativo):** 1255
- **Com role-rule explícita:** 1243
- **DELETE (audit obrigatório):** 77
- **EXPORT (audit obrigatório):** 10
- **IA (rate-limit obrigatório):** 291

### 🎯 Cobertura RBAC: **99.04%** (meta ≥ 70%)

---

## Como funciona

Todo request `/api/*` passa por `_rbac_middleware` em
`server.py`, que:

1. Libera se o path está em `PUBLIC_PATHS` (webhooks, login, health).
2. Decodifica JWT (401 se ausente/inválido).
3. Pula role-check em portais não-staff (`NON_STAFF_AUTH_PREFIXES`).
4. Aplica `required_roles_for(path)` (longest-prefix match) — **403** se role do user não está no set permitido. `administrador` SEMPRE passa.
5. Em rotas IA aplica `rate_limit` (`IA_RATE_LIMIT_PREFIXES`) — **429** se exceder.
6. Em DELETE/EXPORT grava entrada em `audit_log`.

---

## Matriz de permissões por prefixo

| Prefixo | Roles permitidos | IA rate-limit | Endpoints |
|---------|------------------|---------------|-----------|
| `/api//*` | auth-only |  | 1 |
| `/api/about/*` | PÚBLICO |  | 1 |
| `/api/access-tags/*` | admin*, administrador, auditor |  | 2 |
| `/api/admin/*` | admin*, administrador |  | 12 |
| `/api/ai/*` | admin*, auditor, gestor, tecnico | ✅ | 20 |
| `/api/ai-config/*` | admin*, administrador | ✅ | 5 |
| `/api/ai-corrections/*` | admin*, auditor, gestor | ✅ | 3 |
| `/api/ai-topology/*` | admin*, gestor, tecnico | ✅ | 1 |
| `/api/ai-training/*` | admin*, gestor | ✅ | 14 |
| `/api/aihub/*` | admin*, atendimento, gestor | ✅ | 24 |
| `/api/alvaro/*` | admin*, auditor, gestor | ✅ | 7 |
| `/api/appointments/*` | admin*, atendimento, gestor, tecnico |  | 4 |
| `/api/atlaz/*` | admin*, auditor, financeiro, gestor |  | 15 |
| `/api/atlaz-financeiro/*` | admin*, auditor, financeiro, gestor |  | 11 |
| `/api/audit-log/*` | admin*, administrador, auditor |  | 10 |
| `/api/auth/*` | admin*, administrador |  | 9 |
| `/api/auth-recovery/*` | admin*, administrador |  | 1 |
| `/api/billing/*` | admin*, financeiro, gestor |  | 15 |
| `/api/boleto/*` | admin*, financeiro, gestor |  | 6 |
| `/api/branding/*` | admin*, administrador |  | 3 |
| `/api/budget/*` | admin*, financeiro, gestor |  | 10 |
| `/api/central-ia/*` | admin*, atendimento, auditor, gestor | ✅ | 23 |
| `/api/churn/*` | admin*, auditor, financeiro, gestor |  | 12 |
| `/api/client-errors/*` | admin*, administrador, auditor, gestor |  | 4 |
| `/api/cliente-portal/*` | portal próprio |  | 8 |
| `/api/clients-segments/*` | admin*, atendimento, gestor |  | 2 |
| `/api/clock-records/*` | admin*, atendimento, auditor, gestor |  | 8 |
| `/api/collab-assets/*` | admin*, gestor, tecnico |  | 11 |
| `/api/collaborator-auth/*` | portal próprio |  | 5 |
| `/api/collaborators/*` | admin*, administrador, gestor |  | 13 |
| `/api/connections/*` | admin*, gestor, tecnico |  | 4 |
| `/api/conselho-ia/*` | admin*, auditor, gestor | ✅ | 11 |
| `/api/contracts/*` | admin*, financeiro, gestor |  | 9 |
| `/api/copilot-ranking/*` | admin*, auditor, gestor | ✅ | 1 |
| `/api/cto-ports/*` | admin*, gestor, tecnico |  | 9 |
| `/api/customer/*` | portal próprio |  | 32 |
| `/api/dashboard/*` | admin*, atendimento, auditor, financeiro, gestor, tecnico |  | 5 |
| `/api/diagnostic/*` | admin*, auditor, gestor |  | 1 |
| `/api/disparo-ia/*` | admin*, gestor | ✅ | 14 |
| `/api/disparo-promo/*` | admin*, atendimento, gestor |  | 4 |
| `/api/drive/*` | admin*, administrador, gestor |  | 9 |
| `/api/email/*` | admin*, administrador |  | 1 |
| `/api/events/*` | PÚBLICO |  | 2 |
| `/api/feriados/*` | admin*, administrador, gestor |  | 5 |
| `/api/financeiro/*` | admin*, auditor, financeiro, gestor |  | 61 |
| `/api/fleet/*` | admin*, auditor, gestor, tecnico |  | 32 |
| `/api/fleet-portal/*` | PÚBLICO |  | 8 |
| `/api/fleet-tracking/*` | admin*, auditor, gestor, tecnico |  | 24 |
| `/api/geocode/*` | admin*, administrador, atendimento, auditor, financeiro, gestor, tecnico |  | 2 |
| `/api/geofences/*` | admin*, administrador, gestor |  | 3 |
| `/api/gestao-ia/*` | admin*, auditor, gestor |  | 9 |
| `/api/holerites/*` | admin*, auditor, financeiro, gestor |  | 20 |
| `/api/holidays/*` | admin*, administrador, gestor |  | 2 |
| `/api/integrations/*` | admin*, administrador |  | 3 |
| `/api/kpis/*` | auth-only |  | 2 |
| `/api/ligo-maps/*` | admin*, auditor, gestor, tecnico |  | 18 |
| `/api/locations/*` | admin*, atendimento, auditor, gestor, tecnico |  | 6 |
| `/api/logs/*` | admin*, administrador, auditor, gestor |  | 1 |
| `/api/lousa/*` | admin*, atendimento, auditor, gestor, tecnico |  | 99 |
| `/api/lousa-ai/*` | admin*, gestor, tecnico | ✅ | 3 |
| `/api/mass-messaging/*` | admin*, gestor |  | 10 |
| `/api/motor-ia/*` | admin*, administrador | ✅ | 13 |
| `/api/neo-chat/*` | admin*, atendimento, auditor, gestor | ✅ | 4 |
| `/api/neo-reports/*` | admin*, auditor, gestor | ✅ | 10 |
| `/api/network/*` | admin*, gestor, tecnico |  | 8 |
| `/api/notifications/*` | auth-only |  | 3 |
| `/api/oauth/*` | admin*, administrador |  | 3 |
| `/api/onboarding/*` | admin*, administrador |  | 5 |
| `/api/parceiro-portal/*` | portal próprio |  | 14 |
| `/api/parcerias/*` | admin*, atendimento, gestor |  | 21 |
| `/api/payments/*` | admin*, financeiro, gestor |  | 8 |
| `/api/plans/*` | admin*, financeiro, gestor |  | 14 |
| `/api/pracas/*` | admin*, administrador, gestor |  | 4 |
| `/api/pre-attendance/*` | admin*, atendimento, gestor |  | 10 |
| `/api/presidente-ia/*` | admin*, auditor, gestor | ✅ | 17 |
| `/api/preventive-os/*` | admin*, gestor, tecnico |  | 5 |
| `/api/projects/*` | admin*, gestor, tecnico |  | 13 |
| `/api/propostas/*` | admin*, atendimento, gestor |  | 6 |
| `/api/public/*` | auth-only |  | 1 |
| `/api/public-access/*` | admin*, administrador, gestor |  | 3 |
| `/api/purchases/*` | admin*, financeiro, gestor |  | 10 |
| `/api/push/*` | admin*, administrador, gestor |  | 5 |
| `/api/qr-token/*` | admin*, administrador, atendimento, gestor |  | 1 |
| `/api/r/*` | PÚBLICO |  | 2 |
| `/api/radius/*` | admin*, gestor, tecnico |  | 11 |
| `/api/rede-ia/*` | admin*, auditor, gestor, tecnico | ✅ | 105 |
| `/api/referral-campaign/*` | admin*, gestor |  | 3 |
| `/api/referrals/*` | admin*, atendimento, auditor, gestor |  | 11 |
| `/api/saas/*` | admin*, auditor, gestor |  | 9 |
| `/api/sales/*` | admin*, atendimento, gestor |  | 7 |
| `/api/scheduler/*` | admin*, administrador |  | 1 |
| `/api/secretaria/*` | admin*, auditor, gestor | ✅ | 8 |
| `/api/security-home/*` | admin*, administrador, gestor |  | 20 |
| `/api/security-portal/*` | PÚBLICO |  | 8 |
| `/api/sentinela-lousa/*` | admin*, auditor, gestor, tecnico | ✅ | 5 |
| `/api/server-time/*` | auth-only |  | 1 |
| `/api/settings/*` | admin*, administrador |  | 7 |
| `/api/site/*` | PÚBLICO |  | 6 |
| `/api/smartolt/*` | admin*, auditor, gestor, tecnico |  | 24 |
| `/api/smartolt-ai/*` | admin*, gestor, tecnico | ✅ | 11 |
| `/api/smartolt-push-ctos/*` | admin*, auditor, gestor, tecnico |  | 5 |
| `/api/stok/*` | admin*, auditor, gestor, tecnico |  | 66 |
| `/api/subscribers/*` | admin*, atendimento, auditor, financeiro, gestor |  | 20 |
| `/api/system/*` | admin*, administrador, auditor |  | 1 |
| `/api/tech-tracking/*` | PÚBLICO |  | 6 |
| `/api/timesheets/*` | admin*, auditor, financeiro, gestor |  | 4 |
| `/api/timesheets-collective/*` | admin*, auditor, financeiro, gestor |  | 1 |
| `/api/tv/*` | admin*, auditor, gestor |  | 4 |
| `/api/users/*` | admin*, administrador |  | 7 |
| `/api/utils/*` | auth-only |  | 2 |
| `/api/vehicle-checklist/*` | admin*, gestor, tecnico |  | 14 |
| `/api/voice/*` | admin*, atendimento, auditor, gestor | ✅ | 5 |
| `/api/wa-campaigns/*` | admin*, gestor |  | 7 |
| `/api/webhook/*` | PÚBLICO |  | 1 |
| `/api/whatsapp-baileys/*` | admin*, atendimento, auditor, gestor |  | 74 |
| `/api/whatsapp-channels/*` | admin*, administrador, gestor |  | 7 |
| `/api/whatsapp-meta/*` | admin*, administrador, gestor |  | 7 |
| `/api/whatsapp-twilio/*` | admin*, administrador, gestor |  | 7 |
| `/api/wifi/*` | admin*, gestor, tecnico |  | 15 |
| `/api/wifi-hotspot/*` | admin*, atendimento, gestor |  | 17 |

> `admin*` = `administrador` sempre passa em qualquer rota com role-rule (super-role).

---

## DELETE — audit_log obrigatório (77 endpoints)

| Método | Path | Roles |
|--------|------|-------|
| DELETE | `/api/admin/backup/{filename}` | administrador |
| DELETE | `/api/ai-config/key/{provider}` | administrador |
| DELETE | `/api/ai-corrections/{corr_id}` | auditor, gestor |
| DELETE | `/api/aihub/agents/{aid}` | atendimento, gestor |
| DELETE | `/api/aihub/integrations/{itype}` | atendimento, gestor |
| DELETE | `/api/appointments/{appt_id}` | atendimento, gestor, tecnico |
| DELETE | `/api/billing/invoices/{inv_id}` | financeiro, gestor |
| DELETE | `/api/boleto/logo` | financeiro, gestor |
| DELETE | `/api/budget/{bid}` | financeiro, gestor |
| DELETE | `/api/churn/manager-assistant/phones/{phone}` | auditor, financeiro, gestor |
| DELETE | `/api/client-errors/clear` | administrador, auditor, gestor |
| DELETE | `/api/clock-records/{rid}` | atendimento, auditor, gestor |
| DELETE | `/api/collab-assets/{asset_id}` | gestor, tecnico |
| DELETE | `/api/collaborators/{cid}` | administrador, gestor |
| DELETE | `/api/cto-ports/cto/{cto_id}` | gestor, tecnico |
| DELETE | `/api/feriados/{fid}` | administrador, gestor |
| DELETE | `/api/financeiro/bank-import/memory/{mem_id}` | auditor, financeiro, gestor |
| DELETE | `/api/financeiro/bills/{bill_id}` | auditor, financeiro, gestor |
| DELETE | `/api/financeiro/cash-accounts/{doc_id}` | auditor, financeiro, gestor |
| DELETE | `/api/financeiro/categories/{doc_id}` | auditor, financeiro, gestor |
| DELETE | `/api/financeiro/filiais/{doc_id}` | auditor, financeiro, gestor |
| DELETE | `/api/financeiro/movements/{mov_id}` | auditor, financeiro, gestor |
| DELETE | `/api/financeiro/payment-methods/{doc_id}` | auditor, financeiro, gestor |
| DELETE | `/api/financeiro/suppliers/{doc_id}` | auditor, financeiro, gestor |
| DELETE | `/api/fleet-tracking/geofences/{gid}` | auditor, gestor, tecnico |
| DELETE | `/api/fleet-tracking/portal-users/{uid}` | auditor, gestor, tecnico |
| DELETE | `/api/fleet-tracking/tenants/{tid}` | auditor, gestor, tecnico |
| DELETE | `/api/fleet-tracking/vehicles/{vid}` | auditor, gestor, tecnico |
| DELETE | `/api/fleet/fuel/{fuel_id}` | auditor, gestor, tecnico |
| DELETE | `/api/fleet/inspections/{inspection_id}` | auditor, gestor, tecnico |
| DELETE | `/api/fleet/transfers/{tx_id}` | auditor, gestor, tecnico |
| DELETE | `/api/fleet/vehicles/{vehicle_id}` | auditor, gestor, tecnico |
| DELETE | `/api/geofences/{gid}` | administrador, gestor |
| DELETE | `/api/holerites/{doc_id}` | auditor, financeiro, gestor |
| DELETE | `/api/holerites/{doc_id}/permanent` | auditor, financeiro, gestor |
| DELETE | `/api/ligo-maps/assets/{asset_id}` | auditor, gestor, tecnico |
| DELETE | `/api/ligo-maps/cables/{cable_id}` | auditor, gestor, tecnico |
| DELETE | `/api/ligo-maps/splices/{splice_id}` | auditor, gestor, tecnico |
| DELETE | `/api/locations/{cid}` | atendimento, auditor, gestor, tecnico |
| DELETE | `/api/lousa/tickets/{ticket_id}` | atendimento, auditor, gestor, tecnico |
| DELETE | `/api/mass-messaging/campaigns/{cid_id}` | gestor |
| DELETE | `/api/neo-reports/schedules/{sid}` | auditor, gestor |
| DELETE | `/api/parceiro-portal/promotions/{pid}` | — |
| DELETE | `/api/parcerias/partners/{pid}` | atendimento, gestor |
| DELETE | `/api/parcerias/promotions/{pid}` | atendimento, gestor |
| DELETE | `/api/plans/scheduled-adjustments/{sch_id}` | financeiro, gestor |
| DELETE | `/api/plans/{plan_id}` | financeiro, gestor |
| DELETE | `/api/pracas/{pid}` | administrador, gestor |
| DELETE | `/api/pre-attendance/promos/{promo_id}` | atendimento, gestor |
| DELETE | `/api/projects/{project_id}` | gestor, tecnico |
| DELETE | `/api/projects/{project_id}/checklist/{item_id}` | gestor, tecnico |
| DELETE | `/api/projects/{project_id}/files/{file_id}` | gestor, tecnico |
| DELETE | `/api/propostas/{prop_id}` | atendimento, gestor |
| DELETE | `/api/public-access/tokens/{token_id}` | administrador, gestor |
| DELETE | `/api/purchases/{purchase_id}` | financeiro, gestor |
| DELETE | `/api/radius/nas/{nas_id}` | gestor, tecnico |
| DELETE | `/api/rede-ia/bairros/{bid}` | auditor, gestor, tecnico |
| DELETE | `/api/rede-ia/cables/{cable_id}` | auditor, gestor, tecnico |
| DELETE | `/api/rede-ia/ces/{ce_id}` | auditor, gestor, tecnico |
| DELETE | `/api/rede-ia/ctos/{cto_id}` | auditor, gestor, tecnico |
| DELETE | `/api/referral-campaign/config` | gestor |
| DELETE | `/api/saas/admin/companies/{cid}` | auditor, gestor |
| DELETE | `/api/security-home/portal-users/{uid}` | administrador, gestor |
| DELETE | `/api/security-home/sensors/{sensor_id}` | administrador, gestor |
| DELETE | `/api/security-home/sites/{sid}` | administrador, gestor |
| DELETE | `/api/subscribers/{sid}` | atendimento, auditor, financeiro, gestor |
| DELETE | `/api/subscribers/{sid}/phones/{phone_id}` | atendimento, auditor, financeiro, gestor |
| DELETE | `/api/users/{uid}` | administrador |
| DELETE | `/api/vehicle-checklist/{chk_id}` | gestor, tecnico |
| DELETE | `/api/vehicle-checklist/{chk_id}/attachment/{idx}` | gestor, tecnico |
| DELETE | `/api/whatsapp-baileys/conversation/{phone}/unlink-subscriber` | atendimento, auditor, gestor |
| DELETE | `/api/whatsapp-baileys/conversations/{phone}` | atendimento, auditor, gestor |
| DELETE | `/api/whatsapp-baileys/isabella/fragments/{fragment_id}` | atendimento, auditor, gestor |
| DELETE | `/api/whatsapp-baileys/quick-images/{img_id}` | atendimento, auditor, gestor |
| DELETE | `/api/wifi-hotspot/campaigns/{cid_param}` | atendimento, gestor |
| DELETE | `/api/wifi-hotspot/venues/{venue_id}` | atendimento, gestor |
| DELETE | `/api/wifi/subscriber/{sid}/link-onu` | gestor, tecnico |

---

## EXPORT — audit_log obrigatório (10 endpoints)

Considera paths com qualquer um destes hints:
`/export, /download, .pdf, .csv, .xlsx, /pdf-reports`.

| Método | Path | Roles |
|--------|------|-------|
| GET | `/api/admin/backup/download/{filename}` | administrador |
| GET | `/api/audit-log/export.csv` | administrador, auditor |
| GET | `/api/conselho-ia/diagnostic-report.pdf` | auditor, gestor |
| GET | `/api/ligo-maps/export/kml` | auditor, gestor, tecnico |
| GET | `/api/ligo-maps/export/summary` | auditor, gestor, tecnico |
| GET | `/api/projects/{project_id}/files/{file_id}/download` | gestor, tecnico |
| GET | `/api/rede-ia/ctos/{cto_id}/pdf.pdf` | auditor, gestor, tecnico |
| GET | `/api/rede-ia/map/export-kmz` | auditor, gestor, tecnico |
| GET | `/api/stok/history/export` | auditor, gestor, tecnico |
| POST | `/api/whatsapp-baileys/conversation/{phone}/export-pdf` | atendimento, auditor, gestor |

---

## IA — rate-limit obrigatório (291 endpoints)

Limite padrão: **30 req/min**, **1000 req/dia** por usuário (5x por empresa). Configurável via env `IA_RATE_PER_MIN`/`IA_RATE_PER_DAY`.

- `/api/ai/*` — 7 endpoints
- `/api/ai-config/*` — 5 endpoints
- `/api/ai-corrections/*` — 3 endpoints
- `/api/ai-topology/*` — 1 endpoints
- `/api/ai-training/*` — 14 endpoints
- `/api/aihub/*` — 24 endpoints
- `/api/alvaro/*` — 7 endpoints
- `/api/central-ia/*` — 23 endpoints
- `/api/conselho-ia/*` — 11 endpoints
- `/api/copilot-ranking/*` — 1 endpoints
- `/api/disparo-ia/*` — 14 endpoints
- `/api/lousa-ai/*` — 3 endpoints
- `/api/motor-ia/*` — 13 endpoints
- `/api/neo-chat/*` — 4 endpoints
- `/api/neo-reports/*` — 10 endpoints
- `/api/presidente-ia/*` — 17 endpoints
- `/api/rede-ia/*` — 105 endpoints
- `/api/secretaria/*` — 8 endpoints
- `/api/sentinela-lousa/*` — 5 endpoints
- `/api/smartolt-ai/*` — 11 endpoints
- `/api/voice/*` — 5 endpoints

---

## Auth-only legítimos (12 endpoints)

Endpoints onde QUALQUER usuário autenticado pode acessar (consulta o próprio dado, utilitários).

- `GET /api/`
- `POST /api/auth/change-my-password`
- `GET /api/auth/me`
- `GET /api/kpis/churn-reasons`
- `POST /api/kpis/churn-reasons/ai-insights`
- `GET /api/notifications`
- `POST /api/notifications/read-all`
- `POST /api/notifications/{nid}/read`
- `GET /api/public/os-validation-toggles/{collab_id}`
- `GET /api/server-time`
- `GET /api/utils/cep/{cep}`
- `GET /api/utils/validate-document`

---

## Públicos (sem auth)

- `/api/about`
- `/api/auth/google-login`
- `/api/auth/login`
- `/api/auth/logout`
- `/api/branding/public`
- `/api/collab-assets/public/by-collaborator/{cid}`
- `/api/collab-assets/public/romaneio/{cid}`
- `/api/collab-assets/public/sign`
- `/api/events/stats`
- `/api/events/stream`
- `/api/fleet-portal/auth/login`
- `/api/oauth/drive/callback`
- `/api/payments/webhook/asaas`
- `/api/r/{code}/info`
- `/api/r/{code}/submit`
- `/api/security-portal/auth/login`
- `/api/site/config`
- `/api/site/leads`
- `/api/site/leads/{lead_id}`
- `/api/site/plans`
- `/api/tech-tracking/public/ping/{collab_id}`
- `/api/tech-tracking/public/trail/{collab_id}`
- `/api/tech-tracking/public/trail/{collab_id}/snap`
- `/api/webhook/stripe`
- `/api/whatsapp-baileys/inbound`
- `/api/whatsapp-baileys/inbound-call`
- `/api/whatsapp-twilio/webhook`

---

## Roles do sistema

| Role | Descrição |
|------|-----------|
| `administrador` | Super-admin. Passa em **TODAS** as rotas. |
| `gestor` | Gerência operacional. Tem acesso a financeiro, IA, lousa, frota, clientes. |
| `financeiro` | Apenas módulos de billing, payments, boleto, atlaz, holerites. |
| `auditor` | Read-only em quase tudo (relatórios, diagnóstico, audit-log). |
| `tecnico` | Operação de campo: lousa, OLT, CTOs, checklists, frota. |
| `atendimento` | Atendimento ao cliente: chat, pré-atendimento, agendamentos. |
| `colaborador` | Mobile / ponto eletrônico (acesso mínimo). |

> Roles não-staff (clientes/parceiros/seg. residencial) usam JWT próprio com seus próprios endpoints (portais `/api/customer`, `/api/cliente-portal`, `/api/parceiro-portal`, `/api/security-portal`, `/api/fleet-portal`).

---

## Como adicionar/alterar permissão

1. Edite `/app/backend/rbac_policy.py` e ajuste `ROLE_RULES`.
2. Rode `python -m scripts.audit_rbac_coverage` para validar.
3. Rode `python -m scripts.generate_rbac_matrix` para regenerar este arquivo.
4. Rode `pytest backend/tests/test_rbac_sprint2.py` para garantir que cobertura ≥ 70% e nenhum endpoint crítico vaza.
