# SmartProv — ARCHITECTURE (Estado Corrente)

> Subordinado a `SYSTEM_CONSTITUTION.md` e `ARCHITECTURE_LOCK.md`.
> Documento descritivo (estado atual). Para travas, ver `ARCHITECTURE_LOCK.md`.

**Versão arquitetural:** V9.4 — Prova de Mercado
**Atualizado em:** 2026-06-09

---

## 1. Visão Geral

SmartProv é uma plataforma operacional **multi-tenant** para provedores de internet (ISPs) brasileiros. Une 4 camadas:

```
┌─────────────────────────────────────────────────────────────┐
│  Camada de Operação                                         │
│  • Lousa (chamados / OS) • Smart Field Ops • Frota          │
│  • Estoque • Acompanhamento • RADIUS / PPPoE                │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│  Camada Financeira (Action → Cash)                          │
│  • Faturamento • Reconciliação • Dunning                    │
│  • Receita atribuída por evento (não estimativa)            │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│  Camada de Inteligência (AI Center · OS)                    │
│  • Presidente IA • Sala de Guerra • Alvaro Diretor          │
│  • Isabella IA (Revenue Engine) • Knowledge Graph           │
│  • Sistema Nervoso • Data Quality • Predictions             │
│  • Cohorts A/B (Causality Engine) • Action Center           │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│  Camada de Observabilidade (Observability Twin)             │
│  • Zabbix (alertas técnicos) • Grafana (dashboards)         │
│  • SmartOLT Digital Twin (rede óptica)                      │
│  • Health Score 0-100 / 5 níveis                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Stack Técnico

### Backend
- **Linguagem:** Python 3.11
- **Framework:** FastAPI + Uvicorn
- **DB Driver:** Motor (async MongoDB) 3.3.1
- **Scheduler:** APScheduler
- **WhatsApp:** Baileys (Node sidecar local porta 3002)
- **LLMs:** `emergentintegrations` (Anthropic Claude, OpenAI, Gemini)
- **Auth:** JWT (HS256)
- **Outras integrações:** Twilio, Stripe, Asaas, Resend, Atlaz, SmartOLT, Zabbix, Grafana

### Frontend
- **Linguagem:** JavaScript/JSX (React 18)
- **Bundler:** CRACO (Create React App customizado)
- **Estilização:** Tailwind CSS + Shadcn/UI
- **State:** React Context (sem Redux)
- **HTTP:** axios (via `client` em `src/api.js`)
- **Toast:** sonner

### Infraestrutura
- **Container:** Kubernetes pod (Emergent preview)
- **Process manager:** supervisor
- **DB:** MongoDB local (porta 27017)
- **Reverse proxy:** Kubernetes ingress (/api/* → :8001, demais → :3000)

---

## 3. Topologia de Processos (Supervisor)

| Processo | Porta | Status atual |
|---------|-------|--------------|
| `backend` | 0.0.0.0:8001 | RUNNING |
| `frontend` | 0.0.0.0:3000 | RUNNING |
| `mongodb` | 27017 | RUNNING |
| `whatsapp-service` (4x) | 3002 | RUNNING |
| `nginx-code-proxy` | (auxiliar) | RUNNING |

---

## 4. Módulos Funcionais (Mapa)

### 4.1 — Operação
| Módulo | Rota | Frontend |
|--------|------|----------|
| Painel Gestor | `/api/dashboard*` | `App.js#dashboard` |
| Lousa (Chamados) | `/api/lousa*` | `LousaAdminPanel.js`, `LousaMobile.js` |
| Estoque | `/api/estoque*` | (panel referenciado) |
| Frota | `/api/fleet*` | `fleet/` (sub-app) |
| Segurança Residencial | `/api/security_home*` | `security/` (sub-app) |

### 4.2 — Comercial
| Módulo | Rota | Frontend |
|--------|------|----------|
| Atendimento WhatsApp | `/api/whatsapp-baileys*` | `WhatsAppChatLayout.js` |
| Parcerias | `/api/parceria*` | `parceria/` (sub-app) |
| Indique e Ganhe | `/api/customer*` | `cliente/` |
| Clientes Fidelidade | `/api/loyalty*` | `LoyaltyPanel.js` |
| WiFi Hotspot | `/api/wifi-hotspot*` | `WifiHotspotPanel.js` |

### 4.3 — AI Center · OS (`AICenterOS.jsx`)
| Aba | Rota Backend |
|-----|--------------|
| Presidente IA | `/api/ai-center/home*` |
| Sala de Guerra | `/api/ai-center/cash/war-room*` |
| Isabella IA | `/api/ai-center/isabella*` |
| Álvaro Diretor | `/api/ai-center/alvaro*` |
| Knowledge Graph | `/api/ai-center/knowledge_graph*` |
| Data Quality | `/api/ai-center/data_quality*` |
| Sistema Nervoso | `/api/ai-center/nervous_system*` |
| SmartOLT Twin | `/api/ai-center/smartolt_twin*` |
| Decision Center | `/api/ai-center/autonomous*` |
| Action Center | `/api/ai-center/v80*` |
| Predictions | `/api/ai-center/predictive*` |
| Multi-Tenant | `/api/ai-center/multitenant*` |
| Audit Trail | `/api/ai-center/audit*` |

### 4.4 — Causality Engine
| Componente | Local |
|-----------|-------|
| Cohorts A/B | `services/v8_3_causality.py`, `services/v8_4_cohort.py` |
| Lift / Wilson CI95 | `services/v8_3_causality.py` |
| Whitelist piloto | `services/homologation.py::is_whitelisted` |

### 4.5 — Observability Twin
| Componente | Local |
|-----------|-------|
| Zabbix Connector | `services/observability_twin.py::ZabbixConnector` |
| Grafana Connector | `services/observability_twin.py::GrafanaConnector` |
| Knowledge Graph builder | `services/observability_twin.py::persist_knowledge_graph` |
| Pipeline completo | `services/observability_twin.py::run_full_pipeline` |

---

## 5. Fluxo Crítico: Action → Cash → Causality

```
Evento operacional (ticket, OS, ONU down, overdue invoice)
        │
        ▼
Motor IA (services/autonomous_engine.py)
  • _analyze_event → motor_ia_analysis
  • _decide → motor_ia_decisions
  • _execute_action → motor_ia_actions
  • _observe_outcome → motor_ia_outcomes
  • _learn → motor_ia_learnings
        │
        ▼
Action via Gateway WhatsApp (services/homologation.py)
  • HOMOLOG_MODE=true → redirecionado TEST_PHONE
  • Whitelist → envio real ao número, environment=causality_pilot
        │
        ▼
Outcome marcado com environment + actual_BRL
        │
        ▼
Reconciliação financeira (services/v7_2_revenue.py)
  • Match: motor_ia_outcomes.subscriber_id ↔ subscriber_invoices
  • Atribuição → motor_ia_revenue_attribution
        │
        ▼
Cohort A/B (services/v8_3_causality.py, v8_4_cohort.py)
  • Pareamento por strata
  • Wilson CI95 lift
  • Resultado → motor_ia_causality
```

---

## 6. Métricas-chave do Sistema

| Métrica | Coleção origem | Atualização |
|---------|----------------|-------------|
| Receita atribuída | `motor_ia_outcomes.actual_BRL` | tempo real |
| Lift causal | `motor_ia_causality` | por cohort fechado |
| Adoção Smart Field | `tickets.completion_data` | telemetria contínua |
| Health Score | `observability_twin.observability_health_score()` | sob demanda (cache 5min) |
| Data Quality % | `v7_2_2_data_quality.executive_audit()` | diário |
| Disponibilidade | `wa_outbox`, `wa_messages_sent` | tempo real |

---

## 7. Ciclos Operacionais (Schedulers)

| Worker | Intervalo | Função |
|--------|-----------|--------|
| `ai_preventive` | a cada scan | Sugestões preventivas |
| `central_ia` | 900s (15min) | Refresh inteligência central |
| `smartolt_ai` | 30s | Análise rede óptica |
| `lousa_ai_triagem` | 60s | Triagem automática de chamados |
| `churn_scheduler` | 60s | Detecção de churn iminente |
| `conselho_ia_cron` | 3600s (1h) | Conselho IA estratégico |
| `readjustment_scheduler` | 3600s | Reajustes contratuais |
| `ai_training_scheduler` | 60s | Retreino de modelos |
| `outage_worker` | 600s (10min) | Detecção de outage agregada |
| `aging_worker` | 900s (15min) | Aging contratual |
| `mass_messaging` | (event) | Disparos em massa |
| `drive_backup` | (cron) | Backup para Google Drive |
| `preventive_os` | (daily) | OS preventiva |
| `sn_photo_worker` | (event) | Foto + análise visual (Claude vision) |
| `vlan_sync` | 3600s | Sincronização VLAN SmartOLT |
| `smartolt_push_ctos` | 60s | Push de CTOs degradadas |

---

## 8. Segurança e Compliance

- **JWT:** HS256, `JWT_SECRET` em `.env`.
- **HOMOLOG_MODE:** failsafe padrão (ver ADR-0001).
- **Multi-tenancy:** `company_id` obrigatório (ver ADR-0002).
- **LGPD:** termo em `/app/docs_v9_commercial/03_lgpd.md` (DRAFT, sujeito à revisão jurídica).
- **Auditoria:** `audit_log` collection + `motor_ia_events` para tudo que é estratégico.
- **Tokens de ingest:** `FLEET_INGEST_TOKEN`, `SECURITY_INGEST_TOKEN` (rotacionáveis).

---

## 9. Pontos de Extensão Conhecidos

- **Observability Real:** popular `ZABBIX_URL/TOKEN` + `GRAFANA_URL/TOKEN` → conector troca automaticamente para real.
- **Piloto causal:** popular `CAUSALITY_PILOT_PHONES` → liberação cirúrgica.
- **Mongo backup binário:** **gap conhecido** (ver `RELEASE_LOCK.md` item 7).

---

**Próxima atualização obrigatória:** ao concluir Fase 9.2 (30 dias de piloto) ou em emenda arquitetural.
