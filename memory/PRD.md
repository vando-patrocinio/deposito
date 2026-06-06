# SmartProv — PRD (Enterprise 2026 ISP Billing & Network Suite)

> **Idioma do usuário: Português Brasileiro.** Toda comunicação com o usuário
> deve ser em PT-BR.

## Visão
Substituir o sistema "Atlaz" por uma suíte ISP enterprise completa, "SmartProv",
com módulos nativos de Billing, NFCom, PPPoE/RADIUS, SmartOLT TR-069,
Fleet Tracking, Referral ("Indique e Ganhe"), WiFi Hotspot multi-tenant,
SecurityHome (Verisure-style), e marketplace de Parcerias.

## Stack
- **Backend**: FastAPI + MongoDB (PyMongo + Motor) + emergentintegrations (LLMs)
- **Frontend**: React 18, Leaflet, react-leaflet, html5-qrcode
- **Infra**: Kubernetes (preview), Supervisor (backend/frontend), Yarn

## Personas
- **Admin/Gestor**: gerencia operações, faturamento, técnicos, lousa.
- **Técnico/Colaborador**: app mobile, ponto eletrônico, ordens de serviço.
- **Parceiro**: PWA com scanner QR para resgatar promoções.
- **Cliente final**: portal, fatura, indicações, hotspot WiFi.
- **SmartTV (Operação)**: nova persona — telão de monitoramento somente-leitura.

---

## Módulos / Status

### ✅ Concluído (Fork atual — Fev/2026)
- **Lousa Admin Kanban (>3000 linhas)** com auto-distribuição logística,
  avatares de IA (Isabella, Álvaro, Camila), SLA color-coded, Web Audio
  + SpeechSynthesis (TTS PT-BR).
- **LiveMap** com 12 mapas migrados pra CARTO Voyager PT-BR, label de
  acurácia GPS, polylines de rota, ocultação de "fora de cerca" para
  técnicos inativos.
- **QR Code Parceria V2**: Fernet AES + TTL 90s, scanner PWA com glow
  Apple-Pay, áudio e haptics.
- **WiFi Hotspot**: vitrine pública (`/wifi-vitrine`) + captive portal redesenhado.
- **Lousa TV (NOVO)**: link público somente-leitura `?portal=lousa-tv&t=<token>`,
  endpoints `GET /api/lousa/tv-link`, `POST /api/lousa/tv-link/rotate`,
  `GET /api/lousa/public/tv-grid/{token}` (sem auth). Header "📺 TV" no
  admin abre `LousaTvLinkModal` (copiar/abrir/rotacionar).
- **Tipo OS "Rompimento" + IA Claude 4.5 (NOVO)**: técnico descreve em texto
  livre, IA identifica insumos do catálogo e dá baixa no estoque da PRAÇA
  (`location='praca:<id>'`) com saldo negativo permitido. Gestor recebe
  notificação para regularizar.
  - Endpoints: `POST /api/lousa/public/rompimento/parse-preview`,
    `POST /api/lousa/public/tickets/{id}/rompimento-finalize`.
  - Frontend: `RompimentoCloseForm` substitui flow de 4 steps quando
    `ticket.type === "rompimento"`.

### 🟡 Em progresso / pendente
- **WhatsApp Canal 1 (502)**: sidecar Node.js porta 3002 falhando.
  Arquivo: `/app/backend/routes/whatsapp_channels.py`. Não foi atacado
  pelo agente anterior — recorrência.
- **SecurityHome MVP (Verisure-style)**: estrutura básica; falta parser
  Contact ID + integração Asaas para planos.
- **Fleet GPS Chip Payment**: bloqueado — usuário ainda não contratou
  operadora M2M.

### 🔵 Backlog / Upcoming (priorizado)
- **P0** — Módulo 4: NFCom (geração de NFCom para Telecom).
- **P1** — Cron job para pré-aviso de reajuste de mensalidade.
- **P1** — Painel Administrativo de Solicitações de Desbloqueio.
- **P1** — Habilitar dunning real (WhatsApp/SMS) em billing.
- **P1** — Configuração Gateway Asaas (aguardando API key).
- **P1** — Grafana + SNMP OLT monitoring (aguardando token).
- **P2** — Extração de contatos de grupos WhatsApp via Baileys.

### ♻️ Refactoring
- `/app/frontend/src/LousaAdminPanel.js` (3440 linhas) — quebrar em
  subcomponentes (Toolbar, KanbanGrid, AudioEngine, AIAvatars).

---

## API Endpoints chave
- `GET  /api/lousa/grid` — grade autenticada do Kanban
- `GET  /api/lousa/tv-link` — token TV (admin)
- `POST /api/lousa/tv-link/rotate` — rotacionar token
- `GET  /api/lousa/public/tv-grid/{tv_token}` — grade pública (sem auth)
- `POST /api/lousa/public/rompimento/parse-preview` — IA preview
- `POST /api/lousa/public/tickets/{id}/rompimento-finalize` — fecha OS rompimento
- `POST /api/lousa/tickets/auto-distribute` — auto-distribuição logística
- `POST /api/parcerias/scan` — decifra QR V2 + valida elegibilidade
- `GET  /api/wifi-hotspot/public/venues` — vitrine pública

## Schema MongoDB chave
- `tickets`: campo `type` agora inclui `"rompimento"`. Novo campo
  `rompimento_closure` armazena `report_text`, `ai_summary`, `ai_items`,
  `shortages`, `praca_id`.
- `stok_stock`: `location` pode ser `"praca:<id>"` (estoque por praça)
  ou `<technician_id>` ou `"empresa"`.
- `company_settings`: novo campo `lousa_tv_token` (UUID4 hex 32 chars).
- `notifications`: novo tipo `"rompimento_ia_closure"` direcionado ao gestor.
- `stok_history`: novo `type="rompimento"` para baixas via IA.

## 3rd Party Integrations
- **Emergent LLM Key** (Claude Sonnet 4.5 — `anthropic/claude-sonnet-4-5-20250929`)
  para o parser de rompimento. **REAL — não mockado.**
- **Nano Banana** (Gemini) para imagens.
- **Asaas** — MOCKED (aguardando key).
- **Baileys/WhatsApp** — sidecar port 3002 com erro 502 P0 pendente.

## Test credentials
Vide `/app/memory/test_credentials.md`.

## Notas de continuidade
- Usuário testa em **produção** (https://ligo.system) e às vezes acha que
  fixes não funcionam. Lembrar sempre: "Salvar no GitHub → Deploy" pra ver
  no prod. Preview sempre funcional primeiro.
- O suite de testes do Lousa TV + Rompimento ficou em
  `/app/backend/tests/test_lousa_tv_rompimento.py` (criado pelo testing agent).

## Identidade Visual (Manual 2026-06)
Toda nova tela e qualquer alteração deve seguir `/app/design_guidelines.md`.
**Regra global permanente.** Migração já aplicada em fases:
- FASE 1 (fundação): tokens institucionais (roxo `#4b1d7a` + laranja
  `#f28c28`), Inter unificado, Tailwind consumindo CSS variables.
- FASE 2 (Fidelidade): 145 emojis removidos, ícones Lucide nas sub-abas.
- FASE 3 (global): 1853 emojis removidos em 194 arquivos. Aspas tipográficas
  (`“”`) aplicadas em 82 trechos JSX. Exceção: LousaMobile mantida com
  ícones para legibilidade em campo.

## Features 2026-06 implementadas neste ciclo
- **OS Preventivas (Rede IA)** — card de configuração em Configurações.
  Cron 08:30 BRT enche grade ociosa do técnico (meta 12 OS/dia) com clientes
  de pior sinal SmartOLT. Endpoints: `/api/preventive-os/{settings,preview,run-now,history}`.
- **Regra global "uma porta = um cliente"** — helper
  `_smart_link_client_to_port` em `lousa.py` bloqueia HTTP 409 se porta
  ocupada por outro cliente; libera porta antiga em port_swap; mantém Base
  de Portas sincronizada.
- **OS de Reparo/Instalação exige CTO+Porta** — toggle `cto_port_required`
  default ON; backend bloqueia finalize sem cto_id/cto_port_number.
- **Auto-bump de limit no Fidelidade** — clicar barra do gráfico recarrega
  com `limit=10000` e auto-seleciona todos os clientes com telefone válido.
- **Filtro defensivo de data 1969** — `_years_since` rejeita anos < 1995
  (epoch corrompido). Tag `loyalty_hidden` exclui clientes corrompidos.
- **OsValidationTogglesCard** — UI de toggles para validações de OS
  (cto_photo_required, cto_port_required, ipv6_test_required, mac_validation_required).
