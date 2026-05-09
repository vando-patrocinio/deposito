# PRD — Sistema Mesclado: SmartProv + PontoIA (Lousa + Ponto)

**Última atualização**: 2026-05-09 (iteração 2)

## Histórico de iterações

### Iter 1 — Mesclagem inicial (Smart1 Lousa + Smart2 Ponto)
- Smart2 como base estrutural + Smart1 (lousa) plugado em cima
- 3 perfis: colaborador, gestor, administrador
- State machine: Entrada → Lousa liberada / Saída com bolha aberta → confirma → notifica gestor
- Backend: 26/27 pytest

### Iter 4 — Grade Fixa de Horários + Slots Configuráveis (2026-05-09)
- ✅ **Configurações da Grade**: novo card em Settings com 4 campos (hora_inicio, hora_fim, duracao_slot_min, max_bolhas_slot) + prévia visual em verde
- ✅ **Lousa em grade fixa**: cada coluna do técnico exibe TODOS os slots configurados (08:00, 09:00,..., 17:00) — sempre visíveis, mesmo vazios
- ✅ **Drag & drop entre slots**: arrastar bolha para slot vazio dentro da mesma coluna ou para outra coluna+slot
- ✅ **Capacidade configurável**: máximo N bolhas por slot (default 2). Slot cheio fica amarelo com badge "🔒 cheio" e bloqueia drop com erro 409
- ✅ **Bolhas sem horário**: ficam num bloco "📋 Sem horário" abaixo dos slots (sem limite)
- ✅ **Auto-categorização**: bolhas com `scheduled_time` caem no slot que contém o horário (ex: 09:30 → slot 09:00)
- 🔄 Endpoint `/api/lousa/tickets/{id}/transfer` aceita `new_grid_slot` (com ou sem trocar técnico)
- Backend: 14/14 pytest (100%)

### Iter 3 — SLA + Logs + Praça NOTA (2026-05-09)
- ✅ **Card Tempos de Referência** em Configurações: SLA por tipo (reparo=60min, instalacao=120min, retirada=30min) + slider warning% + checkbox piscar overdue + raio cerca NOTA
- ✅ **Bolhas agrupadas por horário** no painel admin: 🌅 Manhã / ☀️ Tarde / 🌙 Noite / 📋 Sem horário, com cabeçalhos por slot
- ✅ **SLA Timer com piscar vermelho**: bolha aberta exibe ⏱ Xmin/Ymin (Z%) com cor verde/amarelo/vermelho; ATRASADA pisca em vermelho via CSS `@keyframes pulseRed`
- ✅ **Logs de auditoria** completos: nova coleção `ticket_logs` com action+actor_role+actor_name+details+timestamp; painel inferior na lousa lista últimos 50 com filtros (Todos/Técnicos/Gestor/Admin)
- ✅ **Praça especial "NOTA"**: opção no select do cadastro → técnico bate ponto direto no endereço da bolha aberta/pendente (cerca virtual dinâmica gerada com raio configurável)
- 🐛 Bug crítico DynFence→dict em routes/clock.py corrigido pelo testing agent
- Backend: 20/20 pytest (100%)

### Iter 2 — Per-collaborator test mode + Kanban Grid + Transfer (2026-05-09)
- ✅ **Cadastro com flag `is_test_mode`**: admin marca colab como teste no formulário (checkbox roxo) → bypassa cerca virtual + validação selfie no clock-records (mesmo SEM token)
- ✅ **Bolhas escondidas até bater Entrada**: API retorna `needs_clock_in:true, tickets:[]` quando colaborador ainda não bateu ponto
- ✅ **Lousa em Grade Kanban**: nova rota `/api/lousa/grid` retorna columns por técnico — frontend redesenhado com coluna por técnico, avatar+badge online/offline, faixa de horários do dia, bolhas arrastáveis
- ✅ **Drag & drop entre técnicos**: endpoint `/api/lousa/tickets/{id}/transfer` permite gestor/admin mover bolhas entre colunas
- Backend: 16/16 pytest (100%)

## Endpoints novos (Iter 2)
- `GET /api/lousa/grid` — kanban (gestor/admin)
- `POST /api/lousa/tickets/{id}/transfer` — transferir nota (gestor/admin)
- `PUT /api/collaborators/{cid}` aceita `is_test_mode`

## Como usar Modo Teste
**Opção A — Por colaborador (NOVO)**: 
1. Login como admin → aba Cadastro → editar colaborador → marcar checkbox roxo "🧪 Modo Teste (Admin)"
2. Esse colaborador específico pode bater ponto **sem cerca e sem selfie** (qualquer um no celular pode bater por ele para testes)

**Opção B — Por sessão admin** (mantida da iter 1):
1. Login admin → "Modo celular" → banner roxo aparece
2. Admin pode bater ponto em qualquer local (token JWT detectado no Authorization header)

## Como usar Drag & Drop entre técnicos (NOVO)
1. Login como gestor/admin → aba Lousa
2. Grid mostra coluna por técnico
3. Arrastar bolha de uma coluna para outra → bolha transfere automaticamente
4. Se bolha estava "aberta", volta para "pendente" no destinatário (limpa estado anterior)

## Backlog priorizado
### P0 (próxima iteração)
- ✅ Drag & drop frontend (FEITO iter 2)
- ✅ Hide bubbles until clock-in (FEITO iter 2)
- ✅ Per-collaborator test mode (FEITO iter 2)
- Cerca virtual dinâmica usando endereço da próxima bolha
- Refatoração: split routes/lousa.py em sub-módulos (passou 700 linhas)

### P1
- Reordenação visual dentro da própria coluna (drag vertical)
- Aba "Auditoria" com mapa ao vivo evidente
- Push real-time para gestor quando técnico encerra Saída com pendência
- Drag & drop também no mobile (hoje só desktop)

### P2
- WhatsApp real (Twilio) — substituir mock
- Object storage para fotos
- PWA offline queue ativada
- Cerca virtual dinâmica auto-criada na bolha aberta

## Credenciais demo
| Email | Senha | Perfil |
|---|---|---|
| `admin@empresa.com` | `123456` | Administrador |
| `gestor@empresa.com` | `123456` | Gestor |
| `colaborador@empresa.com` | `123456` | Colaborador |

## Arquivos críticos
- `/app/backend/routes/lousa.py` — 8 endpoints + grid/transfer (~800 linhas)
- `/app/backend/routes/clock.py` — clock-records com state machine + dual test mode (collab + admin)
- `/app/frontend/src/LousaAdminPanel.js` — Kanban grid com drag-drop nativo HTML5
- `/app/frontend/src/LousaMobile.js` — vista mobile com `needs_clock_in` empty state
- `/app/frontend/src/CadastroPanel.js` — checkbox is_test_mode no form
