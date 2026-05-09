# PRD — Sistema Mesclado: SmartProv + PontoIA (Lousa + Ponto)

**Última atualização**: 2026-05-09 (iteração 11)

## Histórico de iterações

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
