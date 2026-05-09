# PRD — Sistema Mesclado: SmartProv + PontoIA (Lousa + Ponto)

**Última atualização**: 2026-05-09 (iteração 22)

## Histórico de iterações

### Iter 22 — Sync Atlaz a cada 30s + Botão "Nova nota" abre painel Atlaz (2026-05-09) ✅
- ✅ **Sync Atlaz em segundos**: novo campo `sync_interval_seconds: Optional[int] = Field(default=30, ge=10, le=86400)` em `AtlazConfig` e `AtlazConfigUpdate`. Worker usa este valor com **precedência sobre `sync_interval_minutes`**. Tick interno do worker reduzido de 60s para **5s** para suportar intervalos sub-minuto sem hammering (cada empresa só dispara quando o intervalo configurado é alcançado).
- ✅ **Botão "+ Nova nota" na Lousa abre painel Atlaz externo**: quando `tenant_domain` está configurado, o botão (`data-testid="lousa-create-btn"`) dispara `window.open(${tenant_domain}/admin/tickets/list?new=1, '_blank', 'noopener,noreferrer')`. Texto fica "**Nova nota 🔗**". Quando vazio, fallback para o `CreateTicketModal` local — comportamento original preservado.
- ✅ **UI Settings/Atlaz**: input de intervalo agora em **segundos** (`atlaz-interval-seconds`, default 30, mín 10, máx 86400). Card "📋 Bolhas (Lousa)" mostra "A cada **Xs**".
- ✅ **`tenant_domain` da empresa demo** salvo como `https://ligofibra.atlaz.com.br`.
- Backend: 17/17 verde (validação 422 boundaries 10/86400, precedência worker, regressão completa). Frontend: 100% (campo segundos, window.open URL/target verificado via hook).

### Iter 21 — Fix bug HIGH validação Atlaz + auto-cura (2026-05-09) ✅
- ✅ **Field constraints em AtlazConfigUpdate**: `tech_sync_interval_minutes (ge=5,le=1440)`, `sync_interval_minutes (ge=1,le=1440)`, `lookback_days (ge=1,le=365)`, `timeout_seconds (ge=2,le=120)`. PUT com valores inválidos agora retorna 422 (era 200 + cascata 500).
- ✅ **Defesa em profundidade** em `put_atlaz_settings`: reconstrói `AtlazConfig(**{**current.dump(), **update})` em vez de `model_copy(update=...)` — força re-validação.
- ✅ **Auto-cura em `_get_config`**: configs corrompidas legadas no Mongo são sanitizadas (campos fora do range → defaults), persistidas e retornadas. Empresas com docs legados não dão mais 500.
- Backend: 23/23 testes verde (8 parametrizados rejeição + auto-heal + regressão).

### Iter 20 — Atlaz auto-sync de técnicos + SSE em tempo real (2026-05-09) ✅
- ✅ **Auto-sync de técnicos** (`_run_tech_sync_internal`): refatorado em função reutilizável; agora roda no worker periódico com intervalo separado (default 60min, configurável `tech_sync_interval_minutes`). Endpoint manual `POST /api/atlaz/sync-technicians` continua disponível.
- ✅ **4 novos campos em AtlazConfig**: `auto_sync_technicians (bool, default true)`, `tech_sync_interval_minutes (int, 5-1440, default 60)`, `last_auto_sync_bubbles_at (str|null)`, `last_auto_sync_technicians_at (str|null)`. Worker atualiza os timestamps a cada tick bem-sucedido.
- ✅ **SSE em tempo real**: `run_sync` (bolhas) e `_run_tech_sync_internal` (técnicos) publicam eventos `atlaz_bubbles_synced` / `atlaz_technicians_synced` via `routes.events.publish_event` quando criam itens novos. `_safe_publish` faz best-effort com try/except — falha de SSE não derruba sync.
- ✅ **Hook `useEventStream` estendido**: novo callback `onEvent(name, data)` para eventos genéricos (não só notifications). Listeners para `atlaz_bubbles_synced` e `atlaz_technicians_synced` registrados.
- ✅ **`LousaAdminPanel`**: banner verde `lousa-atlaz-flash` aparece quando o worker cria novas bolhas, e dispara `refresh()` automático.
- ✅ **`CadastroPanel`**: banner verde `atlaz-flash` aparece quando o worker cria novos técnicos, e dispara `reload()` da lista de colaboradores.
- ✅ **`AtlazIntegrationCard`**: nova seção `atlaz-auto-sync-section` com 2 cards (📋 Bolhas / 👷 Técnicos) mostrando timestamps de último sync automático + toggle e input de intervalo dos técnicos.
- Worker do backend: agora processa 2 jobs por empresa por tick — bolhas (a cada `sync_interval_minutes`) e técnicos (a cada `tech_sync_interval_minutes` se `auto_sync_technicians=true`).
- Frontend: 100% verde no smoke. Backend: 23/23 (após fix iter21).

### Iter 19 — Date Navigator inline + Mobile Reorder (2026-05-09) ✅
- ✅ **Date Navigator inline na Lousa Admin** (`LousaAdminPanel.js`): controles `◀ [data] ▶` + chip `Hoje` no header (data-testid `lousa-date-navigator`, `lousa-date-prev`, `lousa-date-next`, `lousa-date-input`, `lousa-date-today`). Quando data != hoje, banner amarelo `lousa-date-banner` mostra "🕐 Visualizando dia passado/futuro" + botão `lousa-back-today-btn`. Grid fica com opacity reduzida e drag&drop é desabilitado (read-only).
- ✅ **Mobile Reorder no app do colaborador** (`LousaMobile.js`): toggle `lousa-reorder-toggle` (visível quando >1 ticket e lousa liberada) ativa modo de reordenação. Cada bolha vira `bubble-reorder-{id}` com botões `bubble-up-{id}` e `bubble-down-{id}` + suporte a HTML5 drag (touchAction:none). Bolhas priority != "normal" mostram 🔒 e botões disabled. Barra `lousa-reorder-bar` com `lousa-reorder-cancel` e `lousa-reorder-save`. Save chama o novo endpoint público.
- ✅ **Novo endpoint `POST /api/lousa/public/reorder`** (sem JWT, valida ownership via `collaborator_id`): mesma lógica do `/lousa/reorder` autenticado — bolhas priority `horario`/`prioridade` ou em posição travada não podem ser movidas (HTTP 400). 404 se colaborador não existe. Idempotente.
- Backend: 13/13 (iter19) verde + regressão.
- Frontend: 100% Playwright (DateNavigator render, banner past/future, mobile reorder toggle/save com 3 tickets seed).

### Iter 18 — Atlaz V2 API Oficial (2026-05-09) ✅
- ✅ **Reescrita completa** de `routes/atlaz.py` com base na **doc oficial**: `https://app.atlaz.com.br/docs/api`
- ✅ Base URL: `https://app.atlaz.com.br/api/v2` (não é o domínio do tenant!)
- ✅ Auth: querystring `?token=` (descoberto após muitos testes)
- ✅ `GET /listachamados` com `data_criacao_inicio` obrigatório, filtro por `status=abertos`
- ✅ Dedupe via `atlaz_external_id`; mapeamento por **filial(cidade)** OU **técnico Atlaz** (prioridade técnico)
- ✅ Tipos REAIS detectados: "Retirada de equipamento", "Visita / Vistoria", "Instalação", "Suporte", "Cancelamento", "Outros"
- ⚠ **API V2 NÃO permite fechar/cancelar/reagendar** chamados — push de baixa removido. Gestor precisa dar baixa manualmente no painel web do Atlaz após terminar na Lousa.
- ✅ **Frontend reescrito**: card mais simples, com `BreakdownBox` mostrando contagem por cidade/tipo/técnico no test-connection; `TecnicoMapper` (preenche depois do test) e `FilialMapper`.
- ✅ **TESTADO COM CHAVE REAL DA LIGO FIBRA**: 64 chamados detectados em 5 cidades, 5 técnicos atribuídos, 43 importados como bolhas com sucesso, dedupe verificado (segunda call = 43 skipped).
- ✅ Sync agendado a cada 15min via worker periódico (já existente).
- ⚠ Push hook em `admin-close` mantido como **stub no-op** que retorna `{ok: false, reason: "atlaz_api_v2_not_supported"}`.

### Iter 17 — 4 features P1 do backlog (2026-05-09)
- ✅ **#1 Mapeamento Filial→Colaborador via UI amigável**: substituído textarea JSON cru por componente `FilialCollabMapper` em `AtlazIntegrationCard.js` — cada filial digitada gera linha com dropdown de colaboradores (carregado de `api.listCollaborators`). Filiais "órfãs" (mapeadas mas sumidas da lista) aparecem destacadas em amarelo com botão remover.
- ✅ **#2 Atalho "Selecionar atrasadas"**: novo botão `lousa-select-overdue-btn` visível só em modo seleção, mostra contagem `⚠ Atrasadas (N)`, click marca todos os tickets `sla.status='overdue'` selecionáveis. Disabled quando N=0.
- ✅ **#3 Aba "Avaliação IA 🤖" dedicada**: novo `AiRankingPanel.js` + endpoint `GET /api/lousa/ai-rankings?days=N`. Ranking de técnicos por score IA médio com KPIs (total avaliados / score médio geral / técnicos / período), filtros 7d/30d/90d, distribuição por verdict (Excelente/Bom/Atenção/Crítico) com porcentagem, melhor/pior ticket por técnico, medalhas 🥇🥈🥉.
- ✅ **#4 Cache 5min em /ai-evaluate**: `_AI_EVAL_CACHE` in-memory com TTL=300s por ticket_id. Resposta cacheada inclui `cached: true`. **Refinamento**: fallback heurístico NÃO é cacheado (deixa LLM voltar a próxima call em vez de "grudar" estado degradado).
- ⏳ **#5 P2 Refactor lousa.py >2200 linhas** — adiado para iteração dedicada (alto risco de regressão; merece testes + planning separado).
- Backend: 12/12 (iter17) verde + regressão.
- Frontend: 100% smoke + Playwright (29 ranking rows, KPIs, mapper substituiu textarea, botão Atrasadas hidden→visible no toggle).

### Iter 16 — Integração Atlaz configurável (pull periódico + push de baixa) (2026-05-09)
- ✅ **Novo módulo** `/app/backend/routes/atlaz.py` (~430 linhas) com modelo `AtlazConfig` totalmente configurável: base_url, api_key + header customizável, paths de list/close/cancel/reschedule, mapeamento de filiais→colaborador, mapeamento de tipos (REPARO→reparo etc.), mapeamento de campos (cliente_nome→client_name etc.), intervalo de sync, timeouts.
- ✅ **Endpoints** (todos role gestor):
  - `GET/PUT /api/atlaz/settings` — config com chave **mascarada** (`aaaa…bbbb`); api_key vazio NÃO sobrescreve.
  - `POST /api/atlaz/test-connection` — ping HTTP que detecta automaticamente shape do JSON (`items[]` / `data[]` / `results[]` / `ordens[]` / lista pura) e retorna `sample_count` + `sample_keys` para o gestor calibrar o field_map.
  - `POST /api/atlaz/sync-now` — pull manual; itera filiais; cria bolhas com `atlaz_external_id` (deduplicação).
  - `GET /api/atlaz/sync-logs` — auditoria de todos os eventos `pull` / `test` / `push_*`.
- ✅ **Worker periódico** (`_worker_loop`) — scan a cada 60s das empresas com `enabled=true`, respeita `sync_interval_minutes` por empresa, nunca derruba o backend se Atlaz cair.
- ✅ **Push de baixa**: hook em `admin-close` (single) e `bulk-action` (lote) — quando ticket tem `atlaz_external_id`, dispara `push_close` em `try/except` para o endpoint correspondente (concluir/cancelar/reagendar). Salva `atlaz_pushed` + `atlaz_pushed_at` no ticket.
- ✅ **Frontend**: `AtlazIntegrationCard.js` em SettingsPanel — toggle ON/OFF, todos os campos editáveis, mapeamentos avançados em JSON (com try/parse), botões Testar/Sincronizar/Ver logs com resultados visuais detalhados (HTTP code, sample_keys, body preview, lista de erros).
- ✅ **Visual**: bolha vinda do Atlaz ganha badge `🔗 Atlaz` no canto inferior esquerdo do BubbleCard.
- ✅ **Robustez**: defaults sensatos para o caso de a doc do Atlaz seguir convenção REST típica BR (paths `/v1/ordens-servico/{id}/concluir`, status `aberta`, fields em snake_case PT). User edita pelo card de Settings se a real for diferente.
- Backend: 16/16 (iter16) + regressão verde.
- Frontend: 21/21 atlaz-* testids OK; badge `🔗 Atlaz` renderiza.

### Iter 15 — Seleção múltipla + Ações coletivas (Reagendar / Cancelar / Encerrar / IA) (2026-05-09)
- ✅ **Modo seleção** na Lousa: novo botão `lousa-select-mode-toggle` no header alterna o modo. Quando ativo, cada bolha selecionável (status `pendente`/`aberta`/`aguardando_atendimento`) ganha um checkbox no canto sup-esquerdo. Bolhas finalizadas/encerradas/canceladas ficam não-selecionáveis (cursor not-allowed, opacity reduzida).
- ✅ **Barra flutuante inferior** (`bulk-actions-bar`) aparece com a contagem (`bulk-count`) + 4 botões de ação: `bulk-action-reagendar`, `bulk-action-encerrar`, `bulk-action-cancelar`, `bulk-action-ia` + `bulk-clear`.
- ✅ **Popup unificado por ação** (`bulk-action-modal`):
  - Reagendar: data/hora/motivo (`bulk-resched-date`, `bulk-resched-time`, `bulk-action-notes` obrigatório)
  - Cancelar: motivo obrigatório
  - Encerrar: notas opcionais
  - Após confirmar: `bulk-result-modal` mostra processed/failed
- ✅ **Bulk IA** (`bulk-ai-modal`): roda apenas heurística (sem LLM em lote) — score 0-10, verdict, signals visualizados em cards (`bulk-ai-item-{id}`).
- ✅ **Backend**: 2 novos endpoints em `lousa.py`:
  - `POST /api/lousa/tickets/bulk-action` — payload `{ticket_ids[], action, notes?, new_date?, new_time?}`. Pydantic min_length=1, max_length=200. Skipa already-closed como `errors[]`. Reusa `_log_ticket_action` (com `[bulk]`) + `_create_notification` para colaboradores. Role gestor.
  - `POST /api/lousa/tickets/bulk-ai-evaluate` — payload `{ticket_ids[]}` (max 50). Retorna `{count, items[]}` com score heurístico + signals.
- ✅ Em modo seleção: drag&drop desabilitado, duplo-clique para editar desabilitado, popups inline de ações desabilitados.
- Backend: 13/13 (iter15) + 34/34 regressão (iter11/12/14) verde.
- Frontend smoke: 100% — todos os 4 modais abrem com testids corretos, IA renderiza items reais.

### Iter 14 — Lousa Histórica (Kanban) + Mirror Mobile + serverTime singleton (2026-05-09)
- ✅ **Histórico vira a Lousa em si**: `GET /api/lousa/grid?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` retorna kanban filtrado por período, default abre no DIA atual. Tickets em modo histórico ficam `locked=true historical=true` (read-only). LousaHistoryModal reescrito para mostrar layout kanban (não mais tabela).
- ✅ **5 chips de granularidade**: Dia / Semana / Mês / Ano / Período + busca textual + KPIs clicáveis
- ✅ **Mirror Mobile**: `/api/lousa/by-collaborator/{cid}` agora retorna `tickets: [só ativas]` e `recent_resolved: [resolvidas 24h]` separados → app do colaborador espelha exatamente a lousa do gestor (sem bolha no gestor → sem bolha no mobile)
- ✅ **serverTime.js singleton**: novo módulo com `serverNow()`, `serverDate()`, `useServerNow()` hook. ServerClock refatorado. `client_time_ms` em POST /clock-records agora usa `serverNow()` (anti-tampering — usuário não consegue mais bypassar drift validation alterando relógio do dispositivo)
- ✅ Boot: `App.js` chama `startServerTime()` uma vez no mount; sync periódico a cada 60s
- Backend: 12/12 (iter14) + 84/84 regressão = **96/96 verde**
- Frontend deep test: 100%

### Iter 13 — Cards Clicáveis + Busca Textual no Histórico (2026-05-09)
- ✅ **Cards de KPI no Histórico viraram filtros**: clicar em "Encerradas 8" filtra a tabela para só as 8; clicar de novo limpa; clicar em "Total" sempre limpa qualquer filtro de status. Card ativo destacado com gradient escuro + sombra colorida
- ✅ **Busca textual** com `🔍 Buscar cliente, endereço, bairro, notas, técnico` — filtro client-side instantâneo + botão X para limpar
- ✅ **Filtros 100% client-side** (status + busca) — cards mantêm contagens reais mesmo com filtro ativo (resolve o pain point de UX onde clicar Cancelada zerava os outros cards)
- ✅ Footer dinâmico: "X de Y nota(s)" quando há filtro/busca, ou "X nota(s)" quando sem filtros
- ✅ Export CSV agora exporta **filteredItems** (respeitando filtros ativos)
- Backend: 14/14 regressão iter12 verde
- Frontend deep test: 100% (8/8 cenários)

### Iter 12 — Histórico da Lousa por Dia/Mês/Ano/Período (2026-05-09)
- ✅ **Endpoint** `GET /api/lousa/history?granularity={day|month|year|range}` com filtros opcionais por status/type/collaborator_id, retorna items[] e summary agregado
- ✅ **Modal** "📚 Histórico da Lousa" acessível via botão `lousa-history-btn` no header da Lousa
- ✅ Filtros visuais: 4 chips (Dia/Mês/Ano/Período) + dropdowns Status + Tipo
- ✅ KPIs: Total, Finalizadas, Encerradas, Reagendadas, Canceladas, Tempo médio, Top técnico
- ✅ Tabela com Cliente/Tipo/Técnico/Status/Duração/Datas/Notas
- ✅ Exportar CSV (BOM UTF-8 + escape de newlines em campos)
- ✅ Intervalos padronizados em **semi-aberto** (consistência day/month/year/range)
- Backend: 14/14 (iter12) + 94/94 regressão = **108/108 verde**
- Frontend deep test: 100%

### Iter 11 — Cancelamento mobile + Modal Reschedule + KPIs Gestão + Insights IA (2026-05-09)
- ✅ **Notas canceladas/reagendadas pela gestão SAEM da Lousa do app do colaborador**: `_lousa_for_collaborator` agora filtra apenas `TECH_RESOLVED` (finalizada/encerrada pelo técnico), excluindo `cancelada`/`reagendada` que são ações de gestão
- ✅ **Modal Reschedule** (`/app/frontend/src/lousa/RescheduleModal.js`): substitui `window.prompt` por popup com data, horário e motivo. Submete via `admin-close action=reagendar` com `new_date`+`new_time`+`notes`
- ✅ **Notification automática** ao colaborador: ao cancelar/reagendar via gestão, cria entrada em `db.notifications` com `type=ticket_cancelar_by_admin`/`ticket_reagendar_by_admin`
- ✅ **KPIs da Gestão** (`GET /api/lousa/management-kpis?days=N`): cards Trabalhadas (admin-open) / Encerradas / Reagendadas / Canceladas / Editadas / Transferidas + ranking de gestores + top motivos cancel/reschedule + tempo médio até decisão
- ✅ **Insights IA Gestão** (`POST /api/lousa/management-insights?days=N`): IA analisa decisões de gestão e retorna `analysis_summary` + `red_flags` + `recommendations` + `priority_action`. Botão "🤖 Insights IA" no Painel
- ✅ **admin-open agora loga `aberta_admin`** (não mais `aberta`) — diferencia de execução pelo técnico nos relatórios
- Backend: 8/8 (iter11) + 86/86 regressão = **94/94 verde**
- Frontend deep test: 100%

### Iter 10 — Hover/Edit + Online Indicator + Lock Execution + Server Clock + OpenRouter (2026-05-09)
- ✅ **Hover na bolha**: mouse-over abre ações (não precisa clicar); duplo-clique abre EDIT (antes era admin-open)
- ✅ **Avatar com indicador online/offline**: borda verde + bolinha verde se dispositivo bateu ponto nos últimos 5min (configurável `online_threshold_minutes`); borda amarela + bolinha amarela caso contrário
- ✅ **Bolha em execução**: `in_execution=True` quando `status='aberta'`. Frontend exibe badge "▶ Em execução" pulsante + draggable=false. Backend retorna 409 em `/transfer` e `DELETE /tickets/{id}`
- ✅ **Relógio do servidor**: novo `ServerClock.js` no canto sup-direito (header App + header Mobile). Sincroniza com `/api/server-time` a cada 60s usando `performance.now()` (monotônico) — imune a alterações no relógio do dispositivo
- ✅ **OpenRouter integration**: card em Configurações com toggle de ativação, campo API key (mascarada `sk-or-v1***XXXX`), modelo padrão `deepseek/deepseek-v4-flash`. Backend usa `openai` SDK com `base_url=https://openrouter.ai/api/v1` quando ativo+chave; fallback automático para Emergent LLM. Adapter `_OpenRouterChat` em core.py com mesma interface do `LlmChat`.
- Backend: 9/9 (iter10) + 77/77 regressão = **86/86 verde**

### Iter 9 — Briefing IA + Mobile Redesign + Avatar Auto
- ✅ **Briefing diário**: `GET /api/lousa/briefing` retorna `summary_data` (data, totais, top técnico, pior score IA, top 3 serviços por duração) + `narrative` LLM opcional. Botão `generate-briefing-btn` no Painel abre `briefing-modal` com texto IA em PT-BR (4 parágrafos profissionais)
- ✅ **Mobile colaborador redesenhado** (best practices 2026):
  - Avatar 64px com gradient azul à esquerda + nome + cargo
  - Kebab menu (⋮) à direita com Histórico + Voltar ao painel + Logout Google (quando aplicável)
  - Botão **único primário** "Bater [Próximo]" 72px gradient verde
  - Botão **secundário** Lousa de Serviços
  - Botão central "Histórico" REMOVIDO (movido para o kebab)
  - Avatar atualiza automaticamente após primeira selfie válida (refresh de `listCollaborators` no `onSelfieCaptured`)
- Backend: 4/4 (iter9) + 57/57 regressão = **61/61 verde**
- Frontend deep test: 100%

### Iter 8 — Duração + Gap + IA + Painel Stats + Mobile (2026-05-09)
- Rename "bolha"→"serviço", duplo-clique abre, duração no canto inf-direito, gap entre serviços, badge IA score 0-10, modal IA profunda com LLM, ServiceStatsSection no Painel
- ✅ **Rename** "bolha"→"serviço" em headers, badges, tooltips e alerta
- ✅ **Duplo-clique** em serviço pendente abre via admin-open
- ✅ **Duração** (HH:MM) no canto inf-direito do BubbleCard quando ticket aberto/fechado
- ✅ **Gap entre serviços** texto centralizado entre BubbleCards no mesmo slot + bloco "📒 Encerrados (24h)" por técnico (gap entre cada serviço fechado)
- ✅ **Mobile colaborador**: card "🧾 Último serviço encerrado" com duração + tempo desde encerramento (gap até bater Saída)
- ✅ **Painel — Estatísticas de serviços** (`/api/lousa/stats?days=N`): KPIs (total/executados/finalizados/cancelados/tempo médio), ranking de tipos com barras coloridas, gráfico recharts de volume diário (criados vs finalizados), seletor 7d/30d/90d
- ✅ **IA Heurística (sempre)**: score 0-10 por ticket no `/api/lousa/grid` com sinais cumulativos:
  - Distância da posição atual ao endereço (haversine)
  - Tempo decorrido vs SLA (overshoot %)
  - Histórico de duração média do técnico para o tipo (últimos 30d)
  - Gap longo desde último serviço encerrado (>90min)
  - Geo-fence violations recentes (24h)
- ✅ **IA Profunda (sob demanda)**: botão 🤖 IA chama `POST /api/lousa/tickets/{id}/ai-evaluate` (Emergent LLM via emergentintegrations) e retorna verdict + summary + recomendações + sinais. Modal `ai-detail-modal` exibe tudo.
- Backend: 10/10 pytest novos (iter8) + 11/11 iter5 regression verde

### Iter 7 — Polish + Alertas Sonoros + Refactor + Bug Fixes
- 🔔 Alertas sonoros SLA (slaAlerts.js) + toggle ON/OFF persistido em localStorage
- 🧹 Refactor: EditTicketModal e CreateTicketModal extraídos
- 🐛 4 bugs do code review iter5/6 corrigidos (PUT settings 422, PATCH grid_slot, drift skip admin-only, defaults SLA)

### Iter 6 — Code Review + Bug Fix
- Identificou e corrigiu PUT /api/settings 500→422

### Iter 5 — Time-Sync + Admin Open/Edit + Novos Tipos
- /api/server-time + drift validation 412 + admin-open/edit + 6 tipos de serviço

### Iter 4 — Grade Fixa de Horários + Slots Configuráveis
- Lousa em grade configurável + drag&drop entre slots

### Iter 3 — SLA + Logs + Praça NOTA
- SLA piscando + logs auditoria + cerca dinâmica NOTA

### Iter 2 — Per-collaborator test mode + Kanban Grid + Transfer
- is_test_mode + kanban + transfer drag&drop

### Iter 1 — Mesclagem inicial Smart1+Smart2
- 3 perfis + state machine clock vs lousa

## Endpoints chave
- `GET /api/lousa/grid` — kanban com SLA + duration_minutes + gap_minutes_to_prev + ai_score (heurística) + recent_resolved
- `GET /api/lousa/by-collaborator/{cid}` — para mobile, com last_closed_at + minutes_since_last_close
- `GET /api/lousa/stats?days=N` — KPIs e ranking
- `POST /api/lousa/tickets/{id}/ai-evaluate` — análise LLM (Emergent)
- `GET /api/server-time` — sync horário
- `POST /api/lousa/tickets/{id}/admin-open` + `PATCH` + `transfer` + `admin-close`

## Backlog priorizado

### P0 — Concluído ✅
- IA score + duração + gap + Painel stats (FEITO iter 8)
- Mobile resumo último serviço (FEITO iter 8)

### P1 — Próximas
- Aba "Avaliação IA" dedicada (lista por técnico + média)
- Card de score por técnico no Painel com alertas
- Cache curto para /ai-evaluate (5min) por ticket_id
- Reordenação visual dentro da própria coluna (drag vertical)
- Push real-time gestor

### P2 — Backlog
- Refatorar `routes/lousa.py` (~1418 linhas) em sub-módulos: lousa_grid, lousa_stats, lousa_ai, lousa_admin
- Sentinel para limpar `scheduled_time` via PATCH
- Rate limit em endpoints públicos (slowapi)
- Helper `_is_admin_request` em clock.py
- WhatsApp real (Twilio)
- Object storage para fotos
- PWA offline queue ativada

## Credenciais demo
| Email | Senha | Perfil |
|---|---|---|
| `admin@empresa.com` | `123456` | Administrador |
| `gestor@empresa.com` | `123456` | Gestor |
| `colaborador@empresa.com` | `123456` | Colaborador |

## Arquivos críticos
- `/app/backend/routes/lousa.py` — main lousa (~1422 linhas)
- `/app/backend/routes/lousa_score.py` — heurística + duração
- `/app/backend/routes/clock.py` — clock-records + state machine
- `/app/backend/routes/admin.py` — Settings com Field constraint
- `/app/backend/core.py` — Settings model + LLM helpers
- `/app/frontend/src/LousaAdminPanel.js` — Kanban + IA + duração + gap
- `/app/frontend/src/DashboardPanel.js` — Painel + ServiceStatsSection
- `/app/frontend/src/CollaboratorApp.js` — Mobile + last-service-summary
- `/app/frontend/src/lousa/EditTicketModal.js` + `CreateTicketModal.js`
- `/app/frontend/src/slaAlerts.js` — Web Audio API + Notification API
- `/app/frontend/src/OfflineTimeBanner.js` — banner offline/drift

## Histórico de iterações

### Iter 7 — Polish + Alertas Sonoros + Refactor (2026-05-09)
- ✅ **Alertas sonoros SLA**: novo `slaAlerts.js` com Web Audio API (beep duplo) + Browser Notification quando bolhas overdue aumentam
- ✅ **Toggle 🔔 Alertas ON/OFF** no header da Lousa (`data-testid="lousa-sla-alerts-toggle"`), persiste em `localStorage.sla_alerts_enabled`
- ✅ **Refactor**: `EditTicketModal` e `CreateTicketModal` extraídos para `/app/frontend/src/lousa/` (LousaAdminPanel reduzido de 737 → 596 linhas)
- ✅ **Bug fix `_sla_minutes_for_type`**: defaults completos para os 6 tipos (45/90/60 para prioridade/preventiva/venda)
- ✅ **Bug fix PATCH lousa**: ao mudar `scheduled_time`, agora limpa `grid_slot` para recompute automático
- ✅ **Bug fix drift**: pula validação apenas para admin token JWT, NÃO mais para `is_test_mode` no colaborador (era inconsistente)
- ✅ **Bug fix 422**: `SettingsUpdate.time_sync_max_drift_seconds` com `Field(ge=1, le=86400)` retorna 422 nativo (era 500)
- Backend: 11/11 (session bugfixes) + 22/22 (iter5 base) + 30/30 (iter2+4) — total 63/63 ✅
- Frontend deep test Playwright: 100% (login, tab-lousa, alerts toggle, modais, criar preventiva, edit, offline)

### Iter 6 — Code Review + Bug Fix
- Testing agent identificou 3 bugs no PUT /api/settings (500 ao invés de 422). Corrigido em iter 7.

### Iter 5 — Time-Sync + Admin Open/Edit + Novos Tipos (2026-05-09)
- ✅ **Sincronização horário Brasil**: `GET /api/server-time` público + validação drift em `POST /api/clock-records` (412 quando dessincronizado)
- ✅ **Banner offline + drift**: `OfflineTimeBanner.js` sticky no topo, lousa fica trancada (overlay 50%) quando offline ou drift bloqueado
- ✅ **Admin/gestor abre bolha**: `POST /api/lousa/tickets/{id}/admin-open` (status pendente → aberta + log "aberta")
- ✅ **Admin/gestor edita bolha**: `PATCH /api/lousa/tickets/{id}` aceita client_name/address/neighborhood/phone/relato/type/priority/scheduled_time + cria log "editada"
- ✅ **Novos tipos**: prioridade (45min), preventiva (90min), venda (60min) — adicionados a Pydantic Literal e Settings
- Backend: 22/22 pytest (iter5)

### Iter 4 — Grade Fixa de Horários + Slots Configuráveis
- Lousa em grade fixa configurável + drag&drop entre slots + capacidade configurável

### Iter 3 — SLA + Logs + Praça NOTA
- SLA com piscar amarelo/vermelho + logs auditoria + cerca dinâmica NOTA

### Iter 2 — Per-collaborator test mode + Kanban Grid + Transfer
- is_test_mode por colaborador + grid kanban + transfer drag&drop

### Iter 1 — Mesclagem inicial Smart1+Smart2
- 3 perfis + state machine clock vs lousa

## Endpoints chave
- `GET /api/server-time` — horário servidor (público)
- `GET /api/lousa/grid` — kanban com SLA por tipo
- `POST /api/lousa/tickets` — criar bolha (6 tipos)
- `PATCH /api/lousa/tickets/{id}` — editar (gestor/admin)
- `POST /api/lousa/tickets/{id}/admin-open` — abrir em nome do colab
- `POST /api/lousa/tickets/{id}/admin-close` — encerrar/reagendar/cancelar
- `POST /api/lousa/tickets/{id}/transfer` — transferir entre técnicos/slots
- `POST /api/clock-records` — bate ponto com drift validation (412 se dessync)
- `PUT /api/settings` — Field(ge=1, le=86400) em time_sync_max_drift_seconds

## Backlog priorizado

### P0 — Concluído ✅
- Alertas sonoros SLA (FEITO iter 7)
- Refactor modais (FEITO iter 7)
- Bugs review iter5/6 (FEITO iter 7)

### P1 — Próximas
- Reordenação visual dentro da própria coluna (drag vertical)
- Aba "Auditoria" com mapa ao vivo evidente
- Push real-time para gestor quando técnico encerra com pendência
- Drag & drop também no mobile

### P2 — Backlog
- Recurso "limpar" `scheduled_time` via PATCH com sentinel/UNSET (hoje filter `is not None` bloqueia)
- Refatorar `routes/lousa.py` (~1148 linhas) em sub-módulos: `server_time.py`, `admin_actions.py`, `public_mobile.py`, `grid.py`
- Extrair helper `_is_admin_request(request)` em clock.py (drift skip duplicado)
- Rate limit em `/api/server-time` (slowapi)
- WhatsApp real (Twilio) — substituir mock
- Object storage para fotos
- PWA offline queue ativada

## Credenciais demo
| Email | Senha | Perfil |
|---|---|---|
| `admin@empresa.com` | `123456` | Administrador |
| `gestor@empresa.com` | `123456` | Gestor |
| `colaborador@empresa.com` | `123456` | Colaborador |

## Arquivos críticos
- `/app/backend/routes/lousa.py` — 8+ endpoints + grid/transfer/admin-open/edit (~1148 linhas)
- `/app/backend/routes/clock.py` — clock-records com state machine + drift validation + dual test mode
- `/app/backend/routes/admin.py` — Settings com Field constraint
- `/app/backend/core.py` — Settings model com SLAs + time sync config
- `/app/frontend/src/LousaAdminPanel.js` — Kanban grid + alerts toggle (~596 linhas)
- `/app/frontend/src/lousa/EditTicketModal.js` + `CreateTicketModal.js` — modais extraídos
- `/app/frontend/src/slaAlerts.js` — Web Audio API + Notification API
- `/app/frontend/src/OfflineTimeBanner.js` — banner offline/drift sticky
