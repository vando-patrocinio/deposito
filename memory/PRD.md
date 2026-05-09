# PRD — Sistema Mesclado: SmartProv + PontoIA (Lousa + Ponto)

**Data**: 2026-05-09
**Resultado**: Mesclagem dos projetos `smart1` (SmartProv — lousa de notas de serviço) e `smart2` (PontoIA — ponto eletrônico com selfie+IA).

## Problema original
Usuário tinha 2 projetos separados:
- **smart1**: Lousa de bolhas com regras de prioridade (técnico abre 1 nota por vez, finaliza com fotos/dados técnicos, gestor encerra administrativamente)
- **smart2**: Ponto eletrônico SaaS com selfie+IA, cerca virtual, mapa ao vivo, dwell detection 30min, dashboard KPIs

Quis unificar com lógica de máquina de estados ligando os dois sistemas:
- Colaborador só abre bolha após bater **Entrada**
- Não pode bater **Início intervalo** ou **Saída** com bolha aberta
- Lousa fica visualmente travada durante intervalo
- Saída com bolha aberta → confirma → encerra notas → notifica gestor

## Arquitetura
- **Base estrutural**: Smart2 (FastAPI modular: `server.py + routes/`)
- **Módulo novo**: `routes/lousa.py` (8 endpoints: read, public, gestor, notifications)
- **Frontend novos**: `LousaMobile.js`, `LousaAdminPanel.js`, `NotificationsBell.js`
- **3 perfis**: `colaborador`, `gestor`, `administrador` (auditor mantido por compat)

## Funcionalidades implementadas (2026-05-09)

### Backend
- [x] `routes/lousa.py` com 8+ endpoints (read me/by-collab/all, create/delete, public open/finalize/exit-resolve, admin-close, notifications)
- [x] State machine integrado em `routes/clock.py`: bloqueio de Início intervalo e Saída quando há bolha aberta (412/409)
- [x] Force-close automático de bolhas ao confirmar Saída (`force_close_open_tickets=true`) + criação de notificação crítica para gestor
- [x] Auth: roles colaborador/gestor/administrador/auditor; `administrador` é super-role como auditor
- [x] Seed automático: 5 bolhas + 3 usuários (admin/gestor/colaborador@empresa.com) + colaborador `col-demo-001`
- [x] Vínculo `user.collaborator_id` (colaborador@empresa.com → col-demo-001)
- [x] Indexes: tickets, notifications

### Frontend
- [x] **Mobile do colaborador (PWA)**: botão "Lousa de Serviços" na home + tela completa da lousa com banner de status do ponto + bolhas com cadeado quando travadas
- [x] **Diálogo de Saída com bolhas em aberto**: modal de confirmação que aciona `force_close_open_tickets`
- [x] **Painel Lousa do Gestor**: cards das bolhas filtráveis (todas/ativas/em campo/aguarda gestor/resolvidas) + criação de nota + ações encerrar/reagendar/cancelar
- [x] **Sino de notificações**: dropdown com badge de não lidas + auto-refresh 30s + marcar como lida
- [x] **Aba "Lousa 📋"** no menu do gestor + roles para administrador

### Preservadas do Smart2 (cerca + monitoramento)
- [x] Cerca virtual obrigatória em Entrada/Saída
- [x] Validação de selfie via Emergent LLM (gpt-4o vision) — `validate_face_visible` + `compare_faces`
- [x] Mapa ao vivo (LiveMap.js) e tracking de localização ativa (`/api/locations/live`)
- [x] Dwell detection ≥30min (`/api/locations/dwell-analysis`) + push automático (job a cada 2min)
- [x] Dashboard KPIs (HE, custo, tendência, heatmap)
- [x] Espelho mensal PDF (Resend opcional)
- [x] Multi-tenant scoping via `company_id` (todas as queries de lousa/notifications respeitam tenant)

## Personas e papéis
- **Colaborador (técnico)**: PWA mobile (sem login), bate ponto + opera lousa
- **Gestor**: painel desktop, gerencia bolhas + colaboradores + recebe notificações
- **Administrador**: super-role com acesso total (cadastro de usuários, configurações, plataforma)
- **Auditor**: mantido para compat com smart2 (mesmas permissões do admin)

## Credenciais demo
| Email | Senha | Perfil |
|---|---|---|
| `admin@empresa.com` | `123456` | Administrador |
| `gestor@empresa.com` | `123456` | Gestor |
| `colaborador@empresa.com` | `123456` | Colaborador |

## Endpoints novos (Lousa)
- `GET /api/lousa/by-collaborator/{cid}` — público (PWA)
- `GET /api/lousa/me` — colaborador autenticado
- `GET /api/lousa/all` — gestor
- `GET /api/lousa/tickets/{id}`
- `POST /api/lousa/tickets` — criar (gestor)
- `DELETE /api/lousa/tickets/{id}` — gestor
- `POST /api/lousa/tickets/{id}/admin-close` — gestor (encerrar/reagendar/cancelar)
- `POST /api/lousa/public/tickets/{id}/open` — público (PWA)
- `POST /api/lousa/public/tickets/{id}/finalize` — público (PWA)
- `POST /api/lousa/public/exit-resolve` — público (PWA, ao confirmar Saída)
- `GET/POST /api/notifications` — gestor

## Backlog priorizado
### P0
- Validar fluxo end-to-end com selfie real (mobile real / câmera)
- Cerca virtual dinâmica usando endereço da bolha aberta (estrutura geocode_address já está em create_ticket — falta criar geofence runtime)
- Drag & drop de bolhas no frontend mobile (backend já tem `/lousa/reorder`)

### P1
- Aba "Auditoria/Mapa" rotulada como pediu (atualmente "Auditoria" usa o ManagerPanel)
- Notificações em tempo real via WebSocket / Web Push (estrutura push_service.py já existe)
- Vínculo automático: ao bater Entrada, criar geofence dinâmica no endereço da próxima bolha

### P2
- WhatsApp real (Twilio) — substituir send_whatsapp_mock
- Object storage para fotos da finalização (hoje base64 inflando documentos)
- PWA offline queue (já existe service-worker.js do smart2)

## Testes (2026-05-09)
- Backend: 26/27 pytest passando (96%) — `test_lousa_merge.py`
- Frontend: validado visualmente (login + lousa admin + lousa mobile + state machine 🔒)
