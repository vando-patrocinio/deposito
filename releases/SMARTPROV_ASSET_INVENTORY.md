# SmartProv — ASSET INVENTORY (V1.0)

> Gerado em **2026-06-09** a partir de scan automatizado do código.
> Subordinado a `SYSTEM_CONSTITUTION.md`.

---

## 0. Resumo Executivo

| Métrica | Valor |
|---------|-------|
| **Routes backend (`backend/routes/*.py`)** | 160 arquivos |
| **Services backend (`backend/services/*.py`)** | 135 arquivos |
| **Componentes frontend (`frontend/src/**/*.{js,jsx}`)** | 374 arquivos |
| **Testes pytest (`backend/tests/test_*.py`)** | 240 arquivos |
| **Collections MongoDB referenciadas** | 120 únicas |
| **Variáveis de ambiente referenciadas** | 91 únicas |
| **Routes registradas no `server.py`** | 156 / 160 (97,5%) |
| **Tabs/IDs no `App.js` NAV_GROUPS** | 70 IDs únicos |
| **Stashes git preservados (safety net)** | 10 |
| **Tamanho `backend/routes/`** | 11 MB |
| **Tamanho `backend/services/`** | 4,3 MB |
| **Tamanho `frontend/src/`** | 7,8 MB |

---

## 1. Inventário de Routes (160 arquivos)

### 1.1 — Grupo AI Center (23 arquivos)

```
ai_center_alvaro.py            ai_center_alvaro_v5.py
ai_center_autonomous.py        ai_center_blockers.py
ai_center_cash.py              ai_center_data_quality.py
ai_center_failure_risk.py      ai_center_financial.py
ai_center_home.py              ai_center_homologation.py
ai_center_isabella.py          ai_center_knowledge_graph.py
ai_center_multitenant.py       ai_center_nervous_system.py
ai_center_observability.py     ai_center_predictive.py
ai_center_revenue.py           ai_center_smartolt_twin.py
ai_center_v51.py               ai_center_v6.py
ai_center_v62.py               ai_center_v7.py
ai_center_v80.py
```

### 1.2 — Demais grupos (137 arquivos)

```
admin, atlaz, atlaz_financeiro, audit_log_panel, auth, backup,
billing, central_ia, churn_*, cliente, collaborators, conselho_ia,
contracts, customer, dashboard, drive_backup, email, espelho,
estoque, events, feriados, financeiro_ops, fleet_*, holerite,
indique, integrations, lgpd, logs, lousa, lousa_admin, lousa_score,
loyalty, manager_audit, mass_messaging, motor_ia_admin, neo_reports,
notifications, observability, oauth, ops, parceria, payments, plans,
ponto, pracas, pre_attendance, predictions, preventive_os, projetos,
radius, rede_ia, referrals, sales_funnel, sales_outreach,
sales_leads, security_home, sentinela_lousa, settings, smartolt_*,
subscribers, tickets, tickets_filters, tv, users, vehicle_checklist,
vehicle_silhouettes, wa_baileys, whatsapp_*, wifi_hotspot,
ticket_quality (⚠️ órfão — ver LOST_FEATURE_CHECK)
```

> Lista completa: `releases/inventory_raw/routes.txt`

---

## 2. Inventário de Services (135 arquivos)

### 2.1 — Top 15 por tamanho

| Service | Tamanho |
|---------|---------|
| `secretaria_tools.py` | 46 KB |
| `motor_ia.py` | 44 KB |
| `drive_backup.py` | 41 KB |
| `observability_twin.py` | 39 KB |
| `autonomous_engine.py` | 37 KB |
| `subscriber_connection.py` | 37 KB |
| `ops_v51.py` | 30 KB |
| `secretaria_ia.py` | 28 KB |
| `v8_1_simulator.py` | 27 KB |
| `company_v6.py` | 26 KB |
| `presidente_ia.py` | 26 KB |
| `smartolt_ai.py` | 25 KB |
| `v8_3_causality.py` | 24 KB |
| `alvaro_ai.py` | 24 KB |
| `v7_2_2_data_quality.py` | 23 KB |

### 2.2 — Por família

- **Motor IA / Autonomous:** `motor_ia.py`, `autonomous_engine.py`, `presidente_ia.py`, `alvaro_ai.py`, `secretaria_ia.py`, `aihub_*`
- **Action → Cash (V7):** `v7_2_revenue.py`, `v7_2_2_data_quality.py`, `execution_v7.py`
- **Causality (V8):** `v8_1_simulator.py`, `v8_2_first_cash.py`, `v8_3_causality.py`, `v8_4_cohort.py`
- **Observability:** `observability_twin.py`, `smartolt_ai.py`, `smartolt_*`
- **Company / Multi-tenant (V6):** `company_v6.py`, `alvaro_v5.py`, `failure_risk.py`
- **WhatsApp:** `homologation.py`, `wa/sidecar.py`, demais sob `services/wa/`
- **Integrações externas:** `atlaz_*`, `asaas_*`, `twilio_*`, `stripe_*`, `resend_*`

> Lista completa: `releases/inventory_raw/services.txt`

---

## 3. Inventário Frontend (374 arquivos)

### 3.1 — Componentes AI Center · OS (críticos)

| Arquivo | Linhas | Função |
|---------|--------|--------|
| `AICenterOS.jsx` | 582 | Container do AI Center · OS (20+ abas) |
| `PresidenteIaPanel.js` | 1008 | Aba Presidente IA |
| `WarRoomPanel.js` | 271 | Sala de Guerra |
| `MultiTenantPanel.jsx` | 162 | Multi-Tenant Blindagem |
| `IsabellaPanel.jsx` | 239 | Isabella IA Revenue Engine |
| `KnowledgeGraphPanel.jsx` | 142 | Knowledge Graph + XAI |
| `SmartOLTTwinPanel.jsx` | 378 | SmartOLT Digital Twin |
| `NervousSystemPanel.jsx` | 367 | Sistema Nervoso IA |
| `RevenueOpsPanel.jsx` | 473 | RevenueOps IA · R$ |
| `LgpdPortalPanel.js` | 330 | LGPD Portal |
| `AuditTrailPanel.js` | — | Audit Trail |
| `CtoCommandCenter.jsx` | — | Centro de Comando IA |
| `AutonomousCenterPanel.jsx` | — | Autonomous Center |
| `PredictivePanel.jsx` | 197 | SmartOLT Preditivo |
| `RealRevenuePanel.jsx` | 205 | Real Revenue · ROI |

### 3.2 — Sidebar (App.js NAV_GROUPS — 70 IDs)

**Grupo "Sistema" (16 items):** users, motor-ia, conselho-ia, warroom, **ai-center**, cto-command, revenue-ops, data-quality, nervous-system, smartolt-twin, audit-trail, lgpd-portal, backend-health, settings, platform, backup

**Grupo "Operação":** dashboard, lousa, estoque, projects, radius, contracts, payments, site, …

**Grupo "Inteligência":** ai-ranking, ai-corrections, central-ia, rede-ia, smartolt-push, atendimento, alvaro-ia, alvaro-command-center, observability-twin, mass-messaging, wa-campaigns, pre-attendance, sales-funnel

> Lista completa: `releases/inventory_raw/frontend.txt`

---

## 4. Inventário de Collections MongoDB (120 únicas)

### Tier 1 — Operacional crítica

`subscribers`, `tickets`, `subscriber_invoices`, `contracts`, `appointments`, `collaborators`, `users`, `plans`, `smartolt_onus`, `ctos`, `motor_ia_events`, `motor_ia_decisions`, `motor_ia_actions`, `motor_ia_outcomes`, `motor_ia_learnings`, `motor_ia_autonomous_cycles`

### Tier 2 — Analítica/inteligência

`motor_ia_subscriber_scores`, `motor_ia_revenue_attribution`, `motor_ia_cohorts`, `motor_ia_cohort_members`, `motor_ia_causality`, `motor_ia_analysis`, `knowledge_graph_nodes`, `knowledge_graph_edges`, `observability_incidents`, `audit_log`, `ai_evaluations`, `ai_corrections`, `ai_training_kb`, `ai_training_runs`, `ai_training_scenarios`, `ai_training_schedule`, `ai_training_tests`, `ai_training_decision_matrix`, `ai_insights`, `ai_coaching`, `aihub_agents`, `aihub_cache`, `aihub_calls`, `aihub_coaching`, `aihub_conversations`, `aihub_evaluations`

### Tier 3 — WhatsApp / atendimento

`wa_outbox`, `wa_messages_sent`, `wa_messages_inbound`, `whatsapp_conversations`, `whatsapp_messages`, `atlaz_clients_cache`, `atlaz_invoices_cache`, `isabella_*`, `atendimento_*`

### Tier 4 — Operacional auxiliar

`fleet_*`, `security_*`, `parceria_*`, `referrals`, `loyalty_*`, `wifi_hotspot_*`, `notifications`, `holidays`, `conselho_ia_*`, `preventive_*`, `smartolt_push_*`, `radius_*`, `grafana_dashboards`, `grafana_folders`, `grafana_datasources`, `grafana_alerts`, `ai_agent_switches`, `ai_agent_switch_history`, …

> Lista completa: `releases/inventory_raw/collections.txt`

---

## 5. Integrações Externas

| Integração | Arquivos | Status | Gateway |
|-----------|----------|--------|---------|
| **WhatsApp Baileys** | 101 | ✅ ATIVO (homolog) | `services/homologation.py` |
| **SmartOLT** | 151 | ✅ ATIVO | `services/smartolt_*` |
| **Atlaz (CRM/ISP)** | 84 | ✅ ATIVO | `services/atlaz_*` |
| **Anthropic Claude** | 38 | ✅ ATIVO | `emergentintegrations` |
| **emergentintegrations** | 31 | ✅ ATIVO | núcleo LLM/imagem |
| **OpenAI** | 25 | ✅ ATIVO | `emergentintegrations` |
| **Twilio** | 18 | ✅ ATIVO (backup WA) | `routes/whatsapp_*` |
| **Resend (e-mail)** | 13 | ✅ ATIVO | `routes/email*` |
| **Asaas (pagamento BR)** | 12 | 🟡 CONFIGURADO (sem chave) | `routes/asaas*` |
| **Stripe** | 8 | ✅ ATIVO (test mode) | `routes/billing*` |
| **Zabbix** | 4 | 🟠 MOCK (sem credenciais) | `services/observability_twin.py` |
| **Grafana** | 4 | 🟠 MOCK (sem credenciais) | `services/observability_twin.py` |

---

## 6. Variáveis de Ambiente (91 únicas)

### Críticas (não podem faltar)

`MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `EMERGENT_LLM_KEY`, `WA_SIDECAR_URL`, `WA_INBOUND_TOKEN`, `HOMOLOG_MODE`

### Integrações

`ANTHROPIC_API_KEY`, `STRIPE_API_KEY`, `ASAAS_API_KEY`, `RESEND_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_DRIVE_REDIRECT_URI`

### V9 (Fase Market Validation)

`CAUSALITY_PILOT_PHONES`, `ZABBIX_URL`, `ZABBIX_API_TOKEN`, `ZABBIX_USER`, `ZABBIX_PASSWORD`, `ZABBIX_VERIFY_SSL`, `GRAFANA_URL`, `GRAFANA_SERVICE_ACCOUNT_TOKEN`, `GRAFANA_ORG_ID`, `GRAFANA_VERIFY_SSL`

### Auth/Seed

`SUPER_ADMIN_EMAILS`, `ADMIN_PASSWORD`, `AUDITOR_PASSWORD`, `SEED_SECRET`, `AUTH_RECOVERY_KEY`

### Tokens de Ingest

`FLEET_INGEST_TOKEN`, `SECURITY_INGEST_TOKEN`, `REDE_IA_QR_SECRET`, `REDE_IA_PUBLIC_SECRET`

### Outras

`CORS_ORIGINS`, `COOKIE_SECURE`, `COOKIE_SAMESITE`, `PUBLIC_FRONTEND_URL`, `PUBLIC_BACKEND_URL`, `PUBLIC_BASE_URL`, `ALLOW_MOCK_MODULES`, `APP_TZ`, `BACKUP_DIR`, `BACKUP_USE_BINARIES`, …

> Lista completa: `releases/inventory_raw/env_vars.txt`

---

## 7. Testes (240 arquivos)

Cobertura observada em 2026-06-09:

| Bateria | Status |
|---------|--------|
| `test_homologation.py` (10 testes) | ✅ 10/10 PASS |
| `test_v9_p3_whitelist.py` (6 testes) | ✅ 6/6 PASS |
| `test_observability.py` (9 testes) | ✅ 9/9 PASS |
| `test_lousa_merge.py` | ⚠️ falhas crônicas (dívida técnica) |
| Demais 237 baterias | não rodadas neste ciclo |

---

## 8. Safety Net — Git Stashes (10 preservados)

Backup automático do `lint-staged` — **NÃO DROPAR sem autorização**:

| Slot | ID | Origem |
|------|-----|--------|
| `stash@{0}` | `afd90c03` | lint-staged automatic backup |
| `stash@{1}` | `c6aee43e` | lint-staged automatic backup |
| `stash@{2}` | `a28ce30d` | lint-staged automatic backup |
| `stash@{3}` | `bfc959ae` | lint-staged automatic backup |
| `stash@{4}` | `e67a6e39` | lint-staged automatic backup |
| `stash@{5}` | `ffd91820` | lint-staged automatic backup |
| `stash@{6}` | `cb656768` | lint-staged automatic backup |
| `stash@{7}` | `40815fb5` | lint-staged automatic backup |
| `stash@{8}` | `e0d6f330` | lint-staged automatic backup |
| `stash@{9}` | `334ecf44` | lint-staged automatic backup |

`stash@{0}` contém 282 arquivos / +62.235 linhas — todo o AI Center · OS.

---

## 9. Listas brutas (raw)

Disponíveis em `/app/releases/inventory_raw/`:

- `routes.txt` (160 entradas)
- `services.txt` (135)
- `frontend.txt` (374)
- `tests.txt` (240)
- `collections.txt` (120)
- `env_vars.txt` (91)
- `integrations.txt`
- `routes_orphans.txt` (4 entradas — auditadas em `LOST_FEATURE_CHECK.md`)

---

**Próxima geração obrigatória:** após cada milestone ou a cada 30 dias.

**Script de regeneração:** ver `RELEASE_LOCK.md` item 5.
