# PontoIA — PRD (Product Requirements)

## Visão
Plataforma SaaS de operações para provedores de internet (ISP). Une três bases originais — `smartprov-tech` (Lousa de serviços), `selfie-attendance-7` (ponto facial) e `stok-main` (estoque de fibra) — em um único produto.

## Personas
- **Administrador** — acesso total. Gerencia configurações da empresa.
- **Gestor** — operação diária: lousa, despacho, conferência de ponto, estoque.
- **Auditor** — compliance e auditoria (incluindo ação destrutiva `wipe-all` de bolhas).
- **Colaborador (Técnico)** — fluxo mobile: bate ponto facial, atende serviços, scaneia QR.
- **Super Admin (Plataforma)** — multi-tenant: drill-down em empresas e gestão da plataforma.

## Pilares funcionais
1. **Lousa Kanban** — coluna por técnico, slot por hora; SLA por bolha; drag-and-drop entre técnicos; integração Atlaz V2 em tempo real (poll a cada 30s); ação `wipe-all` exclusiva do auditor.
2. **Ponto facial offline** — selfie + cerca virtual (geofence GPS); fila offline persistida; espelho mensal pronto para RH.
3. **Estoque (Fibra/Equipamentos)** — entrada em massa, dedução automática por chamado, ordens de serviço.
4. **Coletivo (EPIs / Pertences)** — CRUD de pertences por colaborador, valores padrão por categoria, romaneio PDF (mesmo vazio), modal de desativação com lista de pendências e impressão.
5. **IA Center / IA Preventiva / IA Ranking** — heatmaps OSM com bounds via IQR P15-P85, briefing diário, ranking por técnico, avaliação por chamado, fallback de fabricante de OLT (Huawei/ZTE/Nokia/etc).
6. **SmartOLT** — pills de sinal das ONUs, detecção de fabricante por SN, sincronização periódica.
7. **Atlaz V2** — sincronização de chamados; mapeamento técnico→colaborador; reassign-existing; logs auditados.
8. **Permissões dinâmicas** — admin configura quais abas cada role vê (`tab_permissions` em branding).
9. **Auditoria & Logs** — todas as ações destrutivas/sensíveis são logadas (lousa_logs, sync_logs).
10. **Plataforma multi-tenant** — super admin lista empresas, faz impersonation com banner de aviso.

## Arquitetura técnica
- **Backend**: FastAPI · MongoDB (Motor async) · APScheduler · workers async (atlaz, smartolt, ai_preventive, holidays).
- **Frontend**: React 19 · Tailwind · shadcn/ui · Lucide-react · Manrope/JetBrains Mono · React-Leaflet (OSM tiles).
- **LLM**: Emergent Universal Key via `emergentintegrations` (Gemini, Claude, OpenAI text + Nano Banana imagem).
- **PDF**: ReportLab (romaneio).
- **Eventos em tempo real**: SSE via `/api/events`.

## Design System (introduzido em fev/2026)
- **Estética**: Swiss & High-Contrast — clean, sóbrio, profissional B2B.
- **Cores**: Slate (`#0b1220`/`#475569`/`#94a3b8`) + acento Teal (`#0d9488`/`#0f766e`). NO purple/violet.
- **Tipografia**: Manrope (UI), JetBrains Mono (IDs/IPs/MACs/timestamps). NO Inter.
- **Layout**: Sidebar lateral fixa 248px (slate `#0b0f17`) · TopBar branca translúcida 56px com breadcrumb · main content max 1440px.
- **Navegação**: 5 grupos (Operação, Inteligência, Pessoas, Compliance, Sistema) + 12 abas categorizadas.
- **Ícones**: Lucide-react (sem emojis em labels/títulos/headings de painéis desktop).
- **Componentes**: classes utilitárias `.btn`, `.surface`, `.stat-card`, `.pill`, `.input`, `.app-sidebar`, `.app-topbar` em `index.css`.

## Status atual (Feb 2026)
✅ Funcional (Atlaz V2 sync ativo, 68 tickets/dia, sem erros)
✅ Redesign completo (sidebar+topbar+login split, paleta slate+teal, sem emojis em desktop)
✅ **Dark Mode** com toggle no TopBar, persistência localStorage, soft variants para status
✅ **IA Batch Similarity**: 89% de prefixos identificados via Gemini batch contextual
✅ **Ranking de fabricantes**: matching melhorado (45% defects cruzados via _norm + pppoe_user)
✅ **Romaneio de Devolução à Empresa** (na desativação): lista pertences + ONTs + insumos com checkboxes, **assinatura digital do recebedor** (canvas), histórico em `db.collab_returns`, pertences viram automaticamente `status=devolvido`
✅ **Atendimento IA**: nova aba com CRUD de agentes conversacionais, playground multi-turn (Gemini/Claude/GPT via Emergent LLM Key), integrações MagnusBilling (SIP) + WhatsApp Cloud com mascaramento de secrets, webhook receiver de chamadas e histórico
✅ **Assinantes**: cadastro de clientes ISP com normalização de telefone BR e auto-link em chamadas/webhook/playground (4 formatos diferentes matcham mesmo subscriber); IA recebe contexto do cliente no prompt e personaliza atendimento
✅ **MagnusBilling em Configurações** (10/05/2026): card dedicado em Configurações com URL/Key/Secret em branco para preenchimento manual, botão Testar conexão e ponto verde/vermelho com pulse. **Monitor automático em background** (a cada 60s) re-testa MagnusBilling + WhatsApp Cloud e atualiza status — gestor vê quando o serviço cai. Endpoint `GET /api/aihub/integrations/status-summary` consumido com auto-refresh de 30s no frontend.
✅ **Voz da Jerusa — atendente IA por telefone** (10/05/2026): pipeline completo turno-a-turno Whisper STT → GPT-4o-mini → OpenAI TTS (voz "nova" pt-BR) via Emergent LLM Key. Endpoints `POST /api/voice/sessions/start /turn /end`, stub `/sip/incoming` para MagnusBilling/Asterisk AGI plugar depois. Agente "Jerusa" auto-criado na primeira chamada (prompt customizado de atendente ISP). Frontend `JerusaCallSimulator.js`: WebRTC push-to-talk no browser para testar a Jerusa hoje sem precisar de DID/SIP — primeiro sub-tab default em Atendimento IA. Performance medida: ~4.6s por turno (STT 600ms · LLM 2.3s · TTS 1.7s). Cache em memória do mp3 da saudação (hit ratio ~100% após primeira chamada). Testing agent: 8/8 pytest cases PASSED, frontend 100%.
✅ **Configurar Robô (estilo PDF Ligo Fibra)** (10/05/2026): 4 novos campos no `Agent` (`company_info`, `pricing_info`, `priority_situations` + system_prompt). Endpoint `POST /api/aihub/agents/text-gen` (modos `gerar`/`aprimorar` via gpt-4o-mini). Tool `schedule_lousa_ticket` (substitui Google Calendar) — IA cria bolhas reais na Lousa com round-robin pelo técnico com menor carga, relato prefixado `[IA]`, `created_by_source=aihub`. Frontend: seção "Personalidade & Expertise" com card "Gerador Inteligente de Prompts" + botões Aprimorar/Gerar Novo. Testing agent: 9/9 pytest + frontend OK.
✅ **WhatsApp por QR Code (Baileys)** (10/05/2026): Node.js sidecar `@whiskeysockets/baileys` (porta 3002, supervisor) + FastAPI proxy `/api/whatsapp-baileys/{qr,status,send,logout,inbound,messages,auto-reply}` + React `WhatsAppQRPanel` com QR PNG renderizado, polling adaptativo (3s desconectado, 8s conectado). Sessão persiste em `/app/whatsapp-service/auth_info/`. Webhook inbound auto-linka telefone ao Subscriber e salva em `aihub_wa_messages`. **HMAC token `WA_INBOUND_TOKEN`** protege webhook contra injeção externa. Testing agent: 7/7 backend + frontend 100%.
✅ **WhatsApp Auto-Reply (Jerusa 24/7)** (10/05/2026): toggle por empresa em `aihub_settings`, quando ativo a Jerusa responde sozinha cada inbound. Session multi-turno estável por telefone (`session_id=wa-{phone}`). Injeta contexto do Subscriber (plano/status/débitos) quando vinculado. Pula grupos (@g.us) e mensagens do próprio número. Outbound persistido com `delivery_status=sent|failed` + `auto_reply=true`. Testado com WhatsApp real conectado (+5521965680949 "Patrocínio 🇧🇷") respondendo conversas reais com emojis sutis. Testing agent: 12/12 backend pytest.
✅ Pytest backend + ESLint frontend ativos
✅ Roadmap pronto em `/app/memory/ROADMAP.md`

## Próximas (P2)
- Refatorar `routes/lousa.py` (>2400 linhas) e `CadastroPanel.js` (>1200 linhas)
- Melhorar matching Atlaz↔SmartOLT para chegar próximo de 100% (ainda 11/20 unmatched)
- Tema dark: revisar painéis com backgrounds hardcoded (`#fff`/`#f8fafc` em alguns modais)

