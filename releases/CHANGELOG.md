# SmartProv — CHANGELOG

> Histórico cronológico de mudanças. Subordinado a `SYSTEM_CONSTITUTION.md`.
> Cada milestone aqui deve ter "Save to GitHub" correspondente.

Formato baseado em [Keep a Changelog](https://keepachangelog.com/).

---

## [Unreleased]

### Adicionado (Safety P0 — 2026-06-09)
- `services/kill_switch.py` — Kill Switch (global, whatsapp, ai_actions, scheduler)
- `services/mongo_backup.py` — mongodump --gzip wrapper + rotação
- `services/secrets_vault.py` — Vault Fernet criptografado
- `routes/admin_safety.py` — 9 endpoints REST (super_admin obrigatório)
- `ops/backup/mongo_backup.sh` + `mongo_restore.sh` — scripts shell
- `governance/SAFETY_LOCK.md` — runbook completo das 3 medidas
- `backend/tests/test_safety_p0.py` — 6 testes (kill switch + vault + backup)

### Alterado (mínimo)
- `services/homologation.py::safe_send_whatsapp` — hook 1 try/except no topo para respeitar kill switch `whatsapp` antes de qualquer envio (failopen)
- `server.py` — registrado `admin_safety` (156 → 157 routes)

### Adicionado
- `/app/governance/SYSTEM_CONSTITUTION.md` — Constituição V1.0 do sistema
- `/app/governance/ARCHITECTURE_LOCK.md` — travas estruturais
- `/app/governance/DATABASE_LOCK.md` — schema e collections protegidas
- `/app/governance/RELEASE_LOCK.md` — processo de release
- `/app/releases/ARCHITECTURE.md` — arquitetura corrente
- `/app/releases/DECISIONS.md` — registro de decisões arquiteturais (ADRs)
- `/app/releases/SMARTPROV_ASSET_INVENTORY.md` — inventário completo
- `/app/releases/SMARTPROV_LOST_FEATURE_CHECK.md` — auditoria de órfãos

### Princípio adotado
- **Feature Freeze (Fase 9)**: zero UI nova sem ROI documentado.

---

## [v9.4-market-validation] — 2026-06-09

### Adicionado (V9.4 — Prova de Mercado)
- `docs_v9_commercial/01_landing.html` — landing institucional técnica
- `docs_v9_commercial/02_sla.md` — SLA base 30d
- `docs_v9_commercial/03_lgpd.md` — termo LGPD (sujeito à revisão jurídica)
- `docs_v9_commercial/04_contrato_saas.md` — contrato SaaS base (sujeito à revisão jurídica)
- `docs_v9_commercial/05_case_study_template.md` — template de case study
- `docs_v9_commercial/OBSERVABILITY_REAL_SETUP.md` — runbook Zabbix/Grafana
- `docs_v9_commercial/README.md` — índice do pacote

### Adicionado (V9 P3 — Whitelist Causal)
- `backend/services/homologation.py`: `_parse_whitelist()` + `is_whitelisted()`
- `backend/services/homologation.py`: branch `pilot_real` em `safe_send_whatsapp`
- Evento `CAUSALITY_PILOT_REAL_SEND` em `motor_ia_events`
- `wa_messages_sent.kind = "causality_pilot_send"`
- `environment="causality_pilot"` em outcomes do piloto
- `backend/tests/test_v9_p3_whitelist.py` — 6/6 PASS

### Recuperado (incidente lint-staged)
- 282 arquivos / +62.235 linhas restaurados via `git stash apply stash@{0}`
- `AICenterOS.jsx` (582 linhas) + 14 componentes derivados
- 23 routes do AI Center (alvaro, autonomous, cash, data_quality, etc.)
- 5 conflitos cirurgicamente resolvidos

### Corrigido (legacy schema)
- `homologation.py::simulate_full_pipeline` — chaves `outcome_id`/`action_id` em vez de `cycle["outcome_id"]`
- `homologation.py::reconcile_outbox` — filtro por `outcome_id` em vez de `id`
- `test_homologation.py` — 4 testes atualizados ao novo schema
- `test_observability.py` — 1 teste relaxado para aceitar `noop` action

---

## [v9.3-telemetry] — 2026-06-08

### Adicionado
- V9 P2.3 — Telemetria de adoção Smart Field Ops (`v7_2_2_data_quality.executive_audit`)
- 23/23 testes pytest validados

---

## [v9.2-smart-field] — 2026-06-08

### Adicionado
- V9 P2 — Backend Smart Field Ops (`routes/lousa.py`)
- V9 P2.1 — Frontend captura em `LousaMobile.js`
- V9 P2.2 — E2E validação Smart Field Mobile
- Campos: `resolution_kind`, `asset_recovered`, `signed_receipt`, `reopened_within_7d`

---

## [v8.5-maturity] — 2026-06-08

### Adicionado
- Auditoria de Maturidade V8.5
- 25 outcomes confirmados em `motor_ia_outcomes`

---

## [v8.4-cohort] — 2026-06-08

### Adicionado
- `services/v8_4_cohort.py` — pareamento por strata + lift Wilson CI95
- Endpoints: `/v8/v84/eligible-count`, `/run-pilot`, `/attribution/{cohort_id}`, `/lift/{cohort_id}`
- Sanity check: cohort_id `v84-sanity-check-v84-b670d328` (10t+10c)

---

## [v8.3-causality] — 2026-06-08

### Adicionado
- `services/v8_3_causality.py` — A/B testing causal
- `motor_ia_cohorts`, `motor_ia_causality` (collections)
- Conexão Baileys Sidecar real porta 3002

---

## [v8.2-first-cash] — 2026-06-07

### Adicionado
- `services/v8_2_first_cash.py` — atribuição R$ 91,77 recuperados pela IA
- Log persistido em `motor_ia_revenue_attribution`

---

## [v8.1-simulator] — 2026-06-07

### Adicionado
- `services/v8_1_simulator.py` — gerador de 250 tickets sintéticos para métricas

---

## [v7.2-revenue] — 2026-06-05

### Adicionado
- `services/v7_2_revenue.py` — Action-to-Cash com reconciliação G1
- `services/v7_2_2_data_quality.py` — Data Quality IA

### Corrigido
- Backfills massivos: `assigned_to`, `category`, `opened_at`

---

## Política de versionamento

Formato: `vMAJOR.MINOR-fase`
- MAJOR: fase macro (v7 = Action-to-Cash, v8 = Causalidade, v9 = Market Validation)
- MINOR: sub-entrega da fase
- fase: nome curto descritivo

Convenção de commit pré-release:
- `[CONSTITUTION-AMEND]` — emenda constitucional
- `[ADR]` — nova decisão arquitetural
- `[RELEASE]` — pronto para produção
- `[HOTFIX]` — correção urgente
- `[GOVERNANCE]` — apenas docs/governança
