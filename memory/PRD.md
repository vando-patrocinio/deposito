# PRD — Sistema Mesclado: SmartProv + PontoIA (Lousa + Ponto)

**Última atualização**: 2026-05-09 (iteração 7)

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
