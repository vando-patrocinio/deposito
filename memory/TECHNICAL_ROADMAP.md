# 🗓 SmartProv — Roadmap de Remediação Técnica

> Plano de execução baseado em `TECHNICAL_AUDIT.md`. Cada bloco = 1 semana de sprint.
> Premissa: 80% features + 20% débito técnico.

---

## 📅 Visão geral (12 semanas)

```
SPRINT 0 ─── SETUP (Esta semana)
SPRINTS 1-4 ─── 🔴 BLOCO A: Estabilização (P0/P1 críticos)
SPRINTS 5-8 ─── 🟠 BLOCO B: Reestruturação (P1/P2)
SPRINTS 9-12 ── 🟡 BLOCO C: Maturidade (P2/P3)
```

---

## 🚦 Sprint 0 — Setup (esta semana, 3 dias)

**Objetivo**: criar a infraestrutura que vai sustentar os próximos 12 sprints.

- [ ] **0.1** — Adicionar Sentry no backend (FastAPI middleware) e frontend (React Error Boundary)
  - Critério: 1 erro proposital aparecendo no dashboard Sentry
  - Tempo: 2h
- [ ] **0.2** — Criar `/app/memory/CONVENTIONS.md` documentando:
  - Prefixos de coleção (`fin_*`, `wa_*`, `atlaz_*`)
  - Naming de rotas (`/api/v1/{module}/{resource}`)
  - Pasta routes/services/models
  - Estilo de testid e data-testid
  - Tempo: 3h
- [ ] **0.3** — Setup GitHub Action básico que roda `yarn build` + `pytest /app/backend/tests`
  - Critério: PR fictício passa pela action
  - Tempo: 2h
- [ ] **0.4** — Isolar `WA_SESSION_ID` preview ↔ produção (já tem env, só configurar Railway)
  - Critério: 24h sem disconnect cruzado
  - Tempo: 30min

**Entregável**: produção observável + CI mínimo + WhatsApp estável.

---

## 🔴 BLOCO A — Estabilização (Sprints 1-4 · ~4 semanas)

### Sprint 1 — Multi-tenancy real (parte 1)
- [ ] **1.1** — Migration `add_company_id_to_all_collections.py` aplicada via script controlado
  - Coleções: `collaborators`, `clients`, `lousa_tickets`, `wa_*`, `clock_records`
- [ ] **1.2** — Middleware FastAPI obrigatório `enforce_tenant()` aplicado em todos os routers
- [ ] **1.3** — Remover `DEMO_COMPANY_ID` fallback dos top 5 endpoints mais usados (lousa, financeiro, atendimento)
- [ ] **1.4** — Index composto `(company_id, ...)` em todas as 15+ collections principais

**Entregável**: tenancy enforcement em 80% das queries. Sem regressão visível.

### Sprint 2 — Suite de smoke tests
- [ ] **2.1** — 10 testes pytest cobrindo:
  - Login (3 roles)
  - Create+List Bill com filial
  - Create lousa ticket + transferir
  - Send WA message via Baileys
  - Marcar ponto (válido + bloqueado pra Associado)
  - DRE + Aging endpoints retornam 200
- [ ] **2.2** — GitHub Action que roda em todo PR + bloqueia merge se falhar
- [ ] **2.3** — Documento `TESTING_STRATEGY.md` definindo pirâmide (unit / integration / e2e)

**Entregável**: rede de segurança que pega 70% das regressões antes do merge.

### Sprint 3 — WhatsApp resiliente
- [ ] **3.1** — Healthcheck cron `/api/wa/health` retornando `{status, last_msg_ago_seconds, qr_pending}`
- [ ] **3.2** — Alerta automático Telegram/Email se WhatsApp > 5min offline
- [ ] **3.3** — Reconexão automática com backoff exponencial no sidecar (já tem? auditar)
- [ ] **3.4** — Dashboard simples em `/app/admin/wa-health` para gestor monitorar
- [ ] **3.5** — Documentar runbook "WhatsApp caiu" em `RUNBOOKS.md`

**Entregável**: downtime médio < 2min · MTTR < 5min com alerta proativo.

### Sprint 4 — Migration framework + naming
- [ ] **4.1** — Framework de migrations leve em `/app/backend/migrations/` com lock distribuído
- [ ] **4.2** — Converter as migrations existentes (cargo, fin_filiais, etc) para o framework
- [ ] **4.3** — Renomear coleções inconsistentes (decidir canônicas):
  - `wa_conversations` ← canônica
  - `atlaz_config` ← canônica (deletar `atlaz_settings` se existir)
- [ ] **4.4** — Atualizar `CONVENTIONS.md` com regras de naming forçadas via linter custom

**Entregável**: deploys de migration auditáveis + reversíveis.

---

## 🟠 BLOCO B — Reestruturação (Sprints 5-8 · ~4 semanas)

### Sprint 5 — Quebrar `LousaAdminPanel.js` (2.400 linhas)
- [ ] **5.1** — Extrair em `/app/frontend/src/lousa/`:
  - `LousaToolbar.jsx` (toolbar header)
  - `LousaGrid.jsx` (renderer principal)
  - `TechColumn.jsx` (já parcial)
  - `TechTimeline.jsx` (já criado, mover para subpasta)
  - `TechFilterMenu.jsx`
  - `BubbleCard.jsx`
  - `useLousaData.js` (custom hook)
- [ ] **5.2** — Cada arquivo < 400 linhas
- [ ] **5.3** — Testes Playwright smoke do focus mode + drag/drop

**Entregável**: codebase Lousa onboardable em 1h por novo dev.

### Sprint 6 — Quebrar `clock.py` (2.300 linhas)
- [ ] **6.1** — Separar em:
  - `routes/cadastro.py` (CRUD colaboradores)
  - `routes/ponto.py` (clock_records, sheet)
  - `routes/face.py` (recognition)
  - `services/cargo_rules.py` (já existe `cargo.py`, mover lógica)
- [ ] **6.2** — Server.py registra os 3 routers separadamente

**Entregável**: domínios separados claramente.

### Sprint 7 — TypeScript incremental (parte 1)
- [ ] **7.1** — `tsconfig.json` com `allowJs: true` + strict baixo
- [ ] **7.2** — Migrar para `.ts`:
  - `src/api.js` → `api.ts` (tipos de payloads críticos)
  - `src/AuthContext.js` → `AuthContext.tsx`
  - `src/cargo.js` → `cargo.ts` (já são constantes)
  - `src/dialog.js` → `dialog.tsx`
- [ ] **7.3** — Pre-commit hook bloqueando novos `.js` em pastas migradas

**Entregável**: tipos no caminho crítico de auth + API.

### Sprint 8 — Filiais Phase 2 (multi-tenant real)
- [ ] **8.1** — `filial_id` em `collaborators`, `clients`, `lousa_tickets`
- [ ] **8.2** — Filtro de filial no Cadastro de Colaboradores
- [ ] **8.3** — Sidebar de empresa: seletor "Filial: Todas / X / Y" como o Atendimento já tem
- [ ] **8.4** — Endpoint `/api/dashboard/by-filial` agregando KPIs por unidade

**Entregável**: empresa com 3 filiais consegue ver dados separados.

---

## 🟡 BLOCO C — Maturidade (Sprints 9-12 · ~4 semanas)

### Sprint 9 — Versionamento de prompts IA
- [ ] **9.1** — Mover prompts dos agentes para `/app/backend/prompts/v{N}/{agent}.md`
- [ ] **9.2** — Tabela `prompt_versions` com `(version, agent_id, content_hash, deployed_at)`
- [ ] **9.3** — Suite de "regression prompts": 20 entradas gold com output esperado, roda no CI

**Entregável**: zero quebra silenciosa de agentes em deploy.

### Sprint 10 — Abstração LLM Provider
- [ ] **10.1** — Interface `LLMProvider` com métodos `chat()`, `image()`, `embed()`
- [ ] **10.2** — Implementações: `EmergentProvider` (atual) + `OpenAIDirectProvider` (fallback)
- [ ] **10.3** — Switch via `.env` `LLM_PROVIDER=emergent|openai_direct`
- [ ] **10.4** — Healthcheck que detecta provider down e alterna

**Entregável**: independência de vendor.

### Sprint 11 — Observability completa
- [ ] **11.1** — Tracing distribuído com OpenTelemetry (FastAPI + frontend)
- [ ] **11.2** — Dashboards: latência p95 por endpoint, error rate, throughput WA
- [ ] **11.3** — Alertas: erro rate > 5% em 5min · latência p95 > 2s
- [ ] **11.4** — Runbooks dos top 5 incidents recorrentes

**Entregável**: MTTR < 10min para 90% dos incidents conhecidos.

### Sprint 12 — Filiais Phase 3 + DRE multi-filial
- [ ] **12.1** — Filtro `filial_id` em todos os endpoints de Relatórios financeiros
- [ ] **12.2** — DRE consolidado vs por-filial (dropdown)
- [ ] **12.3** — Comparativo MoM (mês vs mês anterior) com setas ↑↓
- [ ] **12.4** — Export PDF dos relatórios

**Entregável**: gestor consegue tomar decisão baseada em dados por filial.

---

## 📊 Métricas de sucesso

| Métrica | Hoje | Meta 12 sem |
|---------|------|-------------|
| Tempo médio para fix de bug P0 | ~4h | < 1h |
| Regressões em produção / mês | ~5 | < 1 |
| Cobertura de testes | 0% | 40% |
| Arquivos > 1000 linhas | 4 | 0 |
| MTTR WhatsApp down | ~30min | < 5min |
| Tempo de onboarding novo dev | ? | < 1 dia |

---

## 🚧 Bloqueios potenciais

1. **Cliente novo entrando** → multi-tenancy fake explode primeiro
2. **Lei LGPD batendo** → auditoria precisa de logs estruturados
3. **WhatsApp Cloud aprovado** → migrar tráfego sem perder histórico
4. **Bug crítico em sexta-feira** → sem alerta = descoberta segunda

---

## 📋 Cerimônias sugeridas

- **Segunda 9h**: planning da semana (15min · escolher 1 item + features)
- **Sexta 16h**: review do que entregou + ajuste do roadmap (10min)
- **A cada 2 sprints**: retrospectiva pequena (qual débito virou bug? qual não foi tocado?)

---

## ✅ Checklist de início

Para começar Sprint 0 amanhã:
- [ ] Confirmar acesso a Sentry (criar conta free se não tem)
- [ ] Confirmar Railway pode rodar 2 sidecars WA (preview + prod)
- [ ] Bloquear 4h no calendário (terça/quinta de manhã, recorrente)
- [ ] Salvar este arquivo no GitHub via "Save to GitHub"
