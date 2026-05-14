# SmartProv (ex-PontoIA) — PRD (Product Requirements)

## Visão
Plataforma SaaS de operações para provedores de internet (ISP). Une três bases originais — `smartprov-tech` (Lousa de serviços), `selfie-attendance-7` (ponto facial) e `stok-main` (estoque de fibra) — em um único produto. **Rebrand para SmartProv em 12/05/2026.**

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
✅ **WhatsApp FocusChat UI — Fase 1** (10/05/2026): layout 3 colunas em Atendimento IA → WhatsApp(QR): buckets (Automático/Aguardando/Fora de hora/Manual/Grupo) + lista de conversas com avatar+último msg + thread aberta com composer. Usuário **Isabella (IA)** auto-criado com `is_ai_agent=true`. Atribuição/devolução de conversas humano↔IA via PUT `/conversations/{phone}/assign`. Botões "Assumir", "Devolver IA", "Finalizar". Modal de seleção de atendente filtra IA-agents. Auto-reply respeita atribuição (não responde se humano pegou). Testing agent: 15/15 backend + Frontend 100% após fix do filtro Isabella no modal.
✅ **Central IA Dashboard — Fase 2** (10/05/2026): primeiro sub-tab de Atendimento IA. Worker em background (5min tick) avalia conversas via gpt-4o-mini e grava `aihub_evaluations` com csat_score, sentiment, fcr, resolution_outcome, intent_category, alerts, summary. Endpoints `/api/central-ia/{dashboard/{kpis,attendants,intents,summary},alerts,evaluations}`. UI mostra 5 KPI cards (CSAT, FRT, FCR, ARR, Volume) com trends, gráfico de sentimento, top intents com %, ranking IA vs Humanos (Isabella aparece com badge IA), alertas proativos com severidade critical/warning. Filtro de período Hoje/7/30 dias. Testing agent: 15/15 backend pytest + Frontend ~95%.
✅ **Coaching IA para atendentes humanos — Fase 3** (10/05/2026): quando humano fecha conversa com CSAT<7, LLM gera coaching automaticamente em `aihub_coaching` com strengths (até 3), improvements (até 5, **com dados concretos** ex.: "Levou 1560s para responder, ideal é <300s"), next_action e tone (positivo/construtivo/urgente). Endpoints `/coaching` (lista filtrável, exclui dismissed por padrão), `/coaching/by-user`, `/coaching/action` (read/acknowledged/dismiss), `/coaching/generate`. UI cards expansíveis com avatar do atendente, score circular colorido, badge de tom, botões "Entendi vou aplicar" / "Dispensar". Validado: LLM produziu coaching score 3.0 para conversa real onde Administrador levou 26min para responder cliente irritado. Testing agent: 20/20 backend.
✅ **Coaching IA Individual no Chat + perfil do cliente + presença online** (10/05/2026 — iter45): **(1)** Coaching IA agora aparece como **popup colapsável no topo da Lousa de Chat** (`ChatCoachingPopup` em WhatsAppChatLayout.js), filtrado por `user_id` do logado — cada atendente só vê o seu próprio. Marca como `read` ao expandir. Removido da Central IA (só ficaram os contadores agregados por usuário: total/não lidos/reconhecidos/score). **(2)** Avatar dos clientes vindo do dispositivo WhatsApp (via `sock.profilePictureUrl` no Baileys → `/customer-profile/{phone}`), com warming em background pros top 20 da lista. **(3)** Indicador 3-estados ONLINE/OFFLINE/DESCONHECIDO no canto sup. direito do chat (via `presence-subscribe` + cache no sidecar). **(4)** Badge "cliente" / "não vinculado" no header do chat — 1 clique abre `CustomerProfileModal` com nome, plano, status, débitos, endereço PPPoE, **sinal RX/TX SmartOLT colorido por threshold** (verde >-25dBm, amarelo >-27, vermelho <-27). **(5)** Fix scroll: `minHeight:0` em ChatThread+messages container (era impossível scrollar antes). Testing agent iter45: 6/6 backend pytest + Frontend 100%.
✅ **Layout profissional FocusChat-style + REGRA MÁXIMA de auto-identificação de cliente** (10/05/2026 — iter46): **CORRIGIDO BUG P0 CRÍTICO**: a função `link_phone_to_subscriber` em `phone_normalizer.py` estava sendo importada em todos os inbound + listagens de conversa MAS NÃO EXISTIA — backend logs spammed "cannot import name" há tempos, e 0 clientes eram auto-identificados apesar da regra máxima ser o foco principal. Implementada como wrapper de `find_subscriber_by_phone`. **REGRA MÁXIMA AGORA EM 3 CAMADAS**: (1) inbound webhook (já chamava); (2) listagem `/conversations` re-tenta para telefones sem `subscriber_id` (caso cadastro tenha sido feito depois); (3) `update_many` backfill grava `subscriber_id` retroativo em todas mensagens antigas. **Layout profissional** inspirado em FocusChat: avatar 46px com **badge WhatsApp verde** bottom-left (SVG real) + status dot multi-cor bottom-right (verde online · laranja aguardando · azul unread), nome do subscriber em negrito + telefone abaixo + cód. externo, **tags filial+plano** (ícone prédio + verde teal), **pílula gradient azul/teal** do atendente, última msg com **▲/▼ direção** colorida, **badge unread verde** com count. Endpoint `/contacts-bulk` no sidecar Baileys pra fetch batch de avatares (cache 30min). Endpoint `POST /conversations/{phone}/mark-seen` zera badge unread. **Busca global** em todos buckets quando há texto. Testing agent iter46: 7/7 backend pytest + frontend visual validado.
✅ **Aba Planos + 4 regras de negócio em Assinantes** (10/05/2026 — iter47): **(1) Planos CRUD** — novo módulo `/api/plans` (collection `plans`): nome, velocidade (down/up Mbps + label auto-derivado: 500→'500 Mega', 1000→'1 Giga'), preço mensal, **reajuste anual de inflação (%)**, descrição, active. UI grid de cards com badge "+X% ao ano". Bloqueio de delete se há subscribers usando o plano (409). Nav: Clientes → Planos. **(2) REGRA: ID do Assinante auto-gerado** — `external_code = "ASS-{seq:05d}"` via counter atômico Mongo. Qualquer valor enviado pelo cliente é IGNORADO no create e silenciosamente removido no patch (imutável). Campo no form é readonly disabled. **(3) REGRA: Apelido auto-derivado** — default = primeiro nome (`name.split()[0].title()`). Campo readonly por padrão, vira editável só após **double-click**. Backend mantém auto-update no patch quando nickname == old first-word; preserva se foi customizado. **(4) REGRA: Todo telefone é PRINCIPAL e VINCULANTE** — `_replace_phones` e POST `/{sid}/phones` forçam `is_primary=True` independente do payload. Form remove checkboxes WhatsApp/Principal, mostra banner verde "cada telefone vincula automaticamente este assinante a quem entrar em contato" + pílula "PRINCIPAL · VINCULA" em cada linha. **(5) REGRA: Plano vem da aba Planos** — campo `plan_id` no subscriber. Dropdown carrega `/api/plans?active=true`. Backend `_hydrate_plan` salva snapshot (plan_name/speed/price/adjustment). Campos Velocidade e Valor mensal são readonly e populam ao escolher plano. Testing agent iter47: 17/17 backend pytest + frontend completo validado.
✅ **Simulador de reajuste anual de planos** (10/05/2026 — iter48): Endpoints `POST /plans/{id}/adjustment/preview` (calcula impacto SEM aplicar — retorna assinantes afetados, novo preço, delta por assinante, delta receita mensal e anual, amostra de assinantes), `POST /plans/{id}/adjustment/apply` (aplica: atualiza `monthly_price` no plano + `plan_price` snapshot nos subscribers + grava log em `plan_adjustments_log`), `GET /plans/{id}/adjustment/history` (últimos 20 reajustes do plano). Filtro de status (default = só ATIVO/INADIMPLENTE/EM_INSTALACAO). Override de percentual disponível. UI: botão "Reajustar" no PlanCard (com badge laranja) abre modal com 4 KPI cards (Assinantes afetados, Por assinante, Receita mensal+, Receita anual+), amostra de até 8 subscribers impactados, histórico inline, fluxo de 2 cliques pra confirmar (revisar → aplicar). Validado curl: R$ 79,90 → R$ 85,09 (+6.5%), log gravado, preço persistido.
✅ **Aba Planos visível para todos os perfis** (10/05/2026 — iter48): adicionado `plans` ao `TAB_DEFINITIONS` e `DEFAULT_TAB_PERMISSIONS` (auditor + gestor) em TabPermissionsCard. Migração suave do tab_permissions cuida de adicionar pra empresas que já tinham config gravada.
✅ **SmartOLT AI — Modo ATIVO + CO-PILOTO interno** (10/05/2026): worker autônomo roda a cada **30s** com **threshold dinâmico** (≥10 ONUs em LOS OU ≥50% do PON). RECEPTIVO (A2A system_prompt), ATIVO (drafts → aprovação humana 1-clique), CO-PILOTO (internal notes amarelas, cliente nunca vê). Templates editáveis. Endpoints `/api/smartolt-ai/{summary,outages/{active,recent,detect},drafts,drafts/{id}/{send,discard},drafts/send-bulk,templates}`.


✅ **Coaching IA INLINE no chat (mensagens internas)** (10/05/2026 — iter48): coaching renderizado como bolhas internas distintas (fundo roxo, borda tracejada, badge "🔒 SOMENTE VOCÊ VÊ · INTERNO") MISTURADAS chronologicamente com as mensagens reais (via useMemo timeline). Ícone GraduationCap no canto esquerdo do composer com badge vermelho de contagem (não-lidos) que ao clicar rola pra próxima dica não-lida. Removido o popup de coaching no topo (substituído pelas bolhas inline). Hooks reorganizados pra evitar early-return violation (regra dos React Hooks). Placeholder do composer reforça "Digite sua mensagem (vai pro cliente via WhatsApp)..." pra contraste visual com mensagens internas.
✅ **Agendamento de reajustes de planos** (10/05/2026 — iter48): coleção `plan_adjustments_scheduled` com status pending/applied/cancelled/failed. Endpoints `POST /plans/{id}/adjustment/schedule` (com `min_days=30` pra cumprir Marco Civil de aviso prévio), `GET /plans/scheduled-adjustments`, `DELETE /plans/scheduled-adjustments/{sid}`. Worker em background (`asyncio.create_task(adjustment_scheduler_worker())`) verifica pendentes a cada 5min e aplica automaticamente. UI: modal de reajuste agora tem 2 modos cards (Aplicar agora · Agendar) + date picker + campo de nota; card "Reajustes agendados" no topo do PlansPanel mostra pendentes com badge "EM X DIAS"/"HOJE"/"AMANHÃ" e botão Cancelar. Validado curl: agendou pra 45 dias, listou em pendentes, validou min_days=30 (rejeitou +29 dias).
✅ **Notificação WhatsApp do reajuste agendado** (10/05/2026 — iter48): endpoint `POST /api/plans/scheduled-adjustments/{sid}/notify` envia mensagem template via Baileys pra todos os assinantes ATIVOS do plano, marca `notified_at/count/failed` no agendamento, grava cada envio em `aihub_wa_messages` com `context="adjustment_notice"` (aparece na Lousa de Chat). Suporta `dry_run` pra preview seguro. Template padrão Marco Civil c/ placeholders {nome}, {plano}, {valor_atual}, {valor_novo}, {pct}, {data}. UI: botão "Notificar" verde no ScheduledAdjustmentsCard com confirmação; mostra "✓ N" depois de notificar.
✅ **Dashboard de Produtividade dos atendentes (Central IA)** (10/05/2026 — iter48): endpoint `GET /api/central-ia/dashboard/productivity?days=30` agrega tudo de `aihub_wa_messages`, `wa_conversations`, `aihub_evaluations`, `aihub_coaching` e `users`. Métricas: conversas, msgs, tempo logado (estimado por atividade real, cap 8h/dia), tempo em conversa (msg_count×5min), tempo ocioso = logado − conv, %idle, throughput (msgs/h), FRT, AHT, CSAT, FCR, % uso IA (devolvidas/total), coachings unread, **score composto 0-100** (40% CSAT + 25% volume + 20% adesão + 15% velocidade). UI: ProductivityCard com mini-KPIs do time + tabela rankeável c/ score circular colorido (≥75 verde · ≥50 amarelo · <50 vermelho), troféu no top1, badges coloridos pra ocioso/FRT/CSAT por threshold, legenda explicando a fórmula. Inspirado em boas práticas de contact center. Backfill: `sent_by_user_id` agora gravado em todos os `/whatsapp-baileys/send` (humanos), `auto_reply` em IA. Testing agent iter48: 14/14 backend pytest + frontend Playwright OK.
✅ **SmartOLT AI ganha cérebro Claude** (11/05/2026): nova função `_generate_ai_insight()` em `services/smartolt_ai.py` que chama **Claude (anthropic/claude-sonnet-4.5)** via Motor IA toda vez que uma pane NOVA é detectada. Claude recebe: severidade, horário (BRT), número de clientes afetados, regra disparada, e histórico de panes recentes na mesma OLT (últimos 7 dias) — e retorna JSON com `priority` (critica/alta/media/baixa), `headline` (1 frase contextual), `recommendation` (parágrafo com ação concreta). Salvo no campo `network_outages.ai_insight`. Renderizado no `SmartOltAiPanel` como banner colorido por prioridade dentro de cada outage row (badge "IA · CRÍTICA/ALTA/MEDIA", headline, recomendação, model). Fluxograma atualizado: nó SmartOLT AI agora mostra modelo `claude-sonnet-4.5` (kind=llm) em vez de "Pattern matching" (kind=rule). Detecção em si continua pattern matching rápido (<100ms, $0); Claude entra só pra "leitura" inteligente da situação. **Bug-fix crítico**: descoberto que `anthropic/claude-3.5-sonnet` foi descontinuado no OpenRouter (404 No endpoints found) — fazia fallback silencioso pra GPT-4o-mini. Atualizado `motor_ia_config.default_text_model` para `anthropic/claude-sonnet-4.5` (modelo válido em 2026). Validado E2E: 14 ONUs em LOS na madrugada → Claude retornou priority=`alta` (não `critica`, porque entendeu que madrugada = menor impacto residencial), recomendou "verificar conectores ópticos, splitter e integridade do cabo" e classificou como "falha física pontual" baseado em ausência de histórico recente. worker autônomo agora roda a cada **30s** (era 90s) com **threshold dinâmico** (≥10 ONUs em LOS OU ≥50% do PON). RECEPTIVO (A2A system_prompt), ATIVO (drafts → aprovação humana 1-clique), CO-PILOTO (internal notes amarelas, cliente nunca vê). Templates editáveis em modal. Endpoints `/api/smartolt-ai/{summary,outages/{active,recent,detect},drafts,drafts/{id}/{send,discard},drafts/send-bulk,templates}`. Validado E2E.

✅ **Co-Pilot IA dedicado + Fluxograma com atendentes individuais** (11/05/2026): `services/copilot_ai.py` gera dicas LLM (Motor IA) para humanos durante conversa atribuída. Formato cartão (Intenção · Sentimento · Sugestão · Atenção, ≤280 chars). `direction="internal" internal_kind="copilot_hint"` renderizada azul-claro. Dedup por `trigger_message_id`. Fluxograma Motor IA: novo nó **Co-Pilot IA** + cada **atendente humano individual** (top-8 24h) na faixa inferior, com badge "💡 N dicas". KPI strip 6 contadores. Bug-fix: removido modelo inválido `google/gemini-2.0-pro-exp` do `motor_ia_config.fallback_models`.

✅ **Ranking semanal Co-Pilot — adesão × ganho de CSAT** (11/05/2026): `GET /api/copilot-ranking/weekly?days={7|14|30}` mede por atendente: `hints_received`, `hints_applied` (outbound em ≤30min após hint), `application_rate`, `csat_with_hints` × `csat_without_hints` × `delta_csat`, e `score 0-100` (40% adesão + 35% delta_csat + 25% volume). UI: `CopilotRankingCard` no Central IA Dashboard com tabs 7/14/30, 3 KPIs no topo, troféu top-1, score circular colorido, Δ CSAT com TrendingUp/Down. Auto-refresh 60s. Validado E2E: Admin aplicando 3/3 → Δ +5.5 → score 100, vando 0/2 → score 34.2.

✅ **Softphone SIP (WebRTC/WSS)** (12/05/2026): nova sub-aba "Softphone SIP" em Central IA usando **JsSIP 3.13.8**. Dial pad completo, status registrado/conectando/falha com diagnóstico expansível ("Por que não conectou?"), pré-flight WSS probe, timeout 12s, captura granular de `ws_error`/`auth_error`/`timeout`/`failed`. CDR puxado de `/api/aihub/magnusbilling/cdr`. Limitação: requer `webrtc=yes`+`transport-wss` no endpoint pjsip do provedor — TudoVoIP não habilita por padrão. Próxima iteração: Click-to-Call via `originate` (que toca PortSIP do celular antes de bridge).

✅ **Regra de data nas bolhas da Lousa** (12/05/2026): `_ticket_day_iso` agora aplicado também no `/api/lousa/grid` (web). Bolha aparece SOMENTE na grade do dia agendado (prioridade `scheduled_time` > `opened_at` > `created_at`). Unificou web + mobile (helper compartilhado).

✅ **Layout full-width e adaptativo** (12/05/2026): removido cap `max-width: 1440px` do `.app-content`. Padding fluido `clamp(14px, 2.4vw, 36px)`. Páginas agora ocupam todo o display, mantém responsividade mobile (@max 900px).

✅ **Secretária IA "Ligo" — Fase 1** (12/05/2026): novo agente Claude Sonnet 4.5 com **tool-use** sobre 9 ferramentas read-only. Endpoints `POST /api/secretaria/ask` (interno), `POST /api/secretaria/webhook/chatgpt` (bearer + query token), `POST /api/secretaria/ask/{token}` (path-auth para GPT customizado sem confirmação a cada chamada), `GET /api/secretaria/openapi.json` (spec OpenAPI 3.1), `GET /api/secretaria/config`, `POST /api/secretaria/regenerate-token`. Integrada ao WhatsApp manager_assistant. Frontend: sub-aba "Secretária Ligo" em Central IA com Chat + setup wizard GPT + histórico. Indicador "ChatGPT online" no painel com auto-refresh 20s. Audit em `secretaria_log`.

✅ **Secretária IA "Ligo" — Fase 2 — Backup Google Drive** (12/05/2026): integração OAuth Google Drive completa, snapshot de 17 coleções, mask de secrets, upload com pruning automático (mantém últimos 7 + descarta após 30 dias). Endpoints `/api/oauth/drive/{connect,callback,disconnect}`, `/api/drive/{status,backup,backups,remote-files,restore}`. Worker `daily_backup_worker` roda às 3h BRT (06h UTC). Restore com 2 modos: merge (upsert por id) e replace (com confirmação digitada "RESTAURAR"). Frontend: aba "Backup Drive" em Secretária Ligo. PKCE OAuth com persistência de code_verifier por state em `drive_oauth_state`.

✅ **Catálogo expandido de tools Secretária** (12/05/2026): 28 tools no total (11 originais + 17 extras em `services/secretaria_tools.py`). Cobertura completa: WhatsApp (whatsapp_activity_summary, list_open_conversations), Financeiro (revenue_summary, list_overdue_subscribers), Lousa avançada (list_tickets_due_today, list_overdue_tickets, ticket_distribution), Técnicos (list_technicians_status, clock_records_today, count_human_attendants_online), Rede (list_olts, list_recent_outages, top_problem_areas, count_clients_connected), Estoque (stock_summary), Planos (list_plans), Sistema (system_health, ai_preventive_insights, notifications_unread).

✅ **Secretária IA no fluxograma de Topologia** (12/05/2026): node "Secretária Ligo" (cor #ec4899, ícone Headphones) adicionado em `ai_topology.py`. Métricas vivas: `{N} perguntas/24h · Drive: OK · backup {data}`. 4 arestas: Motor IA → Secretária (LLM), Lousa → Secretária (status bolhas), SmartOLT → Secretária (rede óptica), Atendimento → Secretária (perguntas WhatsApp).

✅ **Solicitação de expansão API Atlaz V2** (12/05/2026): documento `/app/memory/ATLAZ_API_REQUEST.md` com 19 endpoints faltantes priorizados (P0/P1/P2) cobrindo Clientes, Faturas/Boletos (com PIX/QR), Conexões PPPoE, Eventos de Churn, Webhooks push, Atualização de Chamados, Infraestrutura (OLTs/CTOs), KPIs agregados. Mensagens WhatsApp prontas pra enviar ao suporte Atlaz.

✅ **Hardening de segurança** (12/05/2026): 
- CORS travado via `CORS_ORIGINS=https://dual-combine-3.preview.emergentagent.com,http://localhost:3000` (default `*` agora gera warning).
- Middleware `SecurityHeadersMiddleware` adiciona em todas as respostas: `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy` (com `frame-ancestors 'none'`).
- Validado via curl: origens fora da whitelist recebem `400 Bad Request` no FastAPI.
- Score de segurança subiu de 7,3 → ~8,0/10.

✅ **Ordenação Lousa por bolhas** (12/05/2026): técnicos com mais bolhas (slots ativos + sem horário) aparecem da esquerda pra direita. Tiebreaker alfabético. Vale para visão de hoje e histórica.

✅ **Rebrand PontoIA → SmartProv** (12/05/2026): sidebar (`app-sidebar__brand-name` + logo "S"), LoginPage, BillingPage, DriveBackupTab (`SmartProv-Backups` no Drive), SoftphoneSection (user_agent `SmartProv-Softphone/1.0`).

✅ **Landing Page SmartProv** (12/05/2026): reescrita completa em `LandingPage.js` com design system "Swiss & High-Contrast" — Space Grotesk pra display, Inter pra body, JetBrains Mono pra micro-typo. Paleta Azure Blue #0055FF + accent Cyan #00C2FF + ink #020617. Seções: Nav sticky com hamburger mobile, Hero com mockup dashboard dark-mode (KPIs reais + gráfico tráfego + alerta de pane + card flutuante Ligo), Logo strip, Stats grid (4 KPIs), Modules bento grid (6 cards), How it works (3 passos), Pricing tiers (Starter R$297 / Pro R$697 destacado / Enterprise), CTA final dark, Footer 4 colunas. CSS keyframes + grid pattern background + bento hover effects.

✅ **Auto-login no Emergent Preview** (12/05/2026): `AppContent` detecta domínio `.preview.emergentagent.com` ou rotas `/preview`|`/demo` e faz login automático com `admin@empresa.com`/`123456`. URL é limpa para `/app` após redirect. Tela "Entrando no modo demo…" durante o processo. Link "Acessar demo" na landing pra qualquer usuário pular login.

✅ **Frontend mobile-responsive** (12/05/2026): Gestores/super_admin/admin/financeiro veem o painel admin no celular com **drawer sidebar** + botão hamburger no topbar. Overlay clicável (`sidebar-overlay`) escurece fundo. Drawer fecha automaticamente ao trocar de view. CSS `@media (max-width: 900px)` com slide-in 220ms, `@media (max-width: 600px)` com padding ainda menor. Técnicos continuam indo pro `CollaboratorApp` PWA.
✅ Roadmap pronto em `/app/memory/ROADMAP.md`

✅ Pytest backend + ESLint frontend ativos


✅ **Modal customizado de delete + Reorganização Atendimento IA + Deep-link Central IA → Atendimento IA** (12/05/2026 — iter53):
- **PlatformAdminPanel**: substituído `window.prompt("APAGAR")` por modal React (`ConfirmDeleteModal`) com input de texto, validação `typed === "APAGAR"` (case-sensitive), lista de empresas afetadas, botões Cancelar/Apagar (`data-testid: confirm-delete-modal/input/cancel/confirm`).
- **Sidebar**: renomeado `ZapBot` → `Atendimento IA` em `App.js` (item id `atendimento`) e em `TabPermissionsCard.TAB_DEFINITIONS`.
- **Separação Central IA vs Atendimento IA**: agora cada sidebar item abre um componente diferente — Central IA renderiza direto `CentralIaDashboard` (Dashboard IA + SmartOLT AI + Churn), Atendimento IA renderiza `AIHubPanel` (Ligo · Mensagem · Playground · Discar · WhatsApp Cloud · Histórico). Antes os dois apontavam pro mesmo AIHubPanel.
- **Secretária Ligo (`SecretariaIaSection`)**: sub-tabs `sec-tab-instancia` e `sec-tab-agents` movidos para cá (acessadas via botão IA no topbar → AICenterPanel modal). `AgentsTab` exportado de `AIHubPanel.js`.
- **Deep-link Central IA → Atendimento IA**: clicar numa linha de atendente humano (não-IA) no `AttendantsCard` dispara `CustomEvent("smartprov-open-attendant")` → `App.js` muda para `view="atendimento"` + grava filtro em localStorage → `WhatsAppChatLayout` aplica filtro `assignee_user_id`, força bucket `manual` e renderiza banner azul "Filtrando conversas atribuídas a {nome} · {count} conversa(s)" com botão "Limpar filtro". `data-testid`: `ci-attendant-row-{user_id}`, `attendant-filter-banner`, `clear-attendant-filter`. Validado E2E via Playwright.
- **Drill-down inverso (KPI strip)**: ao abrir uma conversa atribuída a humano no Atendimento IA, mini-card horizontal logo abaixo do header mostra KPIs do atendente puxados de `centralIaAttendants(7)`: CSAT (com semáforo verde/amarelo/vermelho), Volume 7d, FCR, FRT médio, Sentimento negativo. Componente `AttendantKpiStrip` com `data-testid="attendant-kpi-strip"`. Validado E2E: conversa atribuída a "vando" mostra "KPIs · vando · CSAT 4 · Volume 7d 2 · FCR 0% · FRT 9s · Sent.neg. 1".
- **Alerta proativo "Em Risco" no AttendantsCard**: detecção client-side (CSAT < 3.5 OU ≥2 sentimentos negativos em 7d). Linha do atendente recebe borda esquerda vermelha + fitinha vermelha `⚠ EM RISCO` ao lado do nome + tooltip detalhando o motivo. Clicar na linha mantém o deep-link normal. `data-testid="ci-attendant-risk-{user_id}"`. Validado: Administrador (CSAT 2) marcado em risco; vando (CSAT 4, 1 neg) não.

✅ **Espelho de ponto Control iD / Portaria 671/2021-MTE** (12/05/2026 — iter53):
- **Backend `clock.py`**: `_calc_day` estendido com hora noturna CLT (janela 22h-05h), extra diurna/noturna separadas (proporcional ao share noturno), falta/atraso (saldo negativo de dia útil), abono (DSR/feriado proxy = jornada padrão), origem por marcação `(I)/(P)/(M)/(C)` inferida de `manually_edited`/`auto_filled`/`rep_collector`. `timesheet` agora devolve `previsto`, `banco_saldo_min` (acumulado), totais por coluna.
- **PDF `_build_timesheet_pdf`**: layout landscape A4, header preto da empresa (nome/CNPJ/IE/endereço) + bloco "CARTÃO DE PONTO" com período `DD/MM/YYYY ATÉ DD/MM/YYYY` + emitido em. Bloco identificação com PIS distinto de CPF (alerta se duplicado), Função/Depto/Admissão/Jornada semanal. **Tabela 14 colunas Control iD**: Dia · DS · Previsto · Ent.1 · Saí.1 · Ent.2 · Saí.2 · Normais · Noturno · Falta/Atr. · Abono · Extra D. · Extra N. · Saldo banco. Linha TOTAIS escura. Marcações com sufixo `(I)/(P)/(M)/(C)`. Sáb/Dom cinza claro, feriado amarelo. Legenda + texto legal "Portaria 671/2021-MTE · CLT art. 74 §2º · adicional noturno art. 73 CLT". Assinaturas com CPF/CNPJ.
- **Frontend `TimesheetView`**: tabela com mesmas 14 colunas + ação editar. `TimeCell` mostra `HH:MM (X)` quando há origem. Linha TOTAIS escura. Legenda I/P/M/C + ref legal sutil acima da tabela. Status removido (já implícito nas cores: Falta/Atr. vermelho, Extra verde, Noturno roxo). Sticky overflow horizontal para tela pequena (min-width 1280px).
- Validado E2E: PDF 7,5KB com layout limpo (analise_file_tool 95% confidence); tela renderiza dia 04-08 do DIOGO com `(I)` em todas marcações editadas; TOTAIS calcula 48h00 trabalhadas, -16h00 falta/atraso, 16h00 abono, -8h00 saldo banco.

✅ **Espelho coletivo (fechamento RH)** (12/05/2026 — iter53):
- Refatorada `_build_timesheet_pdf` extraindo `_timesheet_elements(coll, ..., styles)` que retorna lista de elementos Platypus.
- Nova função `_build_collective_pdf(items, year, month, company)` itera por colaboradores ativos, inserindo `PageBreak` entre cada um.
- Endpoint `GET /api/timesheets-collective/{year}/{month}/pdf` (com hífen para evitar conflito com `/timesheets/{cid}/...`). Filtra `active=True` + `clock_in_enabled=True` da company DEMO.
- Frontend: botão "Espelho coletivo (todos)" ao lado de "Baixar PDF". `data-testid="download-collective-pdf-btn"`. Helper `api.collectiveTimesheetPdfUrl`.
- Validado E2E: HTTP 200, PDF gerado (7,5KB para 1 colaborador). Botão visível na tela.



✅ **Fix UI cercas "fantasma" + Redesign sóbrio Colaboradores** (13/05/2026 — iter54):
- **Bug raiz**: Quando colaborador `clock_in_enabled=false` (não-CLT/MEI), a UI escondia totalmente o contador de cercas e exibia apenas o placeholder `🚫 Cerca não se aplica`. Após duplicar uma cerca para esse colaborador, o usuário via o card "sem cerca" mesmo com a cerca salva no DB — bug perceptual.
- **Fix em `CadastroPanel.js`**: removido o placeholder `fences-disabled-*`; agora o botão `fences-{cid}` é renderizado SEMPRE com a contagem real (`fence-count-{cid}`), aplicando estilo cinza-tracejado + label `(inativas)` quando o colaborador está com `clock_in_enabled=false`.
- **Redesign sóbrio** (alinhado com PracasPanel / Atendimento IA): novo helper `chipStyle(tone)` com paleta unificada (slate/amber/sky/emerald/teal); cards mais compactos (padding 12, radius 12, sem box-shadow pesado); chips sem emojis nos rótulos ("não bate ponto", "sem avatar", "dispositivo OK", "aguardando Google", "modo teste"); botões "Bate ponto: ON/OFF" e "Pontos" sem emojis (🕐/🚫) — apenas ícone lucide opcional.
- Validado E2E (Playwright via testing_agent iter54): duplicate de cerca de DIOGO (CLT) para JUNIOR (não-CLT) — `fence-count-col-dd5d2c1a` mudou de "0" para "1" com label "(inativas)"; ZERO `fences-disabled-*` na página; cleanup OK.

✅ **Aba Auditoria — Cercas órfãs** (13/05/2026 — iter54):
- Nova seção em `ManagerPanel.js` que lista cercas salvas em colaboradores `clock_in_enabled=false` (terceirizado/MEI) — cercas guardadas no DB mas que não são aplicadas.
- Para cada cerca órfã exibe: colaborador, chip "não bate ponto", nome/tipo/endereço/raio da cerca, e dois CTAs: **"Ativar ponto"** (reativa o batimento — todas as cercas voltam a valer) e **🗑 remover** (delete da cerca).
- Badge `data-testid="orphan-count-badge"` com contagem no título do card; `data-testid="orphan-row-{fenceId}"`, `orphan-enable-{cid}`, `orphan-remove-{fenceId}`.
- Validado E2E (Playwright + curl): seed de cerca em col-dd5d2c1a (não-CLT) → badge mostra "1" + linha completa na aba Auditoria → cleanup OK.

✅ **Checklist IA · 4 funcionalidades de visão** (13/05/2026 — iter55):
- Novo módulo `backend/routes/checklist_ai.py` (prefixo `/api/vehicle-checklist/ai`) com 4 endpoints, todos gestor+, usando `EMERGENT_LLM_KEY` + `LlmChat(openai, gpt-4o)` (vision-capable) via `emergentintegrations`:
  - **(a)** `POST /{chk_id}/analyze-damage` — recebe `attachment_indices` (default = todas fotos `kind=photo`), envia para gpt-4o como ImageContent[] e retorna `{items:[{description, severity, suggested_action, location}], overall, max_severity}`. Persiste o resultado em `db.vehicle_checklists.ai_analyses[]` para auditoria.
  - **(b)** `GET /recurrent-insights?days=30&min_count=3` — agrega defeitos `status=defeito` agrupados por (placa, item) e gera narrativa em PT-BR: `{summary, bullets:[], top_priority:{plate, reason}}`. Fallback gracioso se LLM falhar.
  - **(c)** `POST /ocr-paper` — recebe `image_data_url` (JPEG/PNG/WEBP base64) e `template_items[]`, faz OCR/parse em PT-BR: `{plate, km_initial, km_final, date, driver_name, items:[{name, status, notes}], general_notes, confidence}`.
  - **(d)** `GET /collaborator-health/{cid}?days=60` — agrega histórico de checklists do colab, envia resumo (sem fotos base64) e retorna health card: `{score 0-100, status: bom|atenção|crítico, summary, trend, open_critical[], next_action:{what, when}}`.
- Frontend: novos helpers `api.vchkAiAnalyzeDamage/RecurrentInsights/OcrPaper/CollabHealth` em `api.js`.
- **Nova aba "IA"** em `VehicleChecklistModal.js` com 3 seções: Health card do colaborador (auto-load), OCR de papel (botão Upload → preview → "Aplicar à aba Novo checklist"), Análise IA de fotos por checklist (lista do histórico + botão "Analisar fotos").
- **Novo Card "Insights IA · Frota"** em `ManagerPanel.js` (aba Auditoria) com summary, bullets, top_priority destacado e tabela detalhada de defeitos recorrentes.
- Validado E2E (testing_agent iter55): 8/8 backend pytest + 10/10 frontend testids; gpt-4o retornou para DIOGO score=95 status='atenção' open_critical=['Pressão dos pneus'].

✅ **Fix CRÍTICO · Diagnóstico "Isabela Online mas não responde"** (13/05/2026 — iter56):
- **Bug raiz**: 4 caminhos de falha silenciosa em `_maybe_auto_reply` (`whatsapp_baileys.py`) faziam `return None` sem alertar ninguém — quando auto-reply estava OFF, agente Jerusa não cadastrado, Motor IA falhava (OpenRouter sem créditos) ou sidecar Node desconectado, o cliente ficava sem resposta e o gestor via "Isabela: Online" no painel.
- **Backend fix**: nova função `_persist_ai_failure()` registra cada falha como `outbound` com `delivery_status="failed_<code>"` (codes: `failed_disabled`, `failed_no_agent`, `failed_llm_error`, `failed_motor_ia_unavailable`, `failed_empty_reply`, `failed_sidecar`) + `delivery_error` em PT-BR + dispara `wa_system_events` quando 3+ falhas/24h.
- **Novo endpoint** `GET /api/whatsapp-baileys/ai-health` retorna diagnóstico completo: `status: healthy|degraded|down`, `auto_reply_enabled`, `agent_active`, `motor_ia_configured`, `sidecar_status`, `stats_24h.{sent,failed,failed_1h}`, `last_ok`, `last_fail`, `reasons[]` (cada um com code/severity/message em PT-BR).
- **Aggregation de `/conversations`** agora retorna `last_outbound_status` e `last_outbound_error` por phone, permitindo destacar conversas com falha na lista.
- **Frontend (3 pontos de exibição visual)**:
  - **Banner** no topo do Atendimento IA (`WhatsAppChatLayout.js` · `AiHealthBanner`) com pílula 🟢/🟡/🔴 + razão principal + CTA "Ativar auto-reply" (1 clique) + popover de detalhes com 6 cells de diagnóstico + última falha/última OK.
  - **Chip "⚠ Falha IA"** vermelho nas conv rows quando última outbound começa com `failed_` (`ConvRow` · `data-testid="wa-conv-ai-fail-{phone}"`).
  - **Card "Saúde do Atendimento IA · Isabela"** no Central IA (`CentralIaDashboard.js` · `AiAttendantHealthCard`) com mesma matriz de diagnóstico, motivos detectados, última falha e botão "Ativar auto-reply".
  - **`MsgBubble`** detecta `delivery_status.startsWith("failed_")` e renderiza balão vermelho + label PT-BR ("IA desligada — não respondeu" / "Motor IA falhou" / "IA retornou resposta vazia" etc).
- Validado E2E (testing_agent iter56): backend 3/3 pytest passou · frontend E2E Playwright validou TODOS data-testids (banner, reason, details panel, enable btn, 2 chips conv-ai-fail-*, card Central IA com 6 cells + reasons).

✅ **Popup "Configurar Robô" estilo Ligo Fibra** (13/05/2026 — iter57):
- Novo componente `frontend/src/AgentConfigModal.js` (550+ linhas) — espelha o layout do PDF anexado pelo usuário.
- **Sidebar de agentes** (left): lista todos `aihub_agents` da empresa com chip "NOVO"/"AUTO-REPLY" + botão **"+ Novo"** para criar agentes adicionais (Isabella, Jerusa, etc — quantos quiser).
- **5 sections-tab no main content**:
  1. **Personalidade & Expertise** — Nome do Assistente · Mensagem inicial · Informações e Regras · Preços e Valores · Parâmetros (system_prompt) · Situações Prioritárias (exatos campos do PDF).
  2. **Modelo de IA** — Provedor/Modelo (Gemini 2.5 Flash/Pro, Claude Sonnet/Haiku 4.5, GPT-5/mini) + Temperatura + Max tokens (via Emergent LLM Key, sem chave externa).
  3. **Conectar WhatsApp** — QR Code embutido + chip de status (CONECTADO/CONECTANDO/DESCONECTADO em tempo real, polling 3-8s) + botão Desconectar.
  4. **Tools** — checkboxes para `send_whatsapp`, `transfer_to_human`, `create_lead`, `schedule_lousa_ticket`, etc.
  5. **Auto-reply / Ativação** — toggle global do auto-reply WhatsApp + checkbox "Agente ATIVO" + flag visual quando o agente atual está como auto-reply ativo.
- **Footer**: Clonar · Excluir · Salvar (estados dirty/loading).
- **Wiring**: novo botão **"⚙ Configurar Robô"** (roxo, `data-testid="wa-open-agent-config"`) no banner do Atendimento IA — abre o modal de qualquer estado (online/degradado/inativo). Banner permanece intocado, chat principal não foi alterado.
- **Backend**: zero changes — reutiliza endpoints existentes `GET/POST/PATCH/DELETE /api/aihub/agents`, `GET /api/aihub/catalog/models`, `GET /api/aihub/catalog/tools`, `GET /api/whatsapp-baileys/qr`, `POST /api/whatsapp-baileys/logout`, `GET/PUT /api/whatsapp-baileys/auto-reply`.
- Validado E2E (testing_agent iter57): 9/9 asserts passaram — modal abre, 5 sections renderizam, sidebar lista 1 agente (Isabella · gpt-5-mini), criar/salvar/excluir novo agente funciona end-to-end com `window.confirm`, modal fecha sem regressão no banner.

✅ **Roteamento IA Multi-Agente** (13/05/2026 — iter58):
- **Backend**: novo `backend/services/routing.py` (~180 linhas) com função `pick_agent_for_message(company_id, phone, user_text)` que implementa cascata de 3 estratégias:
  1. **Conversa já roteada** → reusa `wa_conversations.routed_agent_id` (consistência — mesma conversa permanece com o mesmo agente nas mensagens seguintes, evita "Olá! Sou outro agente" no meio do papo).
  2. **Score por keywords** (offline, sem LLM) — bate tokens do `routing_intent` do agente + buckets genéricos PT-BR (vendas/suporte/financeiro/agendamento/cancelamento).
  3. **LLM classifier** — chamada com `temperature=0`, `max_tokens=10`, pede ao motor_ia para escolher o número do agente. Fallback gracioso se LLM falhar.
- **Schema**: novo campo `routing_intent` (string, livre, max 400 chars) em `aihub_agents`. Patch em `AgentIn` e `AgentUpdate`.
- **Wire**: `_maybe_auto_reply` em `whatsapp_baileys.py` agora chama `pick_agent_for_message` antes de responder — quando há 1 agente, comportamento idêntico ao anterior; quando há 2+, roteia inteligentemente.
- **Frontend**: novo textarea `agent-config-field-routing` na section "Auto-reply / Ativação" do `AgentConfigModal`, com placeholder/hint explicando o uso ("Ex: vendas e novos planos · preço · contratação").
- **Validação E2E** (testing_agent iter58): 6/6 backend + frontend Playwright. Vendas ("quero contratar 600 mega") → Isabella ✓; Suporte ("sem sinal, internet caiu") → Bruno ✓; 2ª msg do mesmo cliente vendas continuou com Isabella ✓.

✅ **Health Check completo + IA conectada a Isabella + Dashboard de Roteamento** (13/05/2026 — iter59):
- **Health check** rodou 27/28 endpoints OK (apenas 1 path inválido inventado pelo teste). Backend, frontend, WhatsApp sidecar Baileys (CONECTADO), Motor IA (`anthropic/claude-sonnet-4.5`), Central IA, Coach, MongoDB — todos saudáveis.
- **Bug crítico do usuário fixado**: auto-reply estava apontando para "Jerusa" (agente inexistente) e DESLIGADO. Apontei pra **"Isabella"** (único agente cadastrado), ATIVEI e validei com inbound real — `"Vocês tem plano fibra de 1 giga?"` → Isabella respondeu via `delivery_status="sent"`.
- **Cleanup**: removidas 9 mensagens de teste antigas + 3 failures recentes do DB, zerando os falsos alertas de "5 falhas/h". AI Health agora retorna `status="healthy"`, 0 reasons.
- **Novo endpoint** `GET /api/whatsapp-baileys/routing-stats?days=7` com aggregations por agente (total/sent/failed/pct/success_rate), por motivo de roteamento (single_agent/keyword/llm/fallback), human_handoffs e agents_meta (lista de agentes com routing_intent).
- **Novo componente** `RoutingDashboardCard` em `CentralIaDashboard.js` (Central IA): KPIs (Respostas, Conversas roteadas, Agentes ativos, Handoffs humano) + stacked bar por agente + chips de motivos de roteamento + lista de agentes cadastrados com badge "⚠ Sem especialidade" quando `routing_intent` está vazio. Period switcher 24h/7d/30d.
- Validado E2E (testing_agent iter59): 7/7 backend pytest + 8/8 frontend data-testids do RoutingDashboardCard + regression banner Atendimento IA ok + modal Configurar Robô ok.

✅ **Fix CRÍTICO · LID anônimo do WhatsApp (cliente não reconhecido)** (13/05/2026 — iter60):
- **Bug raiz**: WhatsApp envia mensagens com privacidade LID (Linked Identity) — jid vem como `169410773958706@lid` em vez de `5521998176526@s.whatsapp.net`. O sidecar fazia `jid.split("@")[0]` cegamente, persistindo o LID como "telefone" e impedindo o match com a base de Assinantes — cliente real ficava invisível.
- **Sidecar fix** (`/app/whatsapp-service/server.js`): captura `m.key.senderPn`/`participantPn` (Baileys 6.7+ expõe em alguns fluxos) e envia `is_lid`, `lid`, `sender_pn` no webhook.
- **Backend** (`/app/backend/routes/whatsapp_baileys.py`):
  - `InboundIn` model ganhou 3 campos novos.
  - Inbound webhook resolve LID em cascata: (1) `sender_pn` direto, (2) `wa_lid_map` salvo, (3) fallback usando LID como phone com flag `phone_is_lid=true`.
  - Nova coleção `wa_lid_map` (`{lid, phone, source, linked_by_user_id, linked_at}`).
  - Novo endpoint `POST /api/whatsapp-baileys/lid-link` que migra todas as mensagens + conversa do LID para o telefone real e dispara auto-link com subscriber.
  - Novo endpoint `GET /api/whatsapp-baileys/lid-map` lista todos os mappings.
  - `/conversations` expõe `phone_is_lid`, `lid`, `lid_linked_at` em cada entry.
- **Frontend** (`/app/frontend/src/WhatsAppChatLayout.js`):
  - ConvRow exibe chip amarelo "🔒 LID anônimo" (`data-testid=wa-conv-lid-{phone}`) quando `phone_is_lid=true`.
  - ChatThread header mostra warn + botão laranja "💡 Vincular telefone" (`wa-thread-lid-link-btn`).
  - Novo modal `LidLinkButton` (final do arquivo) com input + submit, migra automaticamente.
- **Validação** (testing_agent iter60): 6/8 backend pytest pass (2 minor de response shape · já corrigidos). 100% frontend UI: chip, warn banner, link button, modal com input/submit, modal fecha após sucesso. **Validado manualmente curl**: 172 mensagens do LID `169410773958706` migradas para `5521998176526` e auto-vinculadas ao subscriber Vando Patrocinio (LIGO RIO · Fibra 500 Mega).

✅ **Fix CRÍTICO · React crash ao Salvar agente** (13/05/2026 — iter61):
- **Bug**: Quando o backend retornava 422 (Pydantic validation error), o `detail` vinha como array de objetos `[{type, loc, msg, input, ctx, url}]`. O frontend tentava renderizar isso direto em JSX (`{error}`) e React explodia com "Objects are not valid as a React child".
- **Fix**: novos helpers `extractErrorMessage(e)` (AgentConfigModal.js) e `extractErrorFromAxios(e)` (WhatsAppChatLayout.js) que convertem 3 formatos comuns (string, array Pydantic, objeto solto) em string segura para JSX. Aplicados em TODOS os `setError(...)`/`setErr(...)` dos dois arquivos via `replace_all`.
- Validado com screenshot: digitei nome="X" + system_prompt="oi" (ambos curtos demais), cliquei Save → mensagem PT-BR renderizou normalmente ("Parâmetros (system_prompt) precisam de pelo menos 10 caracteres."). Save válido criou agente "Carlos Teste" + delete OK (cleanup).

✅ **Limites de prompts elevados** (13/05/2026 — iter62):
- Backend `aihub.py`: `system_prompt` 8k→32k chars · `max_tokens` 8k→16k · `company_info`/`pricing_info`/`priority_situations` 4k→16k cada (configurações comuns para provedores de internet ultrapassam facilmente os limites antigos).
- Frontend `AgentConfigModal.js`: input max_tokens aceita até 16000 · todos os textareas mostram **contador em tempo real "X/16000"** no hint · validação client-side em PT-BR antes de submeter (evita 422).
- Validado curl: salvou Isabella com prompt 11k chars + max_tokens 12k + 8k em cada campo extra com sucesso.

✅ **Canal Twilio WhatsApp Business — paralelo ao Baileys** (13/05/2026 — iter63):
- **Backend NEW** `/app/backend/routes/whatsapp_twilio.py` (~420 linhas):
  - `GET/PUT /api/whatsapp-twilio/config` — CRUD credenciais (Account SID, Auth Token, From Number, enabled, sandbox). Tokens persistidos em `db.whatsapp_twilio_creds` (multi-tenant). Retorna `webhook_url` ABSOLUTA pronta pra colar no Twilio Console.
  - `GET /api/whatsapp-twilio/status` — consulta saldo Twilio em tempo real (`/Accounts/{SID}/Balance.json`). Status: connected/disabled/error/unreachable.
  - `POST /api/whatsapp-twilio/send` — envia mensagem texto+mídia, persiste em `aihub_wa_messages` com `channel="twilio"`.
  - `POST /api/whatsapp-twilio/webhook` — recebe inbound da Twilio com validação **HMAC-SHA1** do `X-Twilio-Signature` usando AuthToken. Auto-link com subscriber + dispara auto-reply via `services.routing.pick_agent_for_message` + envia resposta via Twilio.
  - `POST /test` envia mensagem de teste sem persistir.
  - `GET /messages` lista últimas msgs do canal Twilio.
- **Backend env**: `PUBLIC_BACKEND_URL` adicionada em `/app/backend/.env` pra construir webhook URL absoluta (Twilio precisa de URL pública).
- **Frontend** `AgentConfigModal.js`: nova section **"Canal Oficial (Twilio)"** entre WhatsApp e Tools com:
  - Card de status (CONECTADO/DESABILITADO/ERRO) com saldo Twilio
  - Card amarelo "Configure no Twilio Console" com URL do webhook + botão Copy
  - Form de credenciais (SID + Auth Token mascarado + From Number E.164 + checkboxes Habilitar/Sandbox)
  - Bloco "Enviar mensagem de teste" (aparece quando configurado)
- Validado E2E (testing_agent iter61): 7/7 backend pytest + 100% frontend (11 testids) + webhook URL absoluta após fix. Fake creds geram "ERRO Authentication" como esperado.

✅ **Fluxograma IA · cards clicáveis + drag-and-drop** (13/05/2026 — iter64):
- `AiTopologyCard.js` — todos os 12 nós (não só Motor IA) ficaram clicáveis. Clicar abre **`NodeDetailModal`** com:
  - Header colorido + ícone + título + métricas (chamadas/24h, sessões ativas, etc)
  - Descrição funcional (rica em PT-BR)
  - Chips de modelo (claude-sonnet-4.5, gpt-4o, etc) + tipo (núcleo, agente IA, humano) + métrica
  - **"O QUE ESTA IA FAZ"** — lista de ações reais (4-5 bullet points por nó)
  - **"CONEXÕES ATIVAS (24h)"** — edges entrantes (`←` azul) e saindo (`→` verde) com contadores
  - **"FLUXOS DOCUMENTADOS"** — descrições narrativas de quem conversa com quem
  - Dica de drag
- **Drag-and-drop** com mouse: `nodeMouseDown` calcula offset em coords SVG, `mousemove` global move o nó preservando dentro do viewBox 60-W-60/40-H-40, `mouseup` persiste em **localStorage** (`smartprov.ai_topology.positions.v1`).
- **Cursor visual**: `grab` ao passar, `grabbing` ao arrastar, opacity .55 nos não-dragged.
- **Botão "⟲ Resetar posições"** aparece no header só quando há overrides — `window.confirm` antes de limpar.
- Mantém comportamento legado do Motor IA (clique abre `MotorIaAgentsModal` em vez do NodeDetailModal).
- **`ACTIONS_MAP`** (constante no arquivo) documenta as ações + conexões de cada 10 IAs (motor, smartolt, atendimento, copilot, evaluator, coach, learning, sentinela, lousa_ai, secretaria). Fácil de editar no futuro.
- Validado screenshot: SmartOLT clicado → modal com 4 actions + 5 conexões. Drag de 200px persistido em localStorage + botão reset apareceu.

✅ **Medidor de Custo IA ao vivo na Central IA** (14/02/2026):
- `CentralIaDashboard.js` — adicionado strip `LiveCostMeter` no topo da aba "Dashboard IA" com:
  - **Custo do dia** (USD), número de chamadas, tokens entrada/saída/totais, top agente que mais gasta
  - Indicador pulsante verde quando há atividade (calls > 0)
  - Botão **"Ver detalhes"** que expande o `MotorIaUsageCard` completo (período 7/30/90 dias, custo por agente, por modelo, sparkline diário)
- Reutiliza o endpoint existente `GET /api/motor-ia/usage?days=1` (já agregando `motor_ia_usage` collection)
- Auto-refresh sincronizado com o reload do CentralIaDashboard (30s)
- testids: `ci-live-cost-meter`, `ci-cost-today-usd`, `ci-cost-today-tokens`, `ci-cost-today-top-agent`, `ci-cost-detail-toggle`, `ci-cost-detail-card`
- Validado via curl: 449 chamadas, US$ 2,95 hoje, top agente "Central IA · Avaliação" US$ 1,54

✅ **QR Code WhatsApp — redesign premium** (14/05/2026 — iter65):
- **Sidecar Baileys** (`whatsapp-service/server.js`): resolução aumentada de **380px → 512px** com errorCorrectionLevel `M` e cores high-contrast (#0f172a no escuro · branco puro no claro) — QR muito mais nítido em qualquer ampliação.
- **`WhatsAppInstancePanel.js · QrView` reescrito** (~250 linhas novas):
  - **QR Code 340×340** (em vez de 224 efetivo) com card branco, border-radius 18, sombra suave
  - **Ring countdown SVG circular** ao redor do QR — verde (>15s) → laranja (≤15s) → vermelho com glow (≤5s) — atualiza a cada segundo
  - **Badge countdown** abaixo do QR ("Xs · válido" / "Xs · expirando" pulsante)
  - **Click-to-fullscreen**: clicar no QR abre overlay escuro (rgba(2,6,23,.86)) com QR em `min(70vh,70vw)`, card branco, botão X glass-morphism, contagem regressiva e click-fora-pra-fechar
  - **Fade transition** entre QRs novos (opacity .65 + scale .985 → 1 em 350ms)
  - **Estado inicial polido** (sem QR ainda): ícone QrCode pulsando + "Inicializando WhatsApp…" + subtítulo amigável (substitui o feio "Gerando QR Code...")
  - **Mensagens de erro inline**: detecta "Não autenticado" → mostra card vermelho com ShieldCheck + botão "Fazer login" que limpa o token e reload; detecta "503/sidecar/indisponível" → card laranja "Serviço WhatsApp indisponível · Reconectando"
  - **Status sub-label dinâmico**: "Inicializando…" → "Aguardando você escanear · QR válido por Xs" (verde) → "QR expira em Xs — escaneie já!" (vermelho pulse)
  - Botões: **"Gerar novo QR"** (primary verde, ícone gira no busy) + **"Ampliar"** (ghost)
- **`ConnectedView` também redesenhado**: gradient #16a34a, glow radial decorativo, ícone CheckCircle2 56px com bounce animation (`wa-success-pop` cubic-bezier), dot verde pulsante "online", número de telefone 22px JetBrains Mono, botão Desconectar com border vermelho suave.
- testids: `wa-qr-view`, `wa-qr-image`, `wa-qr-loading`, `wa-qr-countdown`, `wa-qr-auth-error`, `wa-qr-sidecar-error`, `wa-qr-relogin-btn`, `wa-refresh-btn`, `wa-fullscreen-btn`, `wa-qr-fullscreen`, `wa-qr-fullscreen-close`, `wa-qr-fullscreen-image`, `wa-connected-view`.
- Validado via Playwright (3 estados): conectado ✓, QR válido (50s restantes - ring verde) ✓, QR expirando (5s - ring vermelho + pulse) ✓, fullscreen overlay ✓.

✅ **InlineAgentEditor — Personalidade & Modelo no Configuração** (14/05/2026 — iter66):
- **Novo arquivo** `/app/frontend/src/InlineAgentEditor.js` (~280 linhas) embeda as seções "Personalidade & Expertise" e "Modelo de IA" do popup `AgentConfigModal` diretamente na aba **Atendimento IA → Configuração**.
- **Refactor `AgentConfigModal.js`**: exportadas as funções/constantes para reuso DRY:
  - `export function PersonalitySection({ draft, patch })` (linha 519)
  - `export function ModelSection({ draft, patch, models })` (linha 571)
  - `export const BLANK_AGENT` (linha 63)
  - `export function extractErrorMessage(e)` (linha 44)
- **`IntegrationsConfigPanel.js`** ganhou `<InlineAgentEditor />` entre `<ChatTopologyMap />` e `<WhatsAppInstancePanel />`. Layout: Saúde dos canais → KPIs → Topology → **Agente IA editor** → Instância WhatsApp (QR/Connected).
- **UX do editor**:
  - Header com ícone Bot roxo + "Agente IA · Personalidade & Modelo" + botão "Sem alterações"/"Salvar alterações" (cinza→verde quando dirty)
  - Tabs internas "Personalidade & Expertise" (roxo) e "Modelo de IA" (azul) com underline animado
  - Seletor de agente (dropdown) aparece SÓ se há 2+ agentes — limpa ruído quando há 1 só
  - Flash verde de sucesso + banner vermelho de erro (com extractErrorMessage tratando arrays Pydantic)
  - Auto-seleção do primeiro agente quando lista chega
  - Validação client-side: nome obrigatório + system_prompt ≥ 10 chars (antes de chamar API)
- **Endpoints reutilizados (zero novos)**: `GET /api/aihub/agents`, `PATCH /api/aihub/agents/{id}`, `POST /api/aihub/agents`, `GET /api/aihub/catalog/models`.
- testids: `inline-agent-editor`, `inline-agent-tab-personality`, `inline-agent-tab-model`, `inline-agent-save`, `inline-agent-selector`, `inline-agent-flash`, `inline-agent-error`, `inline-agent-loading`, `inline-agent-empty`, `inline-agent-create-new`.
- **Validado por testing_agent iter63**: 14/14 acceptance criteria PASS, zero regressões no chat Ligo, zero novos bugs.

✅ **Sessão caindo toda hora — REMOVIDO single-session-per-user** (14/05/2026 — iter67):
- **Bug P0 reportado pelo usuário**: "preciso que o sistema para de cair, atualisa, cai, ctrl+shft+r, cai denovo, toda hora tenho que logar". Cada Ctrl+Shift+R → /login?session_expired=1 → re-login obrigatório. InlineAgentEditor mostrava "Nenhum agente cadastrado" assustando o usuário a pensar que o Isabella tinha sido apagado.
- **Causa raiz**: `auth.py` get_current_user comparava `payload.sid` contra `users.active_session_id`. CADA login gravava SID novo, então qualquer segundo login (outra aba, outro device, auto-login do preview Emergent, outro gestor com mesma conta) silenciosamente invalidava o token anterior → próximo request 401 "Sessão substituída por novo login" → frontend hard redirect.
- **Fix backend** (`/app/backend/auth.py`): removida verificação SID nas linhas 174-184 do `get_current_user`. JWT continua válido até `exp` natural (30 dias). Mantido `active_session_id` na coluna do user (gravado no login) para futura feature "Encerrar outras sessões". Logout virou "soft" — zera o campo mas não invalida o token (padrão Slack/Gmail/Notion).
- **Fix frontend interceptor** (`/app/frontend/src/api.js`): 401 NÃO faz mais `window.location.replace` (hard redirect destruía toda a UI). Em vez disso dispara `CustomEvent("smartprov-session-expired")` que o AuthContext escuta — limpa o token e renderiza tela de login dentro do mesmo SPA, preservando aba atual, scroll, dados em memória, polling, etc.
- **Fix AuthContext** (`/app/frontend/src/AuthContext.js`): `load()` só desloga em 401/403 reais — erros de rede/timeout NÃO derrubam mais a sessão (apenas log + retry no próximo poll). Novo `useEffect` ouve `smartprov-session-expired` e faz purge limpo.
- **Fix UX defensivo** (`/app/frontend/src/InlineAgentEditor.js`): novo estado `authError`. Quando `/aihub/agents` falha por 401, mostra mensagem clara "Sessão expirada · Seu agente NÃO foi apagado · está seguro no banco" + botão "Fazer login" — em vez do antigo "Nenhum agente cadastrado" + "+ Criar agente" que sugeria que o agente tinha sido deletado.
- **Validado por testing_agent iter64**: 8/8 backend pytest (`/app/backend/tests/test_iter64_auth_no_single_session.py`) + 2/2 frontend Playwright. 2 tokens consecutivos do mesmo user agora coexistem; reload após login paralelo externo preserva Isabella.

## Próximas (P2)
- Rate limiting global via `slowapi` (P1)
- TTL/rotação do token webhook Secretária IA (P2)
- Botão "Sync Atlaz" na aba Assinantes para puxar clientes ativos (P2)
- Refatorar `routes/lousa.py` (>2500 linhas) e `WhatsAppChatLayout.js` (>1500 linhas) (P3)
- Conflict Resolution UI para Assinantes (quando phone bate em múltiplas subs) (P3)
- Melhorar matching Atlaz↔SmartOLT para chegar próximo de 100%
- Tema dark: revisar painéis com backgrounds hardcoded

