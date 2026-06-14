# 🧠 LIGO EXECUTIVE OS — Arquitetura, Reaproveitamento e Plano

> **Operação:** LIGO EXECUTIVE OS — Discovery Phase
> **Data:** 14/06/2026
> **Modo:** CTO — Evidence → Reuse → Duplications → Risks → Architecture → Authorization
> **Status:** 🚫 NENHUM CÓDIGO ESCRITO. Aguardando autorização para implementar.

---

## 🎯 OBJETIVO ESTRATÉGICO

> "Transformar o SmartProv de um ERP de provedor em um Sistema Operacional Executivo da Ligo."

O sistema precisa parar de "monitorar tickets" e começar a **interpretar a operação, gerar visão estratégica, identificar riscos, detectar oportunidades** continuamente.

---

## 1️⃣ MAPA DO QUE JÁ EXISTE (REAL, EM PROD)

### 🟢 Camada de Eventos (Sistema Nervoso) — **JÁ EXISTE E ESTÁ VIVO**

**`/app/backend/services/event_bus.py`** (227 linhas) — barramento canônico:

- **80+ tipos de evento** já definidos: `CLIENT_OFFLINE`, `CLIENT_CHURN_RISK`, `CTO_DEGRADED`, `COLLECTIVE_OUTAGE`, `TICKET_OPENED`, `TICKET_RECURRING`, `SALE_CREATED`, `OPPORTUNITY_DETECTED`, `INVOICE_OVERDUE`, `DUNNING_ESCALATED`, `INCIDENT_PREDICTED`, `INCIDENT_CTO_CLUSTER`, `INCIDENT_NEIGHBORHOOD_CLUSTER`, `OPPORTUNITY_CREATED`, `CHURN_RISK_SCORED`, `REVENUE_OPPORTUNITY_DETECTED`, `EXPERIENCE_EVENT_DETECTED`, `UNIVERSO_LEVEL_CHANGED`, etc.
- Função `emit_event(event_type, company_id, payload, severity, correlation_id)` — best-effort, espelha em `motor_ia_events` E `nervous_events`.
- **Volume real co-demo:** 377.589 docs em `motor_ia_events`, 37.186 em `nervous_events`. **A operação está sendo registrada continuamente.**

**Implicação:** os 7 eventos executivos pedidos pelo CTO (`CLIENTE_RISCO_CANCELAMENTO`, `CLIENTE_FUNDADOR_DETECTADO`, `EMBAIXADOR_NATURAL_DETECTADO`, `BAIRRO_EM_EXPANSAO`, `PRODUTO_EM_ALTA`, `INCIDENTE_RECORRENTE`, `INADIMPLENCIA_CRITICA`) **já existem ou têm equivalente direto** no `EventType`. Não precisamos criar barramento novo — apenas formalizar 5-6 tipos faltantes e roteá-los.

### 🟢 Camada de Inteligência por Agente — **JÁ EXISTE**

| Agente | Arquivo principal | Status |
|---|---|---|
| **Isabella** (vendedora/comandante) | `services/isabella_commanders_worker.py` (Churn/Dunning/Revenue/Twin/Expansion) + 25 arquivos `isabella_*.py` | ✅ rodando |
| **Pamela** (atendimento/relacionamento) | `services/pamela_*` (verificar) | ⚠️ a auditar |
| **Álvaro** (ops/qualidade) | `services/alvaro_*.py` + `routes/ai_center_alvaro_v5.py` | ✅ rodando |
| **Camila** (vendas humanas/leads) | `services/camila_*` ou em `sales_outreach.py` | ⚠️ a auditar |
| **Presidente IA** | `services/presidente_*.py` (12 arquivos), `routes/presidente_ia.py` (1.131 linhas) | ✅ rodando |
| **Rede IA / SmartOLT IA** | `services/rede_ia_outage_detector.py`, `services/smartolt_ai.py` | ✅ rodando |
| **Motor IA (decisão+ação+aprendizado)** | `services/motor_ia.py`, collections `motor_ia_decisions/actions/outcomes/learnings` | ✅ rodando (2.272 decisões, 2.365 ações, 2.271 outcomes, 2.112 aprendizados co-demo) |

### 🟢 Conselho/Briefing — **JÁ EXISTE MAS DESORGANIZADO**

| Componente existente | Função | Reaproveitamento |
|---|---|---|
| `services/presidente_ia_briefing.py` (213 linhas) | "Café com a IA do CEO" — texto 2-3 linhas via WhatsApp | **REUSAR como base** mas expandir para 1 página executiva |
| `services/conselho_ia_scheduler.py` (231 linhas) | Cron 08:00 BRT — roda relatório do conselho | **REUSAR scheduler**, redirecionar saída |
| `routes/conselho_ia.py` (1.362 linhas) | `/report` consolidando overview/network/technicians/atendimento/sales/universo/protege | **REUSAR _collect_*** funções como blocos do CEO BRIEFING |
| `services/isabella_conselho.py` (224 linhas) | Reunião diária dos Commanders → `isabella_council_minutes` | **REUSAR como Conselho Comercial + Operacional** |
| `services/presidente_ia_conselho.py` (234 linhas) | Conselho Estratégico do Presidente | **REUSAR como base do CONSELHO FINANCEIRO** |
| `routes/presidente_ia.py::GET /conselho/{role}` | endpoint que retorna parecer de um conselho por papel | **REUSAR**, expandir para os 5 conselhos do CTO |
| `services/briefing_dispatcher.py` | Dispatcher do WhatsApp | **REUSAR como canal** |
| `services/executive_health.py` | Health corporativo 0-100 | **REUSAR como base do "Como está a Ligo hoje?"** |

### 🟢 Universo Ligo — **JÁ ENTREGUE ONTEM**

- `routes/universo_ligo.py` — endpoints existentes (níveis seedados, scores)
- `routes/universo_ligo_curadoria.py` — **entregue na operação anterior** (TOP10, validate, invite, DNC, NPS, guard log)
- `frontend/src/UniversoLigoPanel.js` + `UniversoLigoCuradoriaPanel.js`
- `universo_ligo_v2/` — módulo de migração e modelos

### 🟢 Frontend executivo — **EXISTE FRAGMENTADO**

- `CentralIaDashboard.js` (já é uma visão central)
- `DashboardPanel.js` (operacional)
- `ConselhoIaPanel.js` (já existe!)
- `AICenterPanel.js`
- `AlvaroPanel.js`
- `ChurnDashboardPanel.js`
- `UniversoLigoPanel.js` + `UniversoLigoCuradoriaPanel.js`

**Não existe ainda:** uma tela **"CEO MODE"** unificada respondendo às 5 perguntas pedidas.

---

## 2️⃣ REAPROVEITAMENTO (O QUE NÃO PRECISA SER RECRIADO)

| Camada CTO pediu | Já existe? | Reaproveita o quê |
|---|---|---|
| Sistema Nervoso Executivo (barramento) | ✅ SIM | `event_bus.py` + `nervous_events`. Só formalizar 5-6 tipos executivos faltantes |
| CEO Briefing diário "Café com o CEO" | ✅ PARCIAL | `presidente_ia_briefing.py` (texto curto) → expandir conteúdo para 1 página com seções obrigatórias |
| Scheduler 08:00 BRT | ✅ SIM | `conselho_ia_scheduler.py` |
| Conselho Comercial | ✅ SIM | `isabella_conselho.py` (Revenue + Expansion Commanders) |
| Conselho Operacional | ✅ SIM | `alvaro_v5.py` + `isabella_incident.py` + `rede_ia_outage_detector.py` |
| Conselho Financeiro | ✅ SIM | `presidente_cash.py` + `presidente_financeiro.py` + `isabella_dunning.py` |
| Conselho Produto | 🟡 PARCIAL | `motor_ia_intel.py` (feedback/learnings) + `isabella_experience.py` — falta consolidador |
| Conselho Universo Ligo | ✅ SIM (acabou de nascer) | `universo_ligo_curadoria.py` + relatórios já gerados |
| KPI executivos | ✅ SIM | `executive_health.py` + `presidente_score_engine.py` + `agent_revenue.py` |
| CEO Mode (visão única) | ❌ NÃO | Precisa criar a tela — mas backend já tem todos os agregadores |

---

## 3️⃣ DUPLICIDADES (DÉBITO TÉCNICO)

> Existem **MUITAS** sobreposições. Antes de adicionar peças novas, precisamos consolidar.

### 🔴 Quatro cérebros do Presidente IA
- `services/presidente_ia.py` (660 linhas) — base
- `services/presidente_executive.py` (884 linhas) — relatórios full
- `services/presidente_brain.py` (520 linhas) — context/memory
- `services/presidente_operator.py` (1.032 linhas) — execução

**Risco:** lógica de decisão executiva pode divergir entre os quatro. Métricas podem dar números diferentes para o mesmo conceito.

**Proposta:** definir um **único entry point** (`presidente_ia.py`) que delega para os outros como módulos especializados, e DOCUMENTAR no header de cada arquivo qual é o papel.

### 🔴 Três conselhos
- `services/isabella_conselho.py` — comandantes de Isabella
- `services/presidente_ia_conselho.py` — conselho do presidente
- `routes/conselho_ia.py` — conselho geral configurável

**Risco:** triplicação de reuniões diárias com mesmo escopo, custos de LLM duplicados, atas conflitantes.

**Proposta:** definir **`conselho_ia.py` como camada de orquestração** dos 5 conselhos do CTO (Comercial/Operacional/Financeiro/Produto/Universo Ligo). Os outros viram **provedores de dados** (não atas concorrentes).

### 🔴 Cinco serviços de receita
- `services/agent_revenue.py` (452 linhas)
- `services/real_revenue.py`
- `services/v7_2_revenue.py`
- `services/revenue_attribution.py`
- `services/isabella_revenue.py`

**Risco:** "qual é a receita real?" tem 5 respostas possíveis. Briefing CEO pode mostrar número diferente do Dashboard que pode ser diferente do Presidente IA.

**Proposta:** consolidar em `agent_revenue.py` como ÚNICA fonte de verdade. Outros viram aliases ou são deprecated.

### 🔴 Três briefings
- `services/presidente_ia_briefing.py`
- `services/briefing_dispatcher.py`
- `services/disparo_briefing.py`

**Proposta:** `presidente_ia_briefing.py` é o **gerador**; `briefing_dispatcher.py` é o **transporte**; `disparo_briefing.py` deve ser deprecated/mesclado.

### 🔴 Collections vazias/duplicadas
- `executive_ledger` (2.351 docs, 99,3% sintético — 16 reais)
- `presidente_ledger` (0 docs)
- `briefing_executive` (0 docs)
- `agent_revenue_events` (0 docs)

**Proposta:** decidir qual é a verdadeira fonte de evento executivo. As outras → drop.

---

## 4️⃣ RISCOS DETECTADOS

### 🚨 R1 — Inflação de dados sintéticos AINDA em coleções de agregado

Mesmo após filtro `$nin` aplicado em `_base_q`, **as collections de agregado já têm dados antigos contaminados**:
- `motor_ia_events`: 12,8% sintético (55k de 432k)
- `nervous_events`: 9,6% sintético
- `isabella_council_minutes`: 38% sintético (33 de 86)
- `executive_ledger`: 99,3% sintético

**Mitigação:** todo novo agregado para o CEO BRIEFING deve usar `company_id="co-demo"` (single-tenant) E os endpoints já corrigidos. Para histórico, precisamos re-agregar últimos 90 dias.

### 🚨 R2 — `nps_responses_mvp` recém-criado com baixa massa

A confiança das estatísticas NPS no briefing será **BAIXA por meses**. O briefing precisa **declarar isso explicitamente** ("NPS: confiança baixa, N=X coletados").

### 🚨 R3 — Eventos `INCIDENT_*` e `OPPORTUNITY_*` existem mas não há consumidor único para "incidentes recorrentes"

Já temos `INCIDENT_PREDICTED`, `INCIDENT_CONFIRMED`, `INCIDENT_CTO_CLUSTER`. **Falta um agregador que conte "incidente recorrente"** (mesma CTO/bairro/equipamento em janela de 7-30d). Hoje cada agente decide isso isolado.

### 🚨 R4 — Camila e Pamela podem não existir como agentes separados

- Pamela: precisamos validar se há `services/pamela_*.py` real. Pode ser que esteja embutida em `isabella_relationship.py`.
- Camila: pode estar em `sales_outreach.py` apenas como persona. Sem rosto próprio no código.

**Mitigação:** auditar em P1; se não existirem como módulos próprios, **declarar isso no documento de governança** antes de prometer "Conselho Comercial liderado por Camila".

### 🚨 R5 — Risco de "produzir relatórios" em vez de "produzir inteligência"

O briefing diário pode virar mais um PDF ignorado se não houver:
1. **CTAs claros** (ex: "ligue para BIANCA hoje" — não "tem 1 cliente em risco")
2. **Encerramento de loops** — quando um risco do briefing de ontem foi resolvido, briefing de hoje precisa registrar
3. **Tom executivo** — não academicismo

---

## 5️⃣ ARQUITETURA PROPOSTA

```
┌─────────────────────────────────────────────────────────────────────┐
│                  LIGO EXECUTIVE OS — Camada Estratégica              │
│                                                                       │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  CEO MODE      │  │ CAFÉ COM CEO │  │  5 CONSELHOS EXECUTIVOS  │  │
│  │  (tela única)  │  │ (briefing 1pg│  │  - Comercial            │  │
│  │                │  │  08:00 BRT)  │  │  - Operacional          │  │
│  │                │  │              │  │  - Financeiro           │  │
│  │                │  │              │  │  - Produto              │  │
│  │                │  │              │  │  - Universo Ligo        │  │
│  └───────┬────────┘  └──────┬───────┘  └─────────┬────────────────┘  │
│          │                  │                    │                   │
│          └──────────┬───────┴────────────────────┘                   │
│                     ▼                                                │
│           ┌─────────────────────────┐                                │
│           │  executive_os_engine.py │  ◄── núcleo novo (consolidador)│
│           │   (consolida/cacheia)    │                                │
│           └────────────┬─────────────┘                                │
└────────────────────────┼──────────────────────────────────────────────┘
                         │ lê
                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│              CAMADA DE INTELIGÊNCIA (JÁ EXISTE)                         │
│                                                                          │
│   ┌─────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│   │ Isabella    │ │ Álvaro   │ │ Presidente│ │ Pamela   │ │ Camila   │ │
│   │ Commanders  │ │ AI       │ │ IA       │ │ (auditar)│ │ (auditar)│ │
│   └─────────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │
│                                                                          │
│   motor_ia (decisions/actions/outcomes/learnings) + isabella_commanders │
└────────────────────────────────────────────────────────────────────────┘
                         │ lê
                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│              CAMADA DE EVENTOS (JÁ EXISTE — event_bus.py)               │
│   80+ tipos: CLIENT_*, ONU_*, CTO_*, TICKET_*, SALE_*, INVOICE_*,       │
│   FIELD_*, INCIDENT_*, OPPORTUNITY_*, CHURN_*, UNIVERSO_*                │
│   → motor_ia_events (377k co-demo) + nervous_events (37k co-demo)        │
└────────────────────────────────────────────────────────────────────────┘
                         │ lê
                         ▼
┌────────────────────────────────────────────────────────────────────────┐
│            CAMADA OPERACIONAL (FONTE PRIMÁRIA DE VERDADE)                │
│   subscribers (2.746 ativos) + tickets + invoices + collaborators +      │
│   ctos + incidents + aihub_wa_messages + ... (após filtro $nin)         │
└────────────────────────────────────────────────────────────────────────┘
```

### Componente NOVO único: `executive_os_engine.py`

**Responsabilidades:**
- Funções `build_briefing_diario(cid)` → 1 página com seções obrigatórias
- Funções `build_conselho(name, cid)` para cada um dos 5 conselhos
- Função `build_ceo_mode(cid)` para a tela única
- **Cache em `executive_os_snapshots`** (collection nova) para evitar re-cálculo (briefing é fotografado às 08:00)
- **Emite eventos executivos novos** quando detecta padrões: `EXECUTIVE_RISK_DETECTED`, `EXECUTIVE_OPPORTUNITY_DETECTED`, `EXECUTIVE_BAIRRO_EXPANSION`, `EXECUTIVE_PRODUCT_TRENDING`

**Quantas linhas:** ~600 — único módulo novo. Resto é orquestração de serviços que já existem.

### Eventos executivos a formalizar no `event_bus.py`

| Evento pedido pelo CTO | Existe? | Decisão |
|---|---|---|
| `CLIENTE_RISCO_CANCELAMENTO` | ✅ `CLIENT_CHURN_RISK`, `CHURN_RISK_SCORED` | reusar |
| `CLIENTE_FUNDADOR_DETECTADO` | ❌ | **criar** `EXECUTIVE_FOUNDER_DETECTED` |
| `EMBAIXADOR_NATURAL_DETECTADO` | ❌ | **criar** `EXECUTIVE_AMBASSADOR_DETECTED` |
| `BAIRRO_EM_EXPANSAO` | ❌ | **criar** `EXECUTIVE_NEIGHBORHOOD_EXPANSION` |
| `PRODUTO_EM_ALTA` | ❌ | **criar** `EXECUTIVE_PRODUCT_TRENDING` |
| `INCIDENTE_RECORRENTE` | ✅ `TICKET_RECURRING`, `INCIDENT_CTO_CLUSTER` | reusar (agregador novo no engine) |
| `INADIMPLENCIA_CRITICA` | ✅ `DUNNING_ESCALATED`, `PAYMENT_OVERDUE` | reusar (limiar no engine) |

**Total de novos eventos:** 4 a adicionar em `event_bus.py::EventType`.

### Conteúdo do "Café com o CEO" (1 página)

Mantém **exatamente** as 7 seções do CTO:

```
☕ CAFÉ COM O CEO · DD/MM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLIENTES
  ativos: 2.746   |  novos 7d: 8   |  cancelamentos 7d: 2
  saldo líquido 30d: +18 (↑ vs −5 mês anterior)

FINANCEIRO
  receita ontem: R$ X.XXX   |  mês: R$ XXX.XXX
  inadimplência: 7,3% (200 contratos)   |  previsão 30d: R$ XXX

ATENDIMENTO
  Isabella: 542 conversas   |  resolução auto: 71%
  transferências humanas: 158   |  irritados: 4
  tempo médio: 4m 12s

REDE
  incidentes ativos: 1   |  bairros afetados: 0
  CTOs críticas: 0   |  capacidade média: 47%

COMERCIAL
  vendas 7d: 5   |  conversões: 28%
  indicações: 0 (sistema sem dados reais)
  oportunidades abertas: 41

UNIVERSO LIGO
  fundadores APTO: 2   |  embaixadores: 0 pendentes carimbo
  invisíveis cuidados 7d: 0   |  convites pendentes: 0

PRESIDENTE IA
  ⚠ alerta: BIANCA (5y) sem contato há 22d
  💡 oportunidade: CORDOVIL — saturação 78%, expansão sugerida
  🛡️ risco: CTO #X em VISTA ALEGRE — 3 chamados recorrentes
```

Cada linha → **callable** se possível (clica e vê detalhes no painel).

### CEO MODE — Tela única (5 respostas)

```
┌─────────────────────────────────────────────────────────────────┐
│   LIGO HOJE                                            [↻]      │
│                                                                  │
│   Saúde corporativa:  🟢 82/100   ↑ +3 vs ontem                  │
│   Receita mês:        R$ XXX.XXX (75% da meta)                   │
│   Clientes:           2.746 ↑ saldo +12 esta semana              │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│   🟢 GANHANDO                    │   🔴 PERDENDO                 │
│   • CORDOVIL: +6 saldo 30d       │   • VISTA ALEGRE: −3 saldo    │
│   • Plano 500M: +18 vendas mês   │   • CTO #X: 3 chamados rec    │
│   • Universo Ligo: 1 aceito      │   • RJ ZN: inadimplência 8%   │
├─────────────────────────────────────────────────────────────────┤
│   QUEM PRECISA DE ATENÇÃO HOJE                                   │
│   1. [CALL] Bianca C. Marinho — 5y sem contato                   │
│   2. [APROVAR] 3 fundadores aguardando carimbo                   │
│   3. [DECIDIR] Expansão CORDOVIL —  proposta engenharia          │
│   4. [REVISAR] Vendedor #2 — 0 conversões 7d                     │
├─────────────────────────────────────────────────────────────────┤
│   O QUE FAZER AGORA                                              │
│   • CTO recomenda: validar 8 fundadores ainda sem carimbo        │
│   • Pamela recomenda: registrar 5 NPS dos atendimentos ontem     │
│   • Álvaro recomenda: agendar OS preventiva em CTO #X            │
└─────────────────────────────────────────────────────────────────┘
```

**Backend** dessa tela: 1 endpoint único `GET /api/executive-os/ceo-mode` que orquestra 4 chamadas internas (`executive_health`, `top_winners`, `top_losers`, `attention_needed`) e retorna JSON compacto.

**Frontend**: 1 arquivo `CeoModePanel.js` (~250 linhas), sem gráficos pesados, sem widgets — só blocos de texto + botões de ação.

---

## 6️⃣ PLANO DE IMPLEMENTAÇÃO POR FASES

### FASE A — Consolidação (P0 · 2-3 dias) — **PRÉ-REQUISITO**
Antes de adicionar peças novas, eliminar débito:

| Item | Ação | Risco se pular |
|---|---|---|
| A1 | Documentar papéis dos 4 cérebros do Presidente IA no header de cada arquivo. **Sem refactor** ainda. | Briefing pode pegar número errado |
| A2 | Definir `agent_revenue.py` como **ÚNICA fonte** de receita; outras viram aliases. | Receita do briefing ≠ Receita do Conselho |
| A3 | Auditar Pamela/Camila: existem como serviços próprios? Se não, **declarar oficialmente** que são personas, não agentes. | Não prometer o que não há |
| A4 | Re-agregar histórico contaminado de `motor_ia_kpis`, `executive_ledger` (drop sintéticos antigos ou taggear como `pre_sanitize_2026_06_14=true`) | Briefing puxa números inflados |

### FASE B — CAFÉ COM O CEO (P0 · 2-3 dias)

| Item | Ação |
|---|---|
| B1 | Adicionar 4 novos `EventType` em `event_bus.py` (`EXECUTIVE_FOUNDER_DETECTED`, `EXECUTIVE_AMBASSADOR_DETECTED`, `EXECUTIVE_NEIGHBORHOOD_EXPANSION`, `EXECUTIVE_PRODUCT_TRENDING`) |
| B2 | Criar `services/executive_os_engine.py` (~600 linhas) — funções `build_briefing_diario`, agregadores por seção |
| B3 | Criar collection `executive_os_snapshots` (idempotente — 1 doc/dia/cid) |
| B4 | Criar route `routes/executive_os.py` — `GET /api/executive-os/briefing/today` |
| B5 | Conectar `conselho_ia_scheduler` para chamar `build_briefing_diario` às 08:00 BRT |
| B6 | Frontend: `CafeComCeoPanel.js` (~200 linhas) — 1 página, sem gráficos, com CTAs |
| B7 | Envio opcional via `briefing_dispatcher.py` (WhatsApp ao CEO se configurado) |

### FASE C — 5 CONSELHOS EXECUTIVOS (P1 · 3-5 dias)

| Item | Ação |
|---|---|
| C1 | Estender `routes/conselho_ia.py` com 5 rotas nomeadas: `/conselho/comercial`, `/operacional`, `/financeiro`, `/produto`, `/universo-ligo` |
| C2 | Cada conselho lê de **fontes específicas**: ver tabela "Mapeamento Conselho → Provedor" abaixo |
| C3 | Cada conselho responde **a pergunta diária** com 3 itens (gargalo/oportunidade/decisão) |
| C4 | Persistir atas em `conselho_executivo_minutes` (collection nova) — 1 doc/conselho/dia |
| C5 | Frontend: estender `ConselhoIaPanel.js` com 5 abas (uma por conselho) — não criar arquivo novo |

### FASE D — SISTEMA NERVOSO EXECUTIVO (P1 · 2 dias)

| Item | Ação |
|---|---|
| D1 | Worker `services/executive_event_router.py` (~200 linhas) — consome `nervous_events`, **promove** eventos relevantes a `executive_events` (collection nova, filtrada/curada) |
| D2 | Briefing + Conselhos consultam `executive_events` (mais limpo que `nervous_events` raw) |
| D3 | Painel Tenant Guard já mostra os sintéticos; **adicionar painel "Eventos Executivos"** mostrando os reais |

### FASE E — CEO MODE (P1 · 2-3 dias)

| Item | Ação |
|---|---|
| E1 | Route `GET /api/executive-os/ceo-mode` |
| E2 | `CeoModePanel.js` (~250 linhas) — única tela executiva |
| E3 | Plugar em sidebar principal **acima** de todos os outros painéis |

### FASE F — OBSERVABILIDADE (P2 · 1 dia)

| Item | Ação |
|---|---|
| F1 | Métrica "briefing read rate" — quem abriu o briefing de hoje? |
| F2 | Métrica "CTA close rate" — quantos CTAs do briefing foram executados? |
| F3 | Métrica "estoria viva" — quantos CTAs foram dispensados como ruído (sinal para tunar a IA) |

---

## 7️⃣ MAPEAMENTO CONSELHO → PROVEDOR DE DADOS

| Conselho | Pergunta diária | Lê de (provedores reais) | Persistido em |
|---|---|---|---|
| **Comercial** | "Como vender mais?" | `isabella_commander_opportunities` (Revenue + Expansion) + `subscriber_addresses` (clusters geográficos) + `agent_revenue.py` | `conselho_executivo_minutes` |
| **Operacional** | "Onde estamos falhando?" | `isabella_incidents` + `tickets` (recorrentes) + `field_os` + `alvaro_analyses` + `rede_ia_outage_detector` | idem |
| **Financeiro** | "Onde estamos perdendo dinheiro?" | `subscriber_invoices` (overdue) + `isabella_dunning` + `presidente_cash` + `executive_ledger` (after $nin) | idem |
| **Produto** | "O que clientes querem?" | `aihub_wa_messages` (NLP em comentários — fase futura) + `motor_ia_learnings` + `isabella_experience` + `nps_responses_mvp` | idem |
| **Universo Ligo** | "Estamos criando pertencimento?" | `universo_ligo_invites` + `universo_ligo_scores` + `experience_campaigns` | idem |

**Princípio:** cada conselho **não precisa ter um agente próprio**. Ele é uma **camada de leitura especializada** dos agentes existentes.

---

## 8️⃣ ZERO MOCKS — CHECKLIST DE DADOS REAIS

| Componente | Fonte real disponível? | Confiança |
|---|---|---|
| Receita por agente | ✅ `agent_revenue.py` + `executive_ledger` (16 reais) | 🟡 baixa massa (precisa Fase A4) |
| Saldo líquido clientes | ✅ `subscribers` + `loyalty_imported_db` (2.746 ativos validados) | 🟢 alta |
| Inadimplência | ✅ `subscriber_invoices` + `loyalty.invoices_overdue` | 🟢 alta |
| Atendimentos Isabella | ✅ `aihub_wa_messages` (42.723 co-demo) | 🟢 alta |
| Tempo médio atendimento | ⚠️ a calcular via timestamps em `aihub_wa_messages` | 🟡 média |
| Clientes irritados | ⚠️ não há flag estruturada — precisaria NLP em mensagens | 🔴 baixa |
| Incidentes ativos | ✅ `isabella_incidents` (5 co-demo) | 🟢 alta |
| Bairros afetados | ✅ derivável de `incidents + subscriber_addresses` | 🟢 alta |
| Vendas / conversões | ✅ `sales_leads` + `motor_ia_actions` | 🟡 média |
| Indicações | 🔴 `referrals` = 7 docs, todos sintéticos. **Briefing deve declarar "sem dados reais"** | 🔴 indisponível |
| Oportunidades abertas | ✅ `isabella_commander_opportunities` (2.041 pending co-demo) | 🟢 alta |
| Fundadores | ✅ `universo_ligo_invites` + relatórios prévios | 🟢 alta |
| Embaixadores | ✅ `experience_campaigns` (17 reais) | 🟡 média |
| Top alertas Presidente IA | ✅ `presidente_ia.compute_risks` | 🟢 alta |
| NPS | 🟡 `nps_responses_mvp` (recém-criado, baixa massa) | 🔴 baixa por agora |

**Itens com sinal vermelho** terão badge explícito de "INDISPONÍVEL" / "BAIXA CONFIANÇA" no briefing. **Nunca inventar.**

---

## 9️⃣ ESTIMATIVA AGREGADA

| Fase | Esforço | Risco | Bloqueio dependente |
|---|---|---|---|
| A — Consolidação | 2-3 dias | 🟢 baixo | nenhum |
| B — Café com CEO | 2-3 dias | 🟡 médio (qualidade de conteúdo) | depende de A4 |
| C — 5 Conselhos | 3-5 dias | 🟡 médio | depende de A |
| D — Sistema Nervoso Executivo | 2 dias | 🟢 baixo | depende de A1 |
| E — CEO Mode | 2-3 dias | 🟡 médio (UX) | depende de B+C+D |
| F — Observabilidade | 1 dia | 🟢 baixo | depende de B+E |
| **TOTAL** | **12-17 dias úteis** | — | — |

> Realista para 1 dev focado, sem desvios. Pode ser paralelizado (A+B juntos; C+D juntos; E+F juntos) para ~7-10 dias.

---

## 🔟 RISCOS RESIDUAIS PÓS-LANÇAMENTO

1. **Sobrecarga de canais** — CEO recebe briefing por WhatsApp + email + push + Slack? **Decisão necessária:** **1 canal primário**.
2. **Atualização do briefing intra-dia** — 08:00 BRT é foto. Se às 14h um incidente crítico nascer, como o CEO sabe? **Decisão necessária:** alerta push em incidente crítico apenas (não mais um briefing).
3. **Quem aprova mudança de tom?** — Pamela/Isabella personas precisam de owner único. **Decisão necessária:** CTO ou comitê de produto?
4. **Multilíngua** — Briefing hoje só em pt-BR. **Decisão:** manter pt-BR fixo (Ligo opera no Brasil).
5. **LLM cost** — Cada briefing/conselho potencialmente chama LLM. Com 5 conselhos × 1×/dia + 1 briefing × 1×/dia + CEO Mode reativo = ~10 chamadas/dia. **Estimativa cost:** baixo se usar Gemini Flash; alto se Claude Opus. **Decisão necessária:** modelo padrão.

---

## ✅ AUTORIZAÇÃO SOLICITADA

CTO, antes de escrever uma linha de código, **três perguntas**:

### Q1 — Sequência de fases
a) Autorizo A → B → C → D → E → F (sequência completa, ~12-17 dias)
b) Autorizo só A + B (consolidação + briefing) primeiro, depois reavaliamos
c) Pule A (não fazer consolidação agora, aceita débito) e vá direto B → C → D → E
d) Outra ordem (especificar)

### Q2 — Canal único do briefing 08:00
a) WhatsApp do CEO (usando `briefing_dispatcher.py` existente)
b) Painel "Café com o CEO" no SmartProv (web)
c) Ambos (WhatsApp envia link curto para o painel)
d) Email (não recomendado — risco de virar marketing)

### Q3 — Conselhos com agentes "responsáveis"
O CTO mencionou Camila / Álvaro / Pamela / Isabella / Presidente IA como responsáveis dos conselhos. Mas Pamela/Camila podem não ter implementação própria — pode ser **persona descritiva** sem código próprio. Autorizo:
a) Declarar **personas oficiais** sem promessa de IA dedicada (mais honesto)
b) Construir agentes próprios Pamela/Camila como parte da Fase A (mais escopo)
c) Sem agentes próprios — toda a inteligência vem do que já existe (Isabella + Álvaro + Presidente IA), com nomes humanos cosméticos
d) Investigar primeiro e decidir depois

### Q4 — Modelo LLM padrão para Conselhos
a) Gemini 3 Flash (rápido, barato, qualidade média)
b) Claude Sonnet 4.5 (qualidade alta, custo médio)
c) Claude Opus 4.5 (qualidade máxima, caro)
d) Gemini 3 Pro
e) Decidir após Fase A com dados de custo real

---

## 📎 ÍNDICE DE ARQUIVOS AUDITADOS NESTE DISCOVERY

Apenas leitura. Nenhuma alteração de código.

```
SERVICES (60 arquivos lidos):
  event_bus.py (227)              — barramento ✅ reuso integral
  presidente_ia_briefing.py (213) — base do briefing
  presidente_ia.py (660)          — health/risk/opp engine
  presidente_executive.py (884)   — relatórios full
  presidente_brain.py (520)       — contexto/memória
  presidente_operator.py (1032)   — execução
  isabella_conselho.py (224)      — conselho dos Commanders
  conselho_ia_scheduler.py (231)  — cron 08:00
  agent_bus.py (198)              — emite eventos de agente
  agent_revenue.py (452)          — receita por agente
  briefing_dispatcher.py (87)     — transporte WhatsApp
  executive_health.py             — saúde corporativa 0-100

ROUTES:
  conselho_ia.py (1362)           — _collect_* reusáveis
  presidente_ia.py (1131)         — dashboard + /conselho/{role}
  presidente_agentes.py (112)     — agentes registry view
  ai_dashboard.py                 — visão IA
  ai_center_*.py                  — paineis especializados

FRONTEND:
  ConselhoIaPanel.js              — UI conselho atual
  CentralIaDashboard.js           — central IA
  AICenterPanel.js                — center
  UniversoLigoCuradoriaPanel.js   — recém-criado

COLLECTIONS (snapshot 14/06/2026):
  motor_ia_events:        377k co-demo (377/432 = 87% real)
  nervous_events:          37k co-demo
  isabella_commander_opportunities:  2.041 co-demo
  isabella_council_minutes:        53 co-demo (38% sintético nos outros)
  motor_ia_actions/decisions/outcomes/learnings: 2.0-2.4k cada co-demo
  executive_ledger:    16 co-demo / 2.351 total (99,3% sintético) ⚠️
  nps_responses_mvp:    1 doc (recém-criado)
  conselho_ia_settings: 1 doc co-demo
  universo_ligo_invites: 4 docs co-demo (recém-criado)
```

---

**VOCÊ AUTORIZA o início pela Fase A?** Responda Q1-Q4 acima.
