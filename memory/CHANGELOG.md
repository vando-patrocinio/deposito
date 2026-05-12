# PontoIA — Changelog

## Feb 11, 2026 — Kill-switch por grupo (bulk pause/resume)

### Backend (`routes/motor_ia.py`)
- Novo endpoint `PUT /api/motor-ia/agents/group/{group_name}` (admin only)
- Aplica `set_agent_state` em loop para todos os agentes do grupo
- Retorna `{group, affected:[ids], changed:[ids], total}` — cliente sabe quantos efetivamente mudaram
- Grupo inexistente → HTTP 404

### Frontend (`MotorIaAgentsModal.js`)
- Botão **"Pausar grupo" / "Reativar grupo"** no header de cada grupo (à direita)
- Vermelho quando todos ativos (oferece pausar), verde quando algum/todos pausados (oferece reativar)
- Confirmação com `window.confirm` antes de aplicar
- Otimistic update na UI após sucesso
- `api.motorIaGroupToggle(groupName, enabled)` adicionada
- `pendingGroup` state evita clicks duplos

### Validação ✓
- `PUT /agents/group/Rede óptica` (encoded) com `{enabled:false}` → 2 agentes pausados + auditoria gravada
- Reativar idem (2 changes)
- Grupo inexistente retorna 404 com mensagem clara
- Lint frontend + backend limpos

---


## Feb 11, 2026 — Agrupamento de Agentes no Painel (6 grupos lógicos)

### Backend (`services/motor_ia.py`)
- Adicionado campo `group` no `AGENT_CATALOG` para cada agente:
  - **Rede óptica**: `smartolt_ai`, `proactive_outage_context`
  - **Operação · Lousa**: `sentinela_lousa`, `lousa_triagem`
  - **Atendimento**: `copilot_ai`, `isabella_whatsapp`, `voice_ai`
  - **Qualidade**: `central_ia_eval`, `central_ia_coach`
  - **AI Hub**: `aihub_chat`, `aihub_textgen`
  - **Insights & Analytics**: `ai_dashboard_insight`, `churn_insight`
- Reordenado catálogo para que agentes do mesmo grupo fiquem adjacentes
- `get_agents_state()` agora retorna `group` em cada agente (default `"Outros"`)

### Frontend (`MotorIaAgentsModal.js`)
- Lista renderiza com **cabeçalho sticky** por grupo (uppercase pequeno, contador de agentes + badge "X OFF" se houver pausados)
- Ordem dos grupos preserva ordem do catálogo (não alfabético)
- Mantém compatibilidade total — `data-testid` antigo (`agent-row-{id}`, `agent-toggle-{id}`) preservado

### Validação ✓
- `GET /agents` retorna 13 agentes em 6 grupos
- Frontend renderiza com cabeçalhos por grupo
- Lint frontend + backend limpos

---


## Feb 11, 2026 — Contexto de pane redigido pelo Claude (linguagem natural)

### Backend (`services/proactive_alerts.py`)
- `_build_outage_context` agora:
  1. Agrega dados brutos do Mongo (panes, severidade, tempo, causa recorrente)
  2. Pede ao Claude (`agent="proactive_outage_context"`, `max_tokens=120`, `temperature=0.3`) para redigir 2-3 bullets curtos em pt-BR
  3. Cacheia o resultado em memória por 10min/OLT — evita custo repetido
  4. Fallback automático para template fixo se Claude falhar ou agente desabilitado
- Novo agente registrado em `AGENT_CATALOG` + `AGENT_LABELS`: `proactive_outage_context` (aparece no Painel de Agentes com kill-switch e métricas)
- Custo aproximado: ~80 tokens/pane (~$0.0003), com cache de 10min é efetivamente <$0.01/dia

### Validação ✓
- 3 panes seed (2 cortes de fibra + 1 manutenção) → Claude gerou:
  ```
  • 3 panes em 14 dias, severidade média de 73,3%
  • Tempo médio de resolução: 1h26min
  • Causa principal: corte de fibra (2 ocorrências)
  ```
- Cache funciona: segunda chamada retorna mesmo texto sem nova chamada Claude
- Fallback testado (mesma estrutura, sem dependência de Claude)
- Lint backend limpo

---


## Feb 11, 2026 — Contexto rico na notificação de pane (histórico recente)

### Backend (`services/proactive_alerts.py`)
- Novo helper `_build_outage_context(cid, outage)`:
  - Busca panes da mesma OLT em 14 dias
  - Agrega: total de panes, severidade média, tempo médio de resolução, causa recorrente (extraída do `ai_insight.probable_cause` quando o mesmo motivo aparece ≥2x)
- `notify_outage` insere o snippet entre as KPIs e as opções:
  ```
  📊 Histórico recente:
  • Esta OLT teve 3 pane(s) em 14 dias
  • tempo médio de resolução: 1h35min
  • severidade média: 58.3%
  • causa recorrente: corte de fibra (2x)
  ```
- Sem histórico (pane inédita) → snippet é omitido automaticamente

### Validação ✓
- Seed com 3 panes (2 cortes de fibra + 1 queda de energia) → snippet gerado corretamente identificando "corte de fibra" como causa recorrente (2x)
- Tempo médio formatado (`58min` ou `1h35min`)
- Sem histórico → snippet vazio, mensagem original mantida
- Lint backend limpo

---


## Feb 11, 2026 — Lista numerada de ações no WhatsApp do gestor

Substituí "sim/não" por menu numerado de até 4 opções. Mais expressivo, mantém simplicidade.

### Backend (`services/proactive_alerts.py`)
- `notify_outage` agora envia menu numerado:
  - **1** — Avisar os N clientes por WhatsApp
  - **2** — Abrir alerta na Lousa (equipe técnica)
  - **3** — Fazer ambos
  - **4** — Ignorar / já está sendo tratado
  - Auto-ajusta quando não há clientes com telefone (remove opções 1 e 3)
- `execute_pending` reescrito:
  - Match por número (`1`, `2`, `3`...) → opção específica
  - Atalho `sim` → primeira opção · `não` → última opção
  - Texto ambíguo → mantém pending e envia "Responda com o número da opção: 1=Avisar... · 2=..."
  - Backward-compat com pendings antigos sem `options`
- Nova ação `lousa_alert`: cria 1 ticket na Lousa AI por cliente afetado (upsert por outage_id+phone, `kind=outage_team`)

### Validação ✓
- `"2"` → criou 3 alertas Lousa (`created_by=proactive_alerts`)
- `"3"` → broadcast 3/3 clientes + 3 alertas Lousa
- `"4"` → marcado como visualizado, sem ação
- `"depois eu vejo"` → resposta clara com lista numerada de opções
- Lint backend limpo

---


## Feb 11, 2026 — Alertas Proativos via WhatsApp (sistema pergunta, gestor decide)

### Backend
- Novo `services/proactive_alerts.py`:
  - `notify_outage(cid, outage)`: detecta pane SmartOLT → envia pergunta ao gestor por WhatsApp + persiste estado em `manager_assistant_pending` (TTL 30min) + flag `proactive_notified_at` no outage (anti-flood 30min)
  - `get_active_pending(cid, phone)`: recupera ação aguardando confirmação
  - `execute_pending(cid, pending, decision_text)`: interpreta sim/não/ambíguo:
    - **Sim** → `_execute_outage_broadcast`: envia aviso padrão para todos os `affected_phones` via sidecar (com rate limit interno)
    - **Não** → marca como `rejected`
    - **Ambíguo** → mantém pending, pede clarificação
- `services/smartolt_ai.py`: após detectar nova pane, chama `notify_outage` automaticamente
- `services/manager_assistant.py`: hook **antes** da classificação de intenção — se há pending ativo, processa ele primeiro

### Validação end-to-end ✓
- Simulou outage TEST-FAKE-OLT (5/5 LOS, 2 clientes afetados) → mensagem entregue ao gestor + pending persistido
- "sim" → broadcast executado para 2/2 clientes + pending resolvido
- "não, deixa pra lá" → marcado como rejected, sem broadcast
- "depois eu vejo" → mantém pending, pede confirmação clara
- Anti-flood funcional (mesmo outage não dispara 2x em 30min)
- Lint backend limpo

### Como funciona na prática
1. SmartOLT detecta pane crítica
2. Sistema dispara: "🚨 PENHA_HUAWEI — 47 ONUs LOS. Quer avisar os clientes? sim/não"
3. Gestor responde **sim** → todos os 47 clientes recebem aviso padrão automaticamente
4. Gestor responde **não** → nada acontece, alerta marcado como visualizado
5. Auditoria completa em `manager_assistant_pending` e `manager_assistant_log`

---


## Feb 11, 2026 — Manager Assistant: catálogo expandido (5 novos comandos)

Expandido de 4 para 9 comandos. Adicionados controle de agentes IA, monitoramento de rede e visão geral do sistema, tudo via WhatsApp.

### Backend (`services/manager_assistant.py`)
- Catálogo `COMMANDS` ampliado:
  - **`pause_agent`** / **`resume_agent`**: liga/desliga agente IA pelo nome livre. Match aproximado contra `AGENT_CATALOG` (substring + tokens). Reusa `set_agent_state` (audita em `ai_agent_switch_history`). Ex: "pausa o copilot", "religa isabella".
  - **`smartolt_report`**: conta panes ativas + top 3 OLTs com mais ONUs em LOS via aggregation.
  - **`system_status`**: agentes ativos/pausados, status do WhatsApp (consulta sidecar :3002/status), total de alertas Lousa e panes de rede.
  - **`tickets_today`**: agregação de tickets por `type` criados desde 00:00 UTC do dia.
- `_quick_intent` agora retorna `(intent, params)` para capturar parâmetros direto na regex (ex.: nome do agente).
- `_resolve_agent_id` faz fuzzy match: nome exato → substring → tokens.

### Validação end-to-end ✓
- "pausa o copilot" → `Co-Pilot IA` pausado (estado persistido + auditoria automática)
- "religa isabella" → `Isabella (WhatsApp)` reativado
- "relatório SmartOLT" → "🟠 1 pane ativa. PENHA_HUAWEI: 1 ONU LOS de 1 (100%)"
- "status do sistema" → "12/12 ativos · WhatsApp 🟢 · 148 alertas · 1 pane"
- "tickets do dia" → "9 no total · reparo:6 · instalacao:2 · retirada:1"
- Lint backend limpo

---


## Feb 11, 2026 — Manager Assistant via WhatsApp (gestor envia comando, IA executa)

### Backend
- Novo `services/manager_assistant.py`:
  - Catálogo de 4 comandos: `help`, `briefing`, `list_churn`, `create_retention_alert`
  - **Heurística rápida** com regex pra comandos óbvios (sem custo de LLM)
  - Fallback: Claude classifica intenção em JSON estruturado (`temperature=0.0, json_mode=true`)
  - **Whitelist dupla**: telefone do gestor já cadastrado em `churn_briefing_schedule.notify_phone` + lista manual em `manager_assistant_phones`
  - **Audit log** em `manager_assistant_log` (cada comando: input, intent detectada, params, reply)
- `routes/whatsapp_baileys.py`: hook em `inbound_webhook` ANTES do auto-reply ao cliente. Se for gestor → executa comando, envia resposta via sidecar, persiste como outbound e retorna 200.
- `routes/churn.py`: REST CRUD da whitelist + log
  - `GET /manager-assistant/phones` (lista — inclui o do schedule)
  - `POST /manager-assistant/phones` (admin only — adiciona)
  - `DELETE /manager-assistant/phones/{phone}` (admin only)
  - `GET /manager-assistant/log?limit=N`

### Validação ✓
- `_is_manager_phone` rejeita corretamente telefone fora da whitelist (`None`)
- Comando "ajuda" retorna menu formatado pra WhatsApp
- "lista de churn" retorna estado correto (nenhum finalizado no momento)
- "abre alerta retenção" **criou 39 alertas reais** na coleção `lousa_alerts` com `kind=retention, severity=alta, created_by=manager_assistant` ✓
- Comando não reconhecido cai em fallback elegante
- Lint backend limpo

### Como usar
1. Em **Central IA → Churn**, configure o WhatsApp do gestor no card de agendamento.
2. Esse mesmo número é automaticamente incluído na whitelist do assistente.
3. Envie "ajuda" pelo WhatsApp → recebe o menu.
4. Envie qualquer comando ou texto livre → IA classifica e executa.

---


## Feb 11, 2026 — Briefing automático diário + entrega via WhatsApp

### Backend
- Novo `services/churn_scheduler.py`: worker que checa a cada 60s se está na hora-alvo, gera briefing via Motor IA (Claude Sonnet 4.5) e envia resumo curto pelo sidecar Baileys.
  - Idempotente: `last_run_date` evita 2 disparos/dia
  - Mensagem WhatsApp formatada com markdown (negrito) + bullets das top 3 recomendações
  - Best-effort no envio (não bloqueia se WhatsApp falhar)
  - Lê config por empresa em `churn_briefing_schedule` (default: 12:00 UTC ≈ 09:00 BRT)
- `routes/churn.py`: novos endpoints
  - `GET /api/churn/briefing-schedule` (lê config)
  - `PUT /api/churn/briefing-schedule` (admin only — ativa/desativa, hora, minuto, telefone, janela)
  - `POST /api/churn/briefing-schedule/run-now?days=N` (admin only — dispara agora sem afetar `last_run_date`)
- `server.py`: worker `start_churn_scheduler()` startado no startup.

### Frontend
- Novo `ChurnBriefingScheduleCard.js`: card compacto ao final da sub-aba Churn com:
  - Toggle Ativar
  - Hora/Minuto UTC (com preview BRT)
  - Telefone WhatsApp do gestor
  - Janela (7/30/90/180d)
  - Botão **Testar agora** (não envia WhatsApp)
  - Status do último disparo + se WhatsApp foi entregue

### Validação ✓
- Worker iniciado no startup
- `PUT /briefing-schedule` salva config com `updated_by`
- `POST /run-now` retornou briefing real (`ci-co-demo-2026-05-11-30`, 39 churns)
- Log: `[churn-scheduler] briefing gerado ci-co-demo-2026-05-11-30 (churn=39)`
- Lint frontend + backend limpos

---


## Feb 11, 2026 — Histórico de Briefings + Comparação IA

### Backend (`routes/churn.py`)
- `POST /api/churn/ai-insight`: agora persiste o briefing em coleção `churn_insights` (upsert por chave `ci-{cid}-{date}-{days}` — máx 1 por dia por janela).
- `based_on` enriquecido com `by_reason`, `by_neighborhood`, `by_kind`, `avg_lifetime_days` para suportar comparação.
- Novo `GET /api/churn/ai-insight/history?limit=N`: lista briefings (mais recentes primeiro, sem o texto completo, só metadados).
- Novo `GET /api/churn/ai-insight/{id}`: retorna 1 briefing histórico completo.
- Novo `POST /api/churn/ai-insight/compare?base_id=&against_id=`: gera comparação narrativa via Claude (3 seções: Evolução / Mudança de padrões / O que fazer diferente). Usa setas ↑↓→.

### Frontend (`ChurnDashboardPanel.js`)
- Novo botão dropdown **História** (ícone `History` + contador) ao lado de "Analisar com IA": lista briefings salvos com data, janela e churn total. Click carrega o briefing antigo.
- Novo botão **"Comparar com anterior"** dentro do card de insight (aparece quando há ≥2 no histórico). Click chama o endpoint compare e renderiza card pontilhado roxo abaixo do briefing.
- Comparação destaca ↑ (vermelho), ↓ (verde), → (cinza) automaticamente via regex no HTML render.

### Validação ✓
- Geramos 2 briefings (180d + 90d) e ambos salvos no Mongo
- `GET /history` retornou 2 itens com metadados
- `POST /compare` retornou comparação narrativa estruturada do Claude (Evolução dos números, Mudança de padrões, 3 recomendações)
- Frontend: dropdown abre, click carrega briefing histórico, botão Comparar renderiza card roxo de comparação ✓
- Lint frontend + backend limpos

---


## Feb 11, 2026 — Briefing executivo de Churn por IA (Claude Sonnet 4.5)

### Backend
- `routes/churn.py`: novo endpoint `POST /api/churn/ai-insight?days=N`. Reusa dados do dashboard, monta prompt estruturado (Diagnóstico / Padrões / Riscos / Recomendações), chama Motor IA via `chat_completion(agent="churn_insight", max_tokens=900, temperature=0.35)`.
- Catálogo de agentes: novo `churn_insight` (`AGENT_CATALOG` em `services/motor_ia.py` + `AGENT_LABELS` em `routes/motor_ia.py`).
- Respeita kill-switch: se `churn_insight` desligado → 503 com mensagem clara.

### Frontend
- `ChurnDashboardPanel.js`: novo botão **"Analisar com IA"** (gradiente roxo/indigo) no header.
- Card de briefing com gradiente sutil, ícone Sparkles, parser leve de markdown (negrito + bullets) usando `dangerouslySetInnerHTML` com escape prévio para evitar XSS.
- Estados: loading ("Claude está analisando…"), erro, colapsável (chevron up/down).
- Footer com modelo/provider/janela.

### Validação
- `POST /api/churn/ai-insight?days=180` retornou briefing completo de Claude Sonnet 4.5 (Amazon Bedrock) com 4 seções perfeitas: Diagnóstico apontou inconsistência (0% rate com 38 movimentações), Padrões identificou Cordovil (37%), Riscos apontou pipeline matematicamente impossível, 4 recomendações acionáveis ✓
- Frontend renderiza loading e card corretamente (screenshot) ✓
- Lint frontend + backend limpos ✓

---


## Feb 11, 2026 — Dashboard de Churn (Central IA → sub-aba "Churn")

Aplicadas best practices ISP/Telecom 2026 (pesquisa Feb/2026): múltiplas dimensões (tempo, geografia, motivo), distinção entre pedido vs operação, tempo médio de vida, pipeline de churn iminente.

### Backend
- Novo `routes/churn.py` registrado em `server.py` (`/api/churn/dashboard`).
- Fonte: coleção local `tickets` (já sincronizada do Atlaz periodicamente) filtrando `type='retirada'` (mapeia CANCELAMENTO + RETIRADA DE EQUIPAMENTO).
- Inferência de motivo por regex em assunto/relato: Preço/Concorrência, Mudança, Problema técnico, Atendimento ruim, Financeiro, Falecimento, Retirada, Outros.
- Tempo de vida calculado quando há ticket de `type=instalacao` do mesmo `atlaz_id_assinante`/`client_id` (média + mediana + amostragem).
- Série temporal: 12 meses fixos com zero-fill.
- Retorna: KPIs, by_month, by_reason, by_neighborhood, by_kind, recent (últimos 20).

### Frontend
- Novo `ChurnDashboardPanel.js`: header com gradiente vermelho, seletor 30/90/180/365 dias, 4 KPI cards, barras mensais animadas, top motivos colorido, top bairros, split pedido×operação, lista de últimos 20 cancelamentos.
- `CentralIaDashboard.js`: adicionada sub-aba "Churn" ao lado de Dashboard IA e SmartOLT AI (ícone `TrendingDown`).
- `api.js`: `churnDashboard(days)`.

### Validação ✓
- Endpoint retorna 38 chamados de churn no período (37 retiradas + 1 outros)
- Top bairros: Cordovil (14), Ramos (3), Irajá (2)
- Frontend renderiza com sucesso (screenshot validado)
- Lint frontend + backend limpos

---


## Feb 11, 2026 — WhatsApp Sidecar v2 (production-hardened)

Aplicadas as melhores práticas para Baileys em produção (pesquisa Feb/2026):

### Sidecar Node (`/app/whatsapp-service/server.js` — reescrita completa)
- **Reconexão com exponential backoff + jitter** (base 2s → cap 5min, 12 tentativas máx). Antes: fixo 3s/5s infinito.
- **Circuit breaker**: ao atingir `RECONNECT_MAX_RETRIES`, notifica admin via webhook e para de tentar.
- **Taxonomia de DisconnectReason**: `loggedOut`/`connectionReplaced`/`forbidden` agora NÃO reconectam (precisa intervenção manual). `restartRequired`/`timedOut`/`badSession` reconectam normalmente. Estado `banned` exposto.
- **Timeouts explícitos Baileys**: `connectTimeoutMs=60s`, `defaultQueryTimeoutMs=60s`, `keepAliveIntervalMs=30s`.
- **Rate limiter no /send**: mínimo 1.2s entre envios + jitter 0-800ms. Reduz risco de ban.
- **Browser fingerprint realista**: `Chrome (Linux),Chrome,120.0.0` (configurável via `WA_BROWSER_FP`).
- **Logger estruturado pino** (info por padrão, debug via `WA_DEBUG=1`), com `base.svc`.
- **Webhook inbound com retry único** após 500ms — antes era 1 tentativa só.
- **Graceful shutdown** (SIGINT/SIGTERM) — fecha socket sem apagar sessão.
- **Handlers globais** `uncaughtException` e `unhandledRejection` (loga, não crasha).
- **Métricas no /health**: `uptime_s`, `retry_count`, `last_send_at`, `last_success_at`.

### Backend FastAPI (`routes/whatsapp_baileys.py`)
- Novo endpoint `POST /api/whatsapp-baileys/system-event` (recebe eventos críticos do sidecar com `X-WA-Token`).
- Persiste em coleção `whatsapp_system_events` ({event, code, name, retry_count, reason, created_at, acknowledged}).
- Novo `GET /api/whatsapp-baileys/system-events` (lista 50 últimos, role gestor).
- Eventos capturados: `logged_out`, `connection_replaced`, `possibly_banned`, `max_retries_exceeded`.

### Validação
- Sidecar reiniciou e conectou em <6s ✓
- `/health` retorna métricas novas ✓
- `/status` mantém compat (campos antigos + `retry_count` novo) ✓
- Evento simulado → persistido em Mongo + listado via GET ✓
- Lint backend limpo ✓

---


## Feb 11, 2026 — Overlay de incidentes na timeline de agentes

### Backend
- `routes/motor_ia.py`: endpoint `GET /api/motor-ia/agents/history` agora retorna `incidents[]` adicional:
  - `network_outages` no período → `kind:"outage"`, afetam `smartolt_ai` e `isabella_whatsapp`.
  - `lousa_alerts` no período → `kind:"sentinela"`, afetam `sentinela_lousa` e `lousa_triagem`.
  - Cada incidente trás `{id, kind, start, end, active, title, detail, affects:[agent_id...]}`.
- Helper interno `_gather_incidents(cid, start, end)`.

### Frontend
- `MotorIaAgentsHistoryView.js`: sobrepõe incidentes às barras de timeline dos agentes afetados (filtro por `inc.affects`).
  - Padrão hachurado em diagonal (laranja para panes, roxo para Sentinela).
  - Tooltip dedicado mostra tipo/título/detalhe/duração/intervalo.
  - Legenda atualizada com 4 itens (Ativo, Pausado, Pane, Alerta Sentinela).
  - Contêiner da barra perdeu `overflow:hidden` para a sobreposição ficar visível.

### Validação
- Endpoint retorna 114 incidentes nas últimas 168h (panes RIO_HUAWEI, PENHA_HUAWEI etc) ✓
- Cada incidente expõe `affects` correto ✓
- Lint frontend + backend limpos ✓

---


## Feb 11, 2026 — Auditoria de Mudanças de Agentes (timeline ON/OFF)

### Backend
- `services/motor_ia.py`: `set_agent_state` agora detecta transições reais (estado anterior ≠ novo) e grava em `ai_agent_switch_history` (`{company_id, agent_id, previous_enabled, enabled, changed_by, changed_at}`).
- Novo `get_agent_history()` retorna eventos no período.
- `routes/motor_ia.py`: novo endpoint `GET /api/motor-ia/agents/history?days=N` (1-90). Retorna:
  - `events` — lista de transições
  - `intervals_by_agent` — segmentos (start/end/enabled) cobrindo todo o período, pronto pra timeline
  - `downtime_by_agent` — segundos OFF e % do período pausado
  - Considera estado anterior ao início do período como ponto de partida

### Frontend
- Novo `MotorIaAgentsHistoryView.js`: timeline horizontal com seletor 24h/7d/30d/90d. Cada agente renderizado em linha com segmentos verde (ATIVO) / vermelho (PAUSADO). Hover mostra agente, estado, intervalo, duração. Lista textual dos últimos 50 eventos com timestamp, ON→OFF e quem alterou.
- `MotorIaAgentsModal.js`: adicionada navegação em abas (**Agentes** | **Histórico**). Footer contextual por aba.
- `api.js`: `motorIaAgentsHistory(days)`.

### Validação
- 4 transições simuladas em `copilot_ai` (off/on/off/on) registradas corretamente ✓
- `GET /agents/history?days=7` retorna 4 eventos, 5 intervalos calculados, downtime correto ✓
- Estado anterior ao período é considerado (não falha quando não há eventos no janela) ✓
- Lint frontend + backend limpos ✓

---


## Feb 11, 2026 — Painel de Agentes IA (kill-switch global)

### Backend
- `services/motor_ia.py`:
  - Nova exceção `AgentDisabledError` lançada por `chat_completion` quando o agente foi pausado pelo admin.
  - Catálogo `AGENT_CATALOG` com 11 agentes (SmartOLT, Sentinela, Triagem, Co-Pilot, Isabella, Voice, Central IA Avaliação/Coaching, AI Hub Chat/TextGen, Dashboard Insights).
  - Helpers `is_agent_enabled()`, `get_agents_state()`, `set_agent_state()`.
  - Verificação de kill-switch ocorre ANTES de qualquer custo (rejeita gastar tokens).
- `routes/motor_ia.py`: endpoints `GET /api/motor-ia/agents` (lista com estado e metadados de quem alterou) e `PUT /api/motor-ia/agents/{agent_id}` (admin-only).
- Coleção `ai_agent_switches` ({company_id, agent_id, enabled, updated_at, updated_by}). Default ativo (sem registro = enabled).

### Frontend
- Novo `MotorIaAgentsModal.js`: modal full com lista de agentes, toggles animados, indicador de pausados, footer explicativo, último alterador.
- `AiTopologyCard.js`: nó **Motor IA** (centro do hub) agora é clicável (`cursor:pointer`). Hint visual "Clique para gerenciar agentes" com bullet pulsante (amarelo). Click abre o `MotorIaAgentsModal`.
- `api.js`: `motorIaAgentsList()` e `motorIaAgentToggle(id, enabled)`.

### Validação
- `GET /api/motor-ia/agents` → 11 agentes, todos ativos por default ✓
- `PUT /api/motor-ia/agents/copilot_ai {enabled:false}` → state persistido com `updated_by: "Administrador"` ✓
- Teste end-to-end: `set_agent_state('smartolt_ai', false)` → `chat_completion` lança `AgentDisabledError` sem chamar OpenRouter ✓
- Re-enable funcional ✓
- Lint frontend + backend limpos ✓

---


## Feb 11, 2026 — Badge persistente de alerta de orçamento no header

### Frontend
- Novo `BudgetAlertBadge.js`: componente que faz polling em `/api/motor-ia/budget/status` a cada 60s e renderiza um badge clicável no header SOMENTE quando o status é `warn` (amarelo) ou `exceeded` (vermelho). Click navega direto para a aba Motor IA.
- Animação CSS `pulse` contínua (sutil) + `pulse-strong` (forte, 3x) ao detectar transição de estado.
- Tooltip exibe gasto / limite / %. Oculto para roles sem acesso ao Motor IA.
- `App.js`: badge integrado entre `NotificationsBell` e `ServerClock` no `TopBar`; `setView` propagado.

### Validação
- API confirmou status `exceeded` (limite 0.03 USD, gasto 0.051 = 170%) ✓
- Limite restaurado para 50 USD / 80% threshold ✓
- Lint frontend limpo ✓

---


## Feb 11, 2026 — Alertas de Orçamento Motor IA

### Backend
- `routes/motor_ia.py`: novos endpoints `GET /api/motor-ia/budget`, `PUT /api/motor-ia/budget` (admin), `GET /api/motor-ia/budget/status` (mês corrente vs limite + projeção linear).
- Coleção `motor_ia_budget` ({company_id, monthly_limit_usd, warn_threshold_pct, enabled}).
- `services/motor_ia.py`: `_check_budget_alert()` chamado após cada `_log_usage` — loga `WARNING` quando gasto do mês ultrapassa threshold (default 80%) ou 100% do limite. Best-effort, não bloqueia chamadas.
- Status: `ok` | `warn` | `exceeded` | `disabled`.

### Frontend
- Novo `MotorIaBudgetCard.js`: barra de progresso com marca do threshold, painel de status colorido (verde/amarelo/vermelho), card de projeção mensal, e form inline (limite USD + threshold % + toggle "ativar alertas").
- `api.js`: `motorIaBudgetGet/Save/Status`.
- `App.js`: card inserido na aba Motor IA acima do dashboard de uso.

### Validação
- `PUT /api/motor-ia/budget` com limite 0.01 USD → status `exceeded` ✓
- Backend log `[motor-ia][BUDGET] Limite mensal EXCEDIDO para co-demo: $0.0242 / $0.01 (242.0%)` ✓
- Projeção linear funcional (`projected_month_usd`) ✓
- Lint backend + frontend limpos ✓

---


## Feb 11, 2026 — Dashboard "Custo do Motor IA"

### Backend
- `services/motor_ia.py`: instrumentado `chat_completion` para capturar `usage` (prompt/completion tokens) e persistir em coleção `motor_ia_usage`. Best-effort (não bloqueia resposta).
- Tabela `MODEL_PRICING` (USD por 1M tokens) com Claude 4.5 (Sonnet/Opus/Haiku), GPT-4o, DeepSeek, Gemini, Llama. Match por modelo exato + por prefixo (ex.: versionados `-20250929`).
- Nova param `agent: str` em `chat_completion` para identificar o chamador.
- Atualizado callers principais com `agent=`: `smartolt_ai`, `sentinela_lousa`, `lousa_triagem`, `copilot_ai`, `isabella_whatsapp` (WhatsApp Baileys), `aihub_chat`, `aihub_textgen`, `central_ia_eval`, `central_ia_coach`, `voice_ai`, `ai_dashboard_insight`.
- `routes/motor_ia.py`: novo endpoint `GET /api/motor-ia/usage?days=N` (1-90 dias). Retorna `totals`, `by_agent` (com labels amigáveis), `by_model`, série diária `daily`.

### Frontend
- Novo `MotorIaUsageCard.js`: seletor de período (7/30/90d), 4 métricas (custo USD, tokens entrada/saída/totais), barras horizontais por agente, lista por modelo, sparkline diária.
- `api.js`: adicionado `motorIaUsage(days)`.
- `App.js`: card integrado à aba Motor IA acima do `MotorIaCard`.

### Validação
- `POST /api/motor-ia/test` registra uso ✓
- `GET /api/motor-ia/usage?days=30` retorna agregação correta (calls, USD, by_agent, by_model, daily) ✓
- Frontend lint limpo ✓

---


## Feb 11, 2026 — Motor IA migrado para Claude Sonnet 4.5

### Backend
- `services/motor_ia.py`: `DEFAULT_TEXT_MODEL` agora é `anthropic/claude-sonnet-4.5` (antes `openai/gpt-4o-mini`). Fallback chain reordenada com Claude primeiro.
- Adicionado safeguard: array `models` enviado ao OpenRouter é truncado para no máximo 3 itens (limite da plataforma).
- `routes/motor_ia.py`: tiers de modelos sugeridos atualizados — `fast` usa Claude Haiku 4.5, `balanced` usa Claude Sonnet 4.5, `premium` usa Claude Opus 4.5.
- Migração no Mongo aplicada em `motor_ia_config` (`co-demo`): default + fallback_models alinhados com Claude.

### Validação
- `POST /api/motor-ia/test` → `{"ok": true, "model": "anthropic/claude-4.5-sonnet-20250929", "provider": "Amazon Bedrock"}` ✓
- Agentes de atendimento (Jerusa/WhatsApp) continuam em DeepSeek (regra de negócio mantida) ✓

---


## Feb 10, 2026 — Sidebar com sub-itens expansíveis (Clientes → Assinantes)

### Frontend
- `App.js`: NAV_GROUPS suporta `children[]`. Item pai com children renderiza chevron e expande/colapsa ao clicar (estado em `expandedParents` Set). Auto-expand quando view atual pertence a um filho. Filhos identados (`paddingLeft: 32, fontSize: 12.5`).
- `ALL_TABS` agora inclui flat dos filhos com `roles` herdados do pai (necessário para o filtro de permissões).
- Item "Assinantes" virou filho de "Clientes" no grupo Pessoas. Para acessar Assinantes: clicar em **Clientes** (expande) → clicar em **Assinantes**.

### Validação
- Antes do clique em "Clientes": filho "Assinantes" oculto ✓
- Após clique: chevron muda de `>` para `v` e Assinantes aparece identado ✓
- Clique em Assinantes abre o painel correto ✓

---

## Feb 10, 2026 — Aba Assinantes redesenhada estilo Atlaz

### Backend
- Novos campos opcionais em `SubscriberIn`/`SubscriberUpdate`: `nickname`, `rg_ie`, `branch` (filial), `billing_method`, `contract_status`, `contracts_count`, `due_day` (dia do vencimento)
- `GET /api/subscribers` repaginado com filtros granulares estilo Atlaz: `name, email, phone, document, street, number, district, city, state, zip_code, complement, branch, billing_method, contract_status, status, external_code` + paginação real (`page`, `page_size`, retorna `total`/`pages`)
- Filtro `phone` agora casa pelos últimos 8 dígitos via regex sufixo (funciona com qualquer formato/máscara)
- Listagem inclui `primary_address_summary` (rua, número, bairro, cidade) para exibir direto na tabela

### Frontend (`SubscribersPanel.js` reescrito)
- **Painel de filtros expansível** no topo com 14 campos (Nome/Apelido, E-mails, Telefones, CPF/CNPJ/RG/IE, Rua, Número, Bairro, Cidade, Estado, CEP, Complemento, ID Assinante) + 3 dropdowns (Filial, Método de cobrança, Status do contrato) + Status do assinante
- Botão **"Mostrar filtros avançados"** + Limpar + **Aplicar filtro**
- **Contador**: "Assinantes encontrados: X" com número em destaque
- **Barra de ações**: ícones (Exportar CSV, Imprimir, E-mail, WhatsApp, Atualizar) + dropdown "Selecione uma ação" + Executar + Importar CSV + Novo assinante
- **Tabela densa** com 9 colunas: checkbox bulk, Nome (clicável), Filial, Contratos, Venc. (dia), Endereço, Telefone, Status (pill), Ações (editar/histórico)
- **Paginação real** com seletor de tamanho (25/50/100/200) e botões prev/next
- **Bulk export CSV** para selecionados; bulk print para a página atual

### Tests
- Manual curl: PATCH com novos campos OK (branch, due_day, billing_method etc), filtro phone parcial (`998176526`) casa o Vando, filtro branch funciona

### Validação visual
- Screenshot confirma identidade com o Atlaz: contador, barra de ações com ícones, tabela com colunas idênticas

---

## Feb 10, 2026 — Aba Assinantes (Subscribers) com auto-link por telefone

### Backend
- **Phone normalizer** (`/app/backend/phone_normalizer.py`): converte qualquer formato BR (`5521998176526@c.us`, `+55 (21) 99817-6526`, `021998176526`, `21 99817-6526`) para canônico `5521998176526`. Função `get_phone_lookup_variants()` retorna variantes para casar com cadastros antigos.
- **Subscribers CRUD** (`routes/subscribers.py`): assinante com phones[] + addresses[] + tags + plan + status (ATIVO/BLOQUEADO/SUSPENSO/CANCELADO/EM_INSTALACAO/AGUARDANDO_VIABILIDADE/SEM_VIABILIDADE/PROSPECT/INADIMPLENTE). Document mascarado na listagem (`***-XX`), full apenas no detalhe.
- **Match service**: `find_subscriber_by_phone()` retorna `matched | conflict | not_found` + auditoria em `subscriber_match_log`.
- **Subscriber context**: `build_subscriber_context()` monta bloco de texto para injetar no system_prompt do agente IA — nome, status, plano, localização (bairro/cidade), tags, notas, últimas 5 chamadas resumidas + regras de privacidade.
- **CSV import** (`POST /import`): aceita colunas PT-BR (`nome, telefone_principal, plano, status, ...`), normaliza phones, detecta conflitos, retorna `{created, updated, errors, conflicts}`.
- **Conflitos**: `GET /subscribers/conflicts` lista phones com >1 vínculo (aggregation).
- **Auto-link integrado em 3 pontos do aihub**:
  - `POST /api/aihub/calls/outbound` → vincula `subscriber_id` ao iniciar chamada
  - `POST /api/aihub/webhooks/call-event` → vincula `subscriber_id` + `subscriber_match_status` ao receber evento
  - `POST /api/aihub/agents/{id}/playground` → aceita `subscriber_id` opcional, injeta `build_subscriber_context()` no prompt
- Mensagens do playground persistem `subscriber_id` para `/subscribers/{id}/history` agregar conversas IA.

### Frontend
- `SubscribersPanel.js`: lista com filtros (busca, status, plano), formulário completo (telefones múltiplos com checkbox principal/WhatsApp, endereço primário, tags), histórico com calls + sessões IA, importador CSV com instruções e relatório.
- Sidebar: novo item **"Assinantes"** no grupo Pessoas (entre Cadastro e Praças) com ícone UserCircle.
- `TabPermissionsCard.js`: aba registrada em `TAB_DEFINITIONS` + ticada por default para administrador/auditor/gestor (regra do user). Merge automático aplica para configs antigas.

### Tests
- `iteration_37.json`: **19/19 pytest backend OK** + frontend smoke completo. Vando Patrocinio (`sub-c1a6d684e0`, telefone `5521998176526`) renderiza com pill ATIVO, plano, tags, e formulário de edição abre populado.
- Validado: 4 formatos de phone diferentes matcham o mesmo subscriber, webhook auto-vincula, outbound persiste mesmo com falha de MB, playground com `subscriber_id` faz a IA chamar o cliente pelo nome.

---

## Feb 10, 2026 — Auto-merge de permissões para abas novas

### Frontend
- `TabPermissionsCard.js`: registrada `{ id: "aihub", label: "Atendimento IA" }` em `TAB_DEFINITIONS` + adicionada nas listas default de **administrador**, **auditor** e **gestor** em `DEFAULT_TAB_PERMISSIONS`.
- **Migration soft (useMemo)**: quando há `tab_permissions` salvo no banco mas faltam abas criadas DEPOIS, mergeia com o default — abas novas aparecem **JÁ TICADAS** para todos os perfis liberados. Ao primeiro toggle do gestor, o estado mergeado é consolidado na próxima gravação.
- `App.js`: mesma lógica de merge ao carregar `tab_permissions` para o sidebar — abas novas aparecem visíveis no menu lateral imediatamente.
- **Padrão para futuras abas**: sempre adicionar o ID em `TAB_DEFINITIONS` + `DEFAULT_TAB_PERMISSIONS` (todos os 3 perfis quando a aba é universal). Migration soft cuida do resto.

### Validação
- Curl: branding tinha `tab_permissions` salvo SEM `aihub`. Após merge, UI mostra **Atendimento IA marcada (3/3 perfis)** e sidebar exibe a aba para todos.

---

## Feb 10, 2026 — Discar com IA + Componente OutboundCallButton reutilizável

### Backend (`/app/backend/routes/aihub.py`)
- `POST /api/aihub/calls/outbound` (gestor): recebe `{agent_id, phone, contact_name?, contact_id?, notes?}`. Valida agente ativo + MagnusBilling configurado. Origina via `POST {url}/index.php/api/{originate_path}` (default `originate`) com params `key/secret/calledid/callerid/trunk + originate_extra`. Sanitiza phone (regex). Persiste `aihub_calls` com `direction=outbound`, `status=originated|failed`, `agent_id`, `agent_name` para correlação posterior com webhook de evento.
- Validações: 400 sem MagnusBilling configurado, 404 agente inexistente/inativo, 422 phone < 8 chars, 502 falha real do MB com erro detalhado.

### Frontend
- Nova sub-aba **"Discar"** em `AIHubPanel.js`: telefone + nome + agente IA (dropdown só ativos) + observações + botão "Iniciar chamada". Mostra resultado inline + lista de chamadas outbound recentes com status pill.
- Componente reutilizável **`OutboundCallButton`** (`/app/frontend/src/OutboundCallButton.js`): popover com dropdown de agentes ativos, props `phone`, `contactName`, `contactId`. Pode ser plugado em qualquer tela (CRM da Lousa, Estoque > Clientes, ficha de cliente, etc).

### Tests
- Manual curl: 400/404/422/502 todos validados, registro persistido em `aihub_calls` com status correto.

---

## Feb 10, 2026 — Atendimento IA (aba nova: agentes conversacionais + integrações)

### Backend (`/app/backend/routes/aihub.py`)
- **Agentes IA** CRUD (`/api/aihub/agents`): nome, system_prompt, model_provider, model_name, temperature, max_tokens, **form_fields** (formulário inteligente: chave/descrição/pergunta), **tools_enabled** (send_whatsapp, transfer_to_human, create_lead, schedule_appointment, get_current_date, hangup), webhook_url, active.
- **Modelos suportados** via Emergent LLM Key: Gemini 2.5 Flash/Pro, Claude Sonnet 4.5, Claude Haiku 4.5, GPT-5, GPT-5 mini.
- **Playground multi-turn** (`POST /agents/{id}/playground`): usa `LlmChat` com session_id persistente, salva mensagens em `aihub_messages`, devolve {session_id, reply, agent_name, model, turn_count}. Form fields injetadas no system_prompt.
- **Integrações** (`PUT /integrations/{type}` para `magnusbilling`, `whatsapp_cloud`, `whatsapp_web`): config genérica com **mascaramento de secrets** (•••) na resposta. Merge inteligente preserva valor real ao re-enviar mascarado.
- **Testes de conexão**: `POST /integrations/magnusbilling/test` (chama `/index.php/api/getInfo` com key+secret) e `POST /integrations/whatsapp_cloud/test` (chama Graph API `/v23.0/{phone_number_id}` com Bearer token). Persiste `last_test_at`/`last_test_error`.
- **Proxy MagnusBilling**: `GET /magnusbilling/dids`, `GET /magnusbilling/cdr` autenticam via integração salva.
- **Webhook receiver** (`POST /webhooks/call-event`, sem auth): registra evento e cria/atualiza `aihub_calls`.
- **Histórico**: `GET /history/calls`, `GET /dashboard` (agregados).

### Frontend (`/app/frontend/src/AIHubPanel.js`)
- 5 sub-abas: **Agentes** (CRUD com editor completo: prompt textarea, modelo dropdown, slider temperatura, formulário inteligente com adicionar/remover, checklist de tools), **Playground** (chat multi-turn com bolhas teal/branco), **MagnusBilling** (configuração + teste + listar DIDs/CDR), **WhatsApp Cloud** (configuração + teste + URL do webhook pra colar no Meta), **Histórico** (dashboard com stats + lista de chamadas).
- Sidebar: novo item **"Atendimento IA"** no grupo "Inteligência" com ícone Bot.

### Tests
- `iteration_36.json`: **18/18 pytest backend OK** + frontend smoke completo (login → sidebar → 5 abas → criar agente → playground com IA real respondendo)

---

## Feb 10, 2026 — Assinatura digital do recebedor + histórico de devoluções

### Backend
- `POST /api/collab-assets/return-confirm/{cid}` (gestor): recebe `{receiver_name, receiver_role, signature_data_url, notes, confirmed_item_keys}`:
  - Persiste auditoria em `db.collab_returns` (snapshot de assets + extras + chaves conferidas)
  - Marca `collaborator_assets` ativos como `status="devolvido"` com `returned_at`, `returned_to`, `return_id` + event log
  - Gera PDF com **assinatura embutida** (Image flowable do ReportLab a partir do base64 PNG)
  - Retorna stream com header `X-Return-Id`
- `GET /api/collab-assets/returns/{cid}`: histórico de devoluções (signature_data_url EXCLUÍDO da resposta para privacidade)
- `_build_romaneio_pdf(receiver={...})` embute assinatura na coluna direita + label "assinado em <data>"
- ONTs e insumos NÃO são auto-devolvidos — gestor decide manualmente em Estoque (revalidação física)

### Frontend
- `DeactivationAssetsModal.js` fluxo em 2 passos com stepper visual:
  - **Passo 1**: Checklist (precisa marcar TODOS os itens para avançar)
  - **Passo 2**: Canvas de assinatura (mouse + touch) + input nome do recebedor + cargo + observações
- Botão final faz POST → recebe blob PDF → abre em nova aba
- `api.js`: `assetReturnConfirm(cid, payload)` (responseType: "blob"), `assetReturnsHistory(cid)`

### Tests
- `iteration_35.json`: **9/9 pytest** — return-confirm, side-effects, persistência, privacidade signature, validação 422, regressão mode=return base, lint frontend OK

---

## Feb 10, 2026 — Romaneio de DEVOLUÇÃO À EMPRESA (desativação de colaborador)

### Backend
- `routes/collaborator_assets.py::_build_romaneio_pdf`: aceita `mode="delivery"|"return"`. No modo `return`:
  - Título: "CHECKLIST DE DEVOLUÇÃO À EMPRESA — TERMO DE RECEBIMENTO"
  - Coluna **Devolvido** com checkbox real desenhado (`Drawing+Rect` em ReportLab — caixa vazia 14x14)
  - Termo de recebimento PELA EMPRESA (substitui o "Termo de Responsabilidade")
  - 2 linhas de assinatura: colaborador (entregando) + responsável da empresa (recebendo)
- `_collect_extra_custody(company_id, cid)`: coleta TUDO em posse do técnico além dos pertences:
  - ONTs no estoque (`stok_onts` location_type=tecnico)
  - Insumos no estoque (`stok_stock` location=collaborator_id)
- Endpoints atualizados com query `?mode=return`:
  - `GET /api/collab-assets/romaneio/{cid}?mode=return`
  - `GET /api/collab-assets/public/romaneio/{cid}?mode=return`
- Novo endpoint `GET /api/collab-assets/custody-full/{cid}` retorna assets+extras normalizados

### Frontend
- `DeactivationAssetsModal.js` reescrito (sem emojis, com `lucide-react`):
  - Lista TUDO em posse (assets + ONTs + insumos) com badges coloridos por origem
  - Checkbox por item para conferência presencial
  - Botão "Marcar todos / Desmarcar todos"
  - Status visual de conferência (X de N itens conferidos)
  - Botão final gera o PDF "Romaneio de Devolução à Empresa"
- `api.js`: `assetCustodyFull(cid)`, `assetDevolucaoUrl(cid)`, `assetRomaneioUrl(cid, only_active, mode)`

### Tests
- `iteration_34.json`: 8/8 pytest backend OK — `/custody-full`, `/romaneio?mode=return`, regressão delivery, regex inválido

---

## Feb 10, 2026 — Dark Mode toggle + Manufacturer-quality matching melhorado

### Frontend (Dark Mode)
- `App.js`: hook `useTheme()` (persistido em localStorage `ponto_theme`, respeita `prefers-color-scheme`)
- Botão `data-testid="theme-toggle-btn"` (Sun/Moon do lucide) no TopBar
- `index.css`: variantes `.dark` para soft backgrounds (success/warning/danger/info/accent), shadows com mais contraste, e adaptadores para `body` e `app-topbar`

### Backend (Manufacturer Quality)
- `routes/ai_dashboard.py::manufacturer_quality`: substituído lowercase trivial por `_norm()` (sem acento, sem espaços/_/-) e tenta casar via `pppoe_user` OU `name`
- Resultado: chamados cruzados subiram de 0/20 → 9/20 (45% match) — agora ranking mostra defect_rate real por marca

### Tests
- `iteration_33.json`: backend 5/5 pytest OK, frontend smoke completo OK

---

## Feb 10, 2026 — Ranking "Qualidade de fabricantes" no IA Center

### Backend
- `routes/ai_dashboard.py`: novo endpoint `GET /api/ai/dashboard/manufacturer-quality?days=90` cruza:
  - Fabricante de cada ONU (de `smartolt_onus` + prefixo + `manufacturer_cache`)
  - Chamados Atlaz tipo "reparo" nos últimos N dias (match por nome do cliente)
- Retorna `{rows[]}` com `{manufacturer, onus_in_field, defect_calls, defect_rate_pct}`, ordenado por taxa de defeito desc
- Inclui `matched_calls` e `unmatched_calls` para diagnóstico de qualidade da sincronização Atlaz↔SmartOLT (quando 0% match, sinaliza no UI)

### Frontend
- `AICenterPanel.js`: nova sub-aba **"Qualidade de fabricantes"** (id=`manuf_quality`) com `ManufacturerQualitySection`:
  - Subtítulo com totais (ONUs, reparos, cruzados)
  - Aviso âmbar quando 0 chamados foram cruzados (problema de naming entre sistemas)
  - Tabela: #, Fabricante (pill teal/neutral), ONUs em uso, Reparos no período, Taxa de defeito (barra horizontal colorida + valor mono)
  - Cores da barra: teal <2%, âmbar 2-5%, vermelho ≥5%
- `api.js`: nova função `aiDashManufacturerQuality(days=90)`

### Resultado real
- 1.729 ONUs em 10 fabricantes ranqueadas
- 20 chamados de reparo no período não foram cruzados (nomes Atlaz ≠ nomes SmartOLT) — UI exibe aviso para o gestor

---

## Feb 10, 2026 — Inferência por similaridade (batch LLM com contexto)
- Função `identify_by_similarity_batch` em manufacturers.py
- 89% identificados (1.557/1.749) após batch LLM com catálogo de exemplos

## Feb 10, 2026 — Botão "Forçar descoberta IA" + otimização por prefixo
## Feb 10, 2026 — Estoque > Clientes (SmartOLT) com identificação de fabricante via IA
## Feb 10, 2026 — Vehicle Checklist FULL: 5 silhuetas + photo upload + IA recurrent defects
## Feb 10, 2026 — Checklist Veicular CONTRAN + Rename "Pertences" → "Checklist"
## Feb 10, 2026 — Mapa de Defeitos sincronizado com Lousa + UI Redesign Major
## Feb 9, 2026 — Lousa fixed slot heights + Wipe-all + Asset deactivation auto-popup
## Feb 8, 2026 — IA Center, EPIs, Tab Permissions, Hardware Detection
