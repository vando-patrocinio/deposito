# SmartProv (ex-PontoIA) — PRD (Product Requirements)

## Visão
Plataforma SaaS de operações para provedores de internet (ISP). Une três bases originais — `smartprov-tech` (Lousa de serviços), `selfie-attendance-7` (ponto facial) e `stok-main` (estoque de fibra) — em um único produto. **Rebrand para SmartProv em 12/05/2026.**

## Personas
- **Administrador** — acesso total. Gerencia configurações da empresa.
- **Gestor** — operação diária: lousa, despacho, conferência de ponto, estoque.
- **Auditor** — compliance e auditoria (incluindo ação destrutiva `wipe-all` de bolhas).
- **Colaborador (Técnico)** — fluxo mobile: bate ponto facial, atende serviços, scaneia QR, cadastra CTOs (Rede IA) em 8 passos.
- **Gestor de Rede** (NOVO 15/05/2026) — `gestor_rede`: aprova/rejeita/solicita correção de CTOs cadastradas pelos técnicos, gerencia bairros/VLAN, edita diretrizes da rede_IA.
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
11. **Training Studio (Multi-Agent Simulator)** — 60 cenários realistas, 20 testes de validação executáveis (Isabela IA + Avaliador IA), 31 regras da matriz de decisão, scoring 100pts, histórico completo de runs. Acessível via Central IA → "Abrir Training Studio". (Feb/2026)
12. **Conexões / Integrações (Card unificado)** — Em Configurações, lista todas as 8 integrações externas (Atlaz, SmartOLT, Twilio, Meta WhatsApp, OpenRouter, Resend, Stripe, Google Drive) com chaves mascaradas e modal de edição. Cobre auditoria de troca de credenciais. (Feb/2026)
13. **Financeiro (Fase 1-4)** — Módulo financeiro completo (interno + clientes). Sub-abas: Categoria, Fornecedor, Método de Cobrança, Caixa (cadastros base), Contas a Pagar (com ação "Pagar" que gera movimentação automaticamente), Fluxo de Caixa (gráfico Recharts + lançamentos manuais), Recebimentos (sync com Atlaz V2: cobranças/boletos/pagamentos dos assinantes via endpoints /listacobrancas, /listaboletos, /listapagamentos com fallback gracioso). Nova role `financeiro`. (Feb/2026)
14. **Disparo em Massa WhatsApp** — Campanhas via Meta Cloud API ou Twilio, modo template HSM ou texto livre com variáveis `{{var}}`, upload CSV, preview, throttle configurável (default 60 msgs/min), agendamento, pause/resume, status por destinatário (queued/sending/sent/failed). Worker assíncrono em background. Suporta volumes >10k contatos. (Feb/2026)
15. **Ligo IA consulta faturas** — 2 tools novas (`consult_subscriber_invoices`, `next_due_invoice`) permitem que a Secretária IA responda automaticamente perguntas como "quanto eu devo", "2ª via", "qual minha próxima fatura" usando os dados sincronizados do Atlaz. Reconhece CPF/CNPJ com ou sem máscara. (Feb/2026)
16. **Analytics financeiro + Rate Limiting** — (a) Gráfico em linha comparando Recebimentos vs Despesas com 7 ranges (1d/7d/30d/3m/6m/1y/5y) e 3 agrupamentos (dia/mês/ano), métricas de regularidade via CV%. (b) Rate limiting global via slowapi protegendo brute force no login (5 tentativas/min) e endpoints sensíveis. (Feb/2026)


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

✅ **Sync inversa Rede IA → SmartOLT (Zones) — VALIDADO E2E** (15/02/2026 — iter68):
- **Objetivo**: ao aprovar uma CTO no painel Rede IA, criar automaticamente a Zone correspondente no SmartOLT (sync bi-direcional — antes era só leitura).
- **Backend** (`/app/backend/services/smartolt_zones.py`): função `ensure_zone_exists(company_id, zone_name, actor)` idempotente com cache de 60s (`_ZONES_CACHE`), normalização case-insensitive (`_normalize_zone`), audit log em `db.smartolt_zone_audit`. Trata 409/race-condition e erros HTTP/rede sem propagar exceção.
- **Wire na aprovação** (`/app/backend/routes/rede_ia.py` linha 537): `_sync_cto_zone_to_smartolt` chamado em `validate_cto` action=approve, NÃO bloqueante (erro de SmartOLT não falha a aprovação — devolve `smartolt_zone: {ok:false, error:...}` na resposta).
- **Endpoint manual** `POST /api/rede-ia/ctos/{cto_id}/sync-smartolt-zone` para reprocessar se SmartOLT estava offline no momento da aprovação.
- **Endpoints auxiliares**: `GET /smartolt/zones` (lista com cache), `GET /smartolt/zone-audit` (últimas 50 ações).
- **API SmartOLT é append-only**: não há PUT/DELETE de zones na coleção oficial. `ensure_zone_exists` resolve isso checando antes de adicionar.
- **Validação E2E** contra SmartOLT real (co-demo já tinha credenciais válidas):
  - Test 1: list zones → 200, 28 zones (inclui "CTO 001_301_TST" criada na sessão anterior) ✓
  - Test 2: audit log → entries com action/zone_name/result ✓
  - Test 3: force-sync CTO inexistente → 404 ✓
  - Test 4: force-sync CTO pendente → 409 "apenas aprovadas sincronizam zone" ✓
  - Test 5: **approve CTO pendente E2E** → status=approved + PDF para Drive + zone "CTO 001_3921_PB3" criada no SmartOLT (`created: true`, `smartolt_response.status: true`) ✓
  - Test 6: re-sync da mesma CTO → idempotente (`created: false`, "já existe") ✓
  - Test 7: audit cresceu para 5 entries com timestamps corretos ✓
- **Pytest** `/app/backend/tests/test_iter68_smartolt_zone_sync.py`: 6/6 passou (test_1_list_zones, test_2_zone_audit, test_3_force_sync_unknown_cto_returns_404, test_4_force_sync_pending_cto_returns_409, test_5_force_sync_approved_is_idempotent, test_6_audit_records_force_sync).

✅ **Fix Bolha 'horario' bloqueada mesmo com lousa liberada** (15/02/2026 — iter69):
- **Bug reportado pelo usuário** (screenshot WhatsApp 10:48): técnico VANDO PATROCINIO (Atlaz, `clock_in_enabled=false`) tinha apenas 1 bolha `priority="horario"` agendada 17:57. Lousa exibia `🔓 lousa liberada` mas a bolha vinha com cadeado 🔒 e clique desabilitado — técnico não conseguia abrir a nota.
- **Causa raiz**: `_lousa_for_collaborator()` (linha 790, `routes/lousa.py`) misturava DOIS conceitos no mesmo campo `t["locked"]`:
  - Lock de reordenação (posicional — `compute_locked_positions` adiciona ao set todas bolhas `horario`/`prioridade` + a anterior a `horario`).
  - Lock de execução (clock state — não bateu Entrada, em intervalo, dia encerrado).
  - O frontend (`LousaMobile.js` linha 483) usava `disabled={ticket.locked}` para desabilitar o clique, então qualquer bolha `horario` solo (`i=0`) ficava permanentemente impossível de abrir.
- **Fix backend** (`/app/backend/routes/lousa.py` linha 790): separou em DOIS campos:
  - `t["locked"]` = somente `is_blocked_by_clock` (não pode abrir).
  - `t["reorder_locked"]` = `i in locked_idx` (informacional, usado pela UI de reordenação).
- **Fix frontend** (`/app/frontend/src/LousaMobile.js` linha 48): `isLockedTicket()` passou a considerar `t.reorder_locked` também, mantendo a UI de reordenação alinhada com a regra do backend.
- **Validação E2E**: 
  - Curl `/api/lousa/by-collaborator/col-b4db2145` → bolha `tkt-5a6979e047` agora retorna `locked=False reorder_locked=True` ✓
  - Screenshot Playwright: bolha sem cadeado, `disabled=None`, clique habilitado ✓
- **Impacto**: 0 regressão — endpoint `public_open_ticket` não validava `compute_locked_positions`, então a abertura sempre foi permitida no backend. O bug era puramente frontend → backend campo errado.

✅ **Fix · Bolhas IA agrupadas no chat (parágrafos viravam 1 mensagem só)** (15/02/2026 — iter70):
- **Bug reportado pelo usuário**: "AS BOLHAS DA CONVERSAÇÃO NO CHAT NÃO ESTÃO SEPARADAS, ESTÃO SENDO AGRUPADAS MESMO QUANDO O PROMPT MANDA ESTAR SEPARADA". A IA gerava resposta com 2-3 parágrafos separados por `\n\n` (como pedido no prompt) mas o backend enviava tudo como UMA mensagem no sidecar Baileys → cliente recebia 1 muralhão de texto no WhatsApp.
- **Causa raiz**: `_maybe_auto_reply` em `routes/whatsapp_baileys.py` (linha 1118-1156) fazia 1 chamada `POST /send` com `text=reply_text` inteiro e persistia 1 linha em `aihub_wa_messages`. Não havia quebra.
- **Fix backend**:
  - Novo helper `_split_ai_reply(text, max_chunks=6, min_chunk_chars=12)` em `whatsapp_baileys.py` que (1) separa por `\n\n` ou marcador `---`, (2) junta micros < 12 chars com o próximo, (3) cap em 6 chunks (overflow → último chunk), (4) preserva `\n` simples dentro de bullets/listas.
  - Loop em `_maybe_auto_reply` envia cada chunk via `/send` com delay de 600ms entre eles (cadência humana) e persiste cada bolha como linha separada em `aihub_wa_messages` com `chunk_index`/`chunk_total`.
  - `delivery_status` por chunk individual — bolha que falha não derruba as outras.
- **Pytest** `/app/backend/tests/test_iter70_ai_reply_split.py`: 8/8 PASS cobrindo parágrafos múltiplos, texto único, bullets, cap de overflow, separador `---`, merge de micro, vazios, newlines simples preservados.
- **Validado E2E real**: trigger `POST /api/whatsapp-baileys/inbound` com mensagem do cliente "quero saber 3 coisas..." → Isabella gerou resposta em 3 parágrafos `\n\n` → backend quebrou em 3 chunks (`chunk_index 0/3, 1/3, 2/3`) → 3 bolhas separadas no DB com `delivery_status: sent` ✓.

✅ **Wallpaper estilo WhatsApp no Atendimento IA + mascote oval no empty state** (15/02/2026 — iter71):
- **Pedido do usuário** (com screenshot): "MUDE AS CORES E O PAPEL DE PAREDE PARA OS DA IMAGEM ENVIADA" — fundo bege-creme clássico do WhatsApp Web com doodles (câmera, fone, coração, foguete, balão, presente, bicicleta etc.) e oval branca centralizada com mini-mascote astronauta.
- **Implementação**:
  - Novo componente `/app/frontend/src/WaWallpaper.js` (~140 linhas) com tile SVG 300×300 contendo 28 doodles em stroke `#d9d2c8` sobre fundo `#efeae2`, embedado como `data-URL` (zero request HTTP).
  - Sub-componente `Mascot` desenha um astronauta roxo com visor cyan segurando celular — inline SVG.
  - Modo `<WaWallpaper empty />` exibe a oval branca centralizada com sombra suave e mascote dentro.
  - testids: `wa-wallpaper`, `wa-empty-mascot`.
- **Wiring em `WhatsAppChatLayout.js`** (2 pontos):
  - Empty state do `ChatThread` (quando não há conversa selecionada): substituído o ícone `MessageSquare` cinza pela `<WaWallpaper empty />`.
  - Background da área de mensagens (`wa-messages-scroll`): substituído `radial-gradient` cinza por tile SVG inline com mesmos doodles e cor `#efeae2`.
- **Validado**: screenshot Playwright em 1920×900 confirma wallpaper bege com doodles repetindo + mascote roxo no oval branco ao centro, idêntico à referência do usuário. `data-testid="wa-wallpaper"` presente, `data-testid="wa-empty-mascot"` presente.

✅ **Botão "Atender" 1-clique nas conv rows + chips de atendente estilo Woluy/FocusChat** (15/02/2026 — iter72):
- **Pedido do usuário** (com vídeo): cada card de conversa precisa ter botão azul "Atender" (ou chip com nome do atendente atribuído) no canto inferior — formato idêntico ao mostrado no vídeo Woluy/FocusChat.
- **Implementação** (`WhatsAppChatLayout.js`):
  - `ConvRow` ganhou 2 props: `authUser` e `onAssignSelf(phone)`.
  - 3 estados visuais no canto inferior-esquerdo de cada card:
    - **Botão azul "Atender"** (gradient `#2f80ed → #1d6cd8`, hover sobe 1px) quando a conversa está com IA ou sem atendente. `data-testid="wa-conv-attender-{phone}"`. `onClick` chama `stopPropagation` + `onAssignSelf`.
    - **Chip azul com nome do atendente** quando outro humano já assumiu. `data-testid="wa-conv-attendant-{phone}"`.
    - **Chip verde "Você está atendendo"** quando o usuário logado é o assignee. `data-testid="wa-conv-mine-{phone}"`.
  - Removida a antiga pílula `assignee_name` que ficava na linha 3 (substituída pelos novos chips abaixo).
  - Wiring em `WhatsAppChatLayout`: `ConversationList` recebe `authUser` + `onAssignSelf`; callback chama `PUT /api/whatsapp-baileys/conversations/{phone}/assign` com `assignee_user_id=authUser.id, assignee_role="human"`, seleciona conv e recarrega.
- **Validado E2E** (Playwright): renderizou **20 botões "Atender"** em conversas com IA ativa; clique disparou PUT → conversa migrou de "Automático" pro bucket "Manual" e chip "Administrador" apareceu no header da thread. Cleanup via curl devolveu pra IA.

✅ **Sidebar accordion · conversas DENTRO de cada bucket** (15/02/2026 — iter73):
- **Pedido do usuário** (vídeo Woluy): "OS CLIENTES FICAM DENTRO DE MENUS E QUANDO VC CLICA NO MENU OS CLIENTES APARECEM TORANANDO MUITO MAIS EXUTO O MENU". Migrou de 3 colunas para **2 colunas** (sidebar accordion + thread).
- **Implementação**: `gridTemplateColumns: "320px 1fr"` (era `220px 360px 1fr`). `ConversationList` removida do JSX (componente preservado como dead code). `BucketSidebar` reescrita com busca global no topo + accordion vertical onde cada bucket, ao estar ativo, renderiza as conversas filtradas nested com border-left tingido na cor do bucket. Chevron rotaciona ⌄ → ⌃ em 180ms. Reutiliza `ConvRow` com todos os recursos (botão Atender, chips, badges).
- **testids**: `wa-bucket-content-{id}`.
- **Validado E2E** (Playwright 1920×900): default abre Automático com 20 convs nested; demais fechados; clique em Aguardando recolhe Automático e expande Aguardando com empty state "Sem conversas em Aguardando". Visual idêntico ao vídeo.

✅ **Módulo Comercial · Orçamento_IA** (15/02/2026 — iter74):
- **Pedido do usuário**: aba "Orçamento" com IA que recebe lista de itens, busca 3 preços, escolhe a média, calcula com %ganho/%imposto/%mão-de-obra (opcional editar), gera romaneio imprimível.
- **Escolhas**: 1b (upload CSV) · 2c (Claude estima sem web search) · 3a (PDF imprimível) · 4c (menu novo "Comercial") · 5a (admin+gestor+financeiro).
- **Backend** (`/app/backend/routes/budget.py` · 350 linhas + `/app/backend/services/budget_pdf.py`):
  - `POST /api/budget` — cria orçamento (name + description, default margin 25%).
  - `POST /api/budget/{id}/upload-csv` — parseia CSV (separador `;` ou `,`, UTF-8/Latin-1, colunas item·qtde·unidade·especificacao com variações de nome aceitas).
  - `POST /api/budget/{id}/analyze` — **Orçamento_IA** = Claude Sonnet 4.5 via Emergent LLM Key, retorna JSON `{items:[{id,low,mid,high,sources,confidence}]}`. Calcula `avg_price = (low+mid+high)/3` e persiste. Tempo médio: 5s para 5 itens.
  - `PUT /api/budget/{id}` — edita name/desc/margin_pct/tax_pct/labor_pct + array de items (suporta `manual_override` por item).
  - `GET /api/budget` — lista; `GET /api/budget/{id}` — detalhe; `DELETE` — exclui.
  - `GET /api/budget/kpis` — KPIs: total, draft/analyzed/final, avg_margin_pct, total_value, avg_value.
  - `GET /api/budget/{id}/pdf` — romaneio ReportLab A4 retrato com tabela de itens (Item·Qtde·Unid·Preço·Subtotal·Fonte+conf), totais (Base·Ganho·Mão-de-obra·Subtotal·Imposto·**Total Final**), rodapé com nota da IA + assinaturas. Marca status="final" na primeira geração.
  - `require_role("administrador","gestor","financeiro")` — `colaborador` recebe 403.
- **Frontend** (`/app/frontend/src/BudgetPanel.js` · 450 linhas):
  - Painel principal: 4 KPI cards no topo (Orçamentos, Valor total, Margem média, Finalizados/Conversão) + busca + lista de orçamentos (cada linha mostra nome, status, itens, margem, total final, botão excluir).
  - Botão "Novo orçamento" → modal de criação (nome + descrição) → abre drawer.
  - Drawer (960px, fixed direita): toolbar com "Subir CSV", "Analisar com Orçamento_IA" (roxo, disabled se sem itens), "Imprimir PDF" (disabled até ter preços). Tabela editável com 6 colunas (Item, Qtde, Unid, Preços IA B/M/A, Unit. usado com input override, Subtotal). Footer sticky com 3 sliders (%Ganho/%Mão-de-obra/%Imposto) + resumo em tempo real (Base → Total Final destacado).
  - Sliders usam debounce via `onMouseUp` para não saturar o backend.
  - PDF abre via `fetch + blob` (preserva header Authorization Bearer) em nova aba.
- **Wiring** (`App.js`): novo grupo "Comercial" no `NAV_GROUPS` com item "Orçamento" (icon `Calculator`, roles admin/gestor/financeiro), rota `view === "budget"`.
- **Endpoints API client** (`api.js`): `budgetList`, `budgetKpis`, `budgetCreate`, `budgetGet`, `budgetUpdate`, `budgetDelete`, `budgetUploadCsv` (FormData), `budgetAnalyze` (timeout 90s), `budgetPdfUrl`.
- **Pytest** `/app/backend/tests/test_iter74_budget.py`: 6/6 PASS — cria draft, CSV parser, percentuais recalculam, override manual recalcula (base = 2×100 + 100×100 = 10200), KPIs, PDF retorna bytes `%PDF-...`. 1 skip (colaborador 403, sem conta de teste no ambiente).
- **Validado E2E** (Playwright 1920×900): menu "Comercial > Orçamento" aparece; painel renderiza KPIs (1 orçamento · R$ 1.018,18 · 30% · 100% conversão); orçamento "Obra CTO-Centro · Finalizado" aparece com 5 itens; drawer abre com tabela completa mostrando preços IA (Mercado Livre·Furukawa·FiberHome·Intelbras), inputs override, e footer com totais (Base R$ 656,25 → Total Final R$ 1.018,18 com sliders %Ganho 30 · %Mão-de-obra 15 · %Imposto 7).

## Iter88 (16/05/2026) — CENTRAL_ONT · sub-aba completa + bloqueio de fechamento com sinal ruim + autorização do gestor + SN mismatch
**4 features integradas:**

1) **Sub-aba 🛰️ CENTRAL_ONT no Chamados** (`/app/frontend/src/lousa/CentralOntPanel.js`):
   - Toggle (data-testid `central-ont-block-toggle`) **"Bloquear fechamento com sinal ruim"** + input do threshold (default -27 dBm).
   - **4 KPIs**: Total fechado, Sinal ruim, % geral, Limite.
   - **Sub-abas internas**: "Por técnico" (tabela com Total / Sinal ruim / % + barra colorida verde<10%, amarelo<20%, vermelho≥20%) e "Notas com sinal ruim" (lista com cliente/endereço/ONT/sinal/data, badge "AUTORIZADO" quando bate).
   - **Solicitações de autorização pendentes** inline (Aprovar/Rejeitar) com poll de 8s.

2) **Backend** (`/app/backend/routes/lousa.py`):
   - `GET/PUT /api/lousa/central-ont/settings` (admin/gestor) — coleção `central_ont_settings`.
   - `GET /api/lousa/central-ont/report?days=N` — agregação completa (total, bad, ratio por técnico, items).
   - `GET/POST /api/lousa/central-ont/auth-requests[/{id}/{approve|reject}]` (admin/gestor) — fluxo de autorização.
   - `GET /api/lousa/public/bad-signal-auth/{id}` — polling sem auth para o técnico.
   - `public_finalize_ticket` reforçado:
     - Se sinal < threshold AND block ON AND sem `bad_signal_auth_id` → **403** `{code: needs_bad_signal_auth, request_id, threshold, sinal}` + cria pending request + notification 'bad_signal_auth_request' (severity=warning).
     - Se sinal < threshold → notification 'bad_signal_close' criada (sempre, mesmo com block OFF — auditoria passiva).
     - **SN mismatch**: compara `cd.ont` com `live_signal.sn` (best-effort; case-insensitive, ignora `:`); persiste em `ticket.central_ont.sn_mismatch`.
   - Coleção `bad_signal_auth_requests`: TTL 30min, status pending/approved/rejected/used/expired.

3) **App do colaborador (LousaMobile)**:
   - Avisos inline amarelos no formulário de finalização: `finalize-bad-signal-warning` (quando `sinal < threshold` — threshold puxado de `/central-ont/settings`) e `finalize-sn-mismatch-warning` (quando ONT digitado ≠ SN da SmartOLT).
   - `handleFinalize` intercepta 403 `needs_bad_signal_auth` → abre `BadSignalAuthWaitModal` com spinner pulsante "⏳ Aguardando autorização" e **poll a cada 4s** em `/lousa/public/bad-signal-auth/{id}` — quando vira `approved`, refaz o finalize automaticamente passando `bad_signal_auth_id`.

4) **LousaAdminPanel**: 2 sub-tabs (Quadro / CENTRAL_ONT) — preserva o quadro existente.

**Testes:** `tests/test_iter88_central_ont.py` (**8/8 pass**) — flow E2E completo: block ON → 403 → approve → retry → ticket.central_ont.auth_used setado · block OFF + sinal ruim → 200 + notification passiva · reject → status=rejected, retry bloqueado · public polling sem auth funciona. Frontend UI confirmada via Playwright pelo testing agent.

## Iter87 (16/05/2026) — App do colaborador: PPPoE click-to-copy + bloco SmartOLT no card da bolha
**Pedido:** clicar no PPPoE "copia automaticamente" + as informações `PORTA OLT / VLAN / CTO / PORTA CTO / SN` devem ser puxadas da SmartOLT (hoje mostravam "smartolt" como placeholder).

**Backend** (`/app/backend/routes/smartolt.py`):
- `_live_signal_summary()` agora retorna `olt_port` ("board/port"), `board`, `port`, `onu`, `sn`, `cto_box` (parseado de `zone_name` — primeiros N-1 segmentos), `cto_port` (último segmento), e `vlan` (busca em `service_ports[*].vlan/cvlan/svlan`).
- `_do_sync()` agora persiste `service_ports` no documento de cada ONU em `smartolt_onus` (antes só salvava signal/board/port). Aplicado retroativamente: 1753/1754 ONUs já com `service_ports` na próxima sync agendada (ou via `POST /api/smartolt/sync-onus`).
- Validação real: ROSANE → `olt_port=1/5, vlan=1005, cto_box=CTO, cto_port=01, sn=FHTTC07CE30B, rx=-24.09 dBm`.

**Frontend** (`/app/frontend/src/LousaMobile.js`):
- Novo componente `<PppoeChip>` — botão arredondado, clique copia o PPPoE pro clipboard (fallback `execCommand` em http) com **flash verde "✓ Copiado!" por 1.4s**. Testid `lousa-pppoe-copy`.
- Novo componente `<SmartOltDetailBlock>` — grid responsivo (cards de 85px) em background azul-claro com 5 chips: PORTA OLT (+ ONU #), VLAN, CTO, PORTA CTO, SN (mono). Só renderiza items com valor (omite os vazios). Testid `lousa-smartolt-block`.
- Card da bolha agora exibe o bloco SmartOLT logo abaixo do pill de sinal/dBm.

**Testes:** `tests/test_iter87_live_signal_extended.py` (5/5 pass — parse de olt_port/cto/vlan, campos ausentes não quebram, zone_name com 1 segmento, prioridade vlan>cvlan>svlan, thresholds de qualidade good/warn/bad).

## Iter86 (16/05/2026) — App do colaborador: pull-to-refresh nativo
**Feature:** Arrastar a tela pra baixo no topo atualiza os dados do app sem sair da página (UX padrão de PWA).

**Implementação** (`/app/frontend/src/CollaboratorApp.js`):
- Novo hook `usePullToRefresh(onRefresh, {enabled, threshold=70})` — detecta `touchstart/touchmove/touchend` no `window`, só ativa quando `scrollY === 0`, com damping de 50% no arraste e `preventDefault` no move (passive:false) pra não deixar o browser interceptar.
- Novo componente `<PullIndicator>` — círculo branco com spinner rotativo (cinza enquanto puxa, azul quando passa do threshold e durante o refresh), `position:fixed` no topo, `pointer-events:none`, com keyframe `ptr-spin`.
- `document.body.overscroll-behavior-y = "contain"` quando mobile=true — **bloqueia o pull-to-refresh nativo do browser** (causa do "sair da tela" / recarregar a tab inteira).
- Wire-up: `ptr = usePullToRefresh(doRefresh, { enabled: mobile && !!collabId })` — só ativo no modo celular com técnico já carregado. Renderizado no topo de `<Wrapper>`.

**Validado em produção** (viewport 430×900): `overscroll-behavior-y=contain` aplicado, indicador `pull-refresh-indicator` aparece no arraste, `doRefresh()` dispara ao soltar passando do threshold.

## Iter85 (16/05/2026) — App do colaborador: bypass admin sem link único
**Bug fix:** Quando o admin/auditor abria o app do colaborador sem `?cid=` na URL, a tela "Acesso pelo link próprio" bloqueava completamente — obrigando o admin a copiar o link do técnico. O usuário pediu que essa tela ofereça uma forma do admin entrar sem precisar do link.

**Arquivo:** `/app/frontend/src/CollaboratorApp.js` linhas 400-480.

**Mudança:** Na tela "Acesso pelo link próprio", se `isAdminTest === true` (JWT do `ponto_token` com role administrador/auditor), renderiza um painel vermelho **🔓 "Modo administrador — acesso sem link"** com:
- `<select data-testid="admin-collab-select">` listando todos os colaboradores cadastrados (nome + role).
- Ao selecionar, faz `setCollabId(value)` e a Lousa do técnico abre imediatamente sem link único.
- Aviso: "⚠ Apenas para suporte/admin. Ações continuam sendo registradas em seu nome de admin no log."

A tela para técnicos não-admin permanece IDÊNTICA (não vaza acesso). Validado em produção: dropdown com 8 colaboradores reais aparece corretamente.

## Iter84 (16/05/2026) — Botão vermelho "Liberar bolha presa" no Chamados
**Feature entregue:** botão de emergência no painel Chamados (`LousaAdminPanel`) que permite a admins/gestores **liberarem manualmente uma bolha de serviço presa** quando o técnico não consegue finalizar (app travado, perdeu sinal, etc).

**Backend** (`/app/backend/routes/lousa.py`):
- `GET /api/lousa/admin/stuck-tickets` — lista colaboradores que TÊM bolha em status `aberta` agora. Retorna 1 entrada por colab (a mais antiga aberta), com `minutes_stuck` calculado em tempo real.
- `POST /api/lousa/admin/release-stuck` — body `{collaborator_id, reason?}`:
  - Encontra a bolha mais antiga `aberta` do colaborador (sort opened_at:1)
  - 404 se não houver
  - Reset → `status="pendente"`, `$unset opened_at, whatsapp_status, whatsapp_last_message`
  - **Log de auditoria** `action="liberada_admin"` com `actor_id`, `actor_name`, role, detalhes (técnico + cliente + motivo)
  - **Notification crítica** `type="bolha_liberada_admin"`, severity=`critical`, mensagem com quem fez e contra quem (pra outros admins verem no painel/SSE)
  - Retorna `{ok, freed_ticket, collaborator_id, collaborator_name}`
  - **1 bolha por chamada** — se houver outra presa do mesmo colab, é necessário repetir.

**Frontend:**
- `/app/frontend/src/lousa/ReleaseStuckBubbleModal.js` (NEW) — modal compacto:
  - Bloco de aviso laranja: "ação registrada nos logs · notificação a todos os admins · libera apenas 1"
  - Lista de bolhas presas (1 botão-card por colab) com badge de tempo presa (laranja <60min, vermelho ≥60min)
  - Input "motivo" opcional
  - Confirmação inline com 2 etapas (botão vermelho → caixa vermelha com SIM/NÃO)
- `LousaAdminPanel.js` — novo botão vermelho `🚨 Liberar bolha` (data-testid `lousa-release-stuck-btn`) entre Histórico e Alertas.

**Validação em produção:** 2 bolhas presas reais encontradas no demo (`DIOGO` há 3d 7h e `VANDO` há 35min). Screenshot confirma badge vermelho/laranja por tempo presa.

**Testes:** `/app/backend/tests/test_iter84_release_stuck.py` (4/4 pass — flow completo com auditoria + notification, 404 sem bolha, escolhe mais antiga quando múltiplas, listagem). Frontend testids: `lousa-release-stuck-btn`, `release-stuck-modal`, `stuck-coll-{id}`, `stuck-reason-input`, `stuck-trigger-confirm`, `stuck-confirm-btn`, `stuck-cancel-btn`.

## Iter83 (16/05/2026) — Canal Baileys no Disparo IA + Scheduler diário + Badge de pendentes
**Features entregues:**

1) **Canal Baileys (WhatsApp Web) como opção de disparo**:
   - `routes/mass_messaging.py`: regex aceita `baileys` em `CampaignCreate.channel`. Novo helper `_send_baileys(camp, rec, text)` que faz POST para o sidecar (`http://127.0.0.1:3002/send`) e persiste a outbound em `aihub_wa_messages` (com `channel=baileys`, `actor_user=disparo_ia`, `campaign_id`, `campaign_origin`).
   - `routes/disparo_ia.py`: `ApproveIn.channel` regex aceita `baileys`.
   - `DisparoIaPanel.js`: select `disparo-channel-select` agora oferece 3 opções (Baileys = default, Meta Cloud, Twilio).

2) **Scheduler diário automático do Disparo IA**:
   - `server.py`: novo APScheduler cron `disparo_ia_daily` às **06:30** (30min após o Alvaro fechar o relatório diário às 06:00). Roda `generate_campaign_suggestions(cid)` para cada company da base. Log `[disparo_ia] daily run company=… gerou N sugestões`.

3) **Badge de sugestões pendentes**:
   - Novo endpoint `GET /api/disparo-ia/pending-count` → `{pending, latest_run_id, latest_created_at}`.
   - Aba "Disparo IA" em `MassMessagingPanel.js` exibe badge roxo `disparo-pending-badge` com o número de pendentes (poll a cada 30s).

**Testes:** `tests/test_iter83_baileys_scheduler.py` **6/6 pass** — Pydantic accept baileys (ApproveIn + CampaignCreate), `_send_baileys` POST sidecar + persiste histórico (com mock httpx), `_send_baileys` retorna erro em falha do sidecar, pending-count endpoint shape, scheduler job registrado em server.py. Frontend validado via screenshot: badge=5, modal completo com canal Baileys default.

## Iter82 (16/05/2026) — Disparo IA · briefing injetado na Isabella (ciclo das 3 IAs fechado)
**Feature entregue:** quando um cliente que recebeu uma campanha Disparo IA responde no WhatsApp, a Isabella IA recebe automaticamente o briefing específico daquela campanha como contexto extra no system_prompt — fechando o ciclo Alvaro → Disparo → Isabella.

**Arquivos:**
- **Novo serviço:** `/app/backend/services/disparo_briefing.py` — `fetch_disparo_briefing_for_phone(cid, phone)` busca a campanha Disparo IA mais recente (janela 14d, status sent/delivered) e formata o bloco com: tipo da campanha, mensagem enviada, briefing literal, instrução de "siga prioritariamente".
- **Wire-up:** `/app/backend/routes/whatsapp_baileys.py` em `_maybe_auto_reply` (3f, após o orchestrator) — adiciona o bloco ao array `extra` que vai pro system_prompt da Isabella. Best-effort: log "[wa-baileys] disparo_ia briefing injetado p/ phone=…" quando acionado.

**Validação E2E em produção:**
- Seed: campanha plan_upsell com briefing "🚀 Tom CONSULTIVO. Cliente está no Fibra 300, ofereça 600 e 1Gb. Escale humano se citar concorrente."
- Inbound real: phone do recipient mandou "oi tudo bem? vi a mensagem do upgrade".
- Log confirmou injection.
- Isabella respondeu: *"Oi! Tudo ótimo, obrigada! 😊 Que bom que viu a mensagem! Estou aqui para te ajudar com o upgrade. Para te oferecer as m..."* — tom alinhado ao briefing.

**Testes:** `/app/backend/tests/test_iter82_disparo_briefing.py` (4/4 pass — injeção quando há campanha recente, skip phone desconhecido, skip campanha sem origin=disparo_ia, skip campanha >14d).

## Iter81 (16/05/2026) — Disparo IA · Estrategista comercial autônomo
**Feature entregue:** Novo módulo "Disparo IA" dentro de Disparo em Massa — IA estrategista que orquestra Alvaro (insights) + Isabella (execução WhatsApp) para gerar campanhas ativas.

**Decisões do usuário:** Claude Sonnet 4.5 · pacote completo de 10 KPIs · todos os 6 tipos de campanha · aprovação humana SEMPRE · reaproveita sistema mass_messaging.

**Backend (`/app/backend/services/disparo_ai.py` + `/app/backend/routes/disparo_ia.py`):**
- `DISPARO_SYSTEM_PROMPT`: prompt-mãe baseado em best-practices outbound 2026 (Outreach/Apollo/AISensy/Zenvia). KPIs alvo: delivery≥95%, read≥70%, reply 15-35%, positive_reply≥8%, block<1%.
- `generate_campaign_suggestions(cid)`: lê último relatório Alvaro + base CRM + histórico recente de tipos → Claude responde com até 6 sugestões (1 por tipo). Persiste em `disparo_suggestions`.
- `_resolve_audience(cid, filters)`: combina filtros do Alvaro (risco_cancelamento, since_days) + filtros estruturais (plan_contains, bairro_in, status) e retorna size + 5 phones preview.
- `compute_kpis(cid, days)`: agrega métricas reais das `mass_campaigns` com origin=disparo_ia, classifica replies (positive/negative/neutral via regex), conta save_signals/upsell_signals/blocks por tipo.
- Endpoints (admin/gestor): `GET /api/disparo-ia/types`, `POST /generate-suggestions`, `GET /suggestions[?status=&type=]`, `GET /suggestions/{id}`, `POST /suggestions/{id}/approve` (cria mass_campaign + recipients), `POST /suggestions/{id}/reject`, `GET /kpis?days=30`, `GET /campaigns`.
- `mass_campaigns` ganhou flags: `origin: "disparo_ia"`, `disparo_type`, `disparo_suggestion_id`, `disparo_run_id`, `isabella_briefing`, `expected_kpis`, `approval_notes`.
- `motor_ia.AGENT_CATALOG`: registrados `alvaro_ai` e `disparo_ia` para o painel kill-switch.

**Frontend (`/app/frontend/src/DisparoIaPanel.js`):**
- Painel renderizado como 2ª aba de Disparo em Massa (`mass-tab-disparo_ia`).
- **KPI Dashboard** (10 cards): Campanhas (30d), Enviadas, Delivery, Read rate, Reply rate, Positive reply, Save (churn), Upsell sinalizado, Block rate, Cost/conv.
- Botão "Gerar sugestões" roxo (Claude Sonnet 4.5).
- Filtros: Pendentes / Aprovadas / Rejeitadas / Todas.
- Lista de sugestões com icon+badge por tipo (Churn/Upsell/Cobrança/NPS/Expansão/Reativação), título, rationale e tamanho da audiência.
- Modal de detalhe: rationale, audiência preview, mensagem editável, **briefing pra Isabella** editável, KPIs alvo, janela de envio, cadência, parâmetros de envio (canal/throttle/notas), botões **Aprovar** (verde) e **Rejeitar** (vermelho).

**LLM validado em produção:** primeira execução gerou 2 sugestões reais (NPS+Upsell) com rationale baseado em dados reais do Alvaro (run alv-run-3ad22ea0, média 6.88), briefing diferenciado pra Isabella, KPIs alvo e janela de envio justificadas.

**Testes:** `/app/backend/tests/test_iter81_disparo_ia.py` (9/9 pass — types, kpis, ACL, list, generate-validation, approve full e2e com shape de mass_campaigns + recipients, reject, 404 detail). Frontend testids confirmados: `mass-tab-manual`, `mass-tab-disparo_ia`, `disparo-ia-panel`, `disparo-generate-btn`, `disparo-kpi-dashboard`, `disparo-filter-*`, `disparo-sug-{id}`, `disparo-sug-modal`, `disparo-msg-edit`, `disparo-briefing-edit`, `disparo-approve-btn`, `disparo-reject-btn`.

## Próximas (P2)
- Rate limiting global via `slowapi` (P1)
- TTL/rotação do token webhook Secretária IA (P2)
- Botão "Sync Atlaz" na aba Assinantes para puxar clientes ativos (P2)
- Refatorar `routes/lousa.py` (>2500 linhas), `routes/whatsapp_baileys.py` (>2585 linhas) e `WhatsAppChatLayout.js` (>4100 linhas) (P3)
- Conflict Resolution UI para Assinantes (quando phone bate em múltiplas subs) (P3)
- Melhorar matching Atlaz↔SmartOLT para chegar próximo de 100%
- Tema dark: revisar painéis com backgrounds hardcoded
- Aba "Histórico WhatsApp" no perfil do cliente (P2)
- Banco Inter PIX dinâmico (P1) — pausado por pivots anteriores
- Refresh tokens curtos para URLs de mídia (`/audio/{file}?t=`) para reduzir exposição de JWT longo (P2)
- Meta WhatsApp Cloud webhook 403: aguardando App Secret correto do usuário (BLOQUEADO)
- **Disparo IA — evolução futura:**
  - Read receipts reais da Meta Cloud API → `read_rate` ≠ `delivery_rate`
  - Cost-per-conversion (multiplicando channel cost × deliveries)
  - Agendador automático Disparo IA (worker diário gera sugestões sem ação humana)
  - A/B testing automático de variações de mensagem (2 grupos disparados, comparados após N dias)
  - Reply classification mais robusta com LLM (substituir POSITIVE_RE/NEGATIVE_RE por Claude classificando intenção)
  - Briefing dinâmico injetado automaticamente no system prompt da Isabella quando ela recebe replies de campanhas Disparo IA

## Iter78 (16/05/2026) — Filtros Alvaro IA + UX confirmações + ONU detail + Áudio inbound + Typing indicator
**P0 entregue:**
- **Alvaro IA filtra mensagens automáticas** (`/app/backend/services/alvaro_ai.py`):
  - Novo helper `_is_automatic_message` detecta `auto_reply=True` ou `actor in ("ai","bot","system","auto")`.
  - `_build_conversation_text` ignora essas mensagens antes do prompt — economiza tokens.
  - `run_daily_analysis` agora pula conversas que só tiveram bot↔cliente (sem atendente humano e <2 inbounds) — sem insight útil.
- **Modal Sim/Não para finalizar conversa** (já existia em `FinalizeAtendimentoModal` linha 2657 do WhatsAppChatLayout.js — verificado, sem `window.confirm`).
- **ONU detail dentro do modal "ONUs por VLAN"** (`/app/frontend/src/RedeIaPanel.js`):
  - Linhas da tabela viraram clicáveis (hover/cursor).
  - Novo `OnuDetailModal` com sinal vivo + refresh, status, levels 1310/1490, botão **Reiniciar ONU** com `ConfirmRebootModal` (Sim/Não), histórico de ações (smartolt_actions).
  - Novo endpoint `GET /api/smartolt/onu/{external_id}/actions` (em `/app/backend/routes/smartolt.py`).
  - API client: `smartoltOnuActions(extId, limit)`.

**P1 entregue:**
- **Player de áudio inbound** (PTT/voice note do cliente):
  - Sidecar `/app/whatsapp-service/server.js`: importa `downloadMediaMessage` da Baileys, baixa o áudio quando `msg.audioMessage` está presente, envia como base64 ao `/inbound` junto com `audio_mimetype`, `audio_duration_sec`, `audio_is_ptt`.
  - Backend `inbound_webhook`: aceita os novos campos opcionais, salva em `/app/backend/uploads/wa_audio/{msg_id}.{ext}` e cria a mensagem com `media_type="audio"`, `media_url`, `media_duration_sec`, `media_is_ptt`.
  - Frontend: o `InlineAudioPlayer` existente já renderiza qualquer mensagem com `media_type=audio` — funcionou de fábrica em inbound também.
- **"Isabella digitando…" no chat e na lista**:
  - Backend `_maybe_auto_reply`: seta `wa_conversations.ai_typing_until = now + 45s` + `ai_typing_agent` antes da chamada LLM; limpa após o envio (sucesso/falha/empty/exception).
  - Backend `/conversations`: expõe `ai_typing_until` e `ai_typing_agent` em cada conv.
  - Frontend `ChatThread`: tick de 1.5s revalida `aiTyping`; presence label roxo `"{agent} digitando…"` + nova barra animada com 3 bolinhas (testid `wa-ai-typing-bar`) acima do composer; CSS keyframes `wa-typing-dot` + `wa-typing-fade`.
  - Frontend `ConvRow`: quando IA está digitando, substitui o preview de `last_text` por `"{Agent} digitando…"` em itálico roxo.

**Testes:** `/app/backend/tests/test_iter78_alvaro_smartolt_actions.py` (13/13 pass) · `/app/backend/tests/test_iter78_wa_audio_typing.py` (11/11 pass). Frontend testids confirmados visualmente: `onus-by-vlan-modal`, `onu-detail-modal`, `onu-signal-refresh`, `onu-reboot-btn`, `onu-reboot-confirm-modal`, `wa-finalize-modal`, `wa-audio-player`, `wa-ai-typing-bar`.


✅ **Wizard 2-passos no App do Colaborador + OCR de etiqueta ONT** (16/05/2026 — iter89/90):
- **Backend** (`/app/backend/routes/lousa.py` L2105): novo endpoint `POST /api/lousa/public/ocr-sn` que recebe `{image_base64, hint}` e usa **Gemini 2.5 Flash via Emergent LLM Key** (`emergentintegrations.LlmChat` com `ImageContent`) para extrair SN/MAC da etiqueta. Cap 4MB, base64 validado, JSON parse robusto (strip code fences), normaliza MAC para `AA:BB:CC:DD:EE:FF`. Endpoint público (técnico não tem JWT).
- **Backend fix** (`/app/backend/routes/lousa.py` L1180 + L1485): regra antiga exigia ≥3 fotos para `type="instalacao"` (bloqueava o novo wizard que coleta 1 foto obrigatória do equipamento + opcional da etiqueta). Reduzido para **≥1 foto** — o wizard já enforça client-side via `photo-required-modal`.
- **Frontend** (`/app/frontend/src/LousaMobile.js` L723 `TicketDetail`): tela de finalização virou **wizard de 2 passos** com indicador `finalize-steps`:
  - **Etapa 1** — Sinal medido, MAC ONT (com botão `ocr-sn-btn` que tira foto da etiqueta e auto-preenche via OCR Gemini), **Foto do equipamento OBRIGATÓRIA** (`equip-photo-section` + `equip-photo-input`), warnings de bad signal e SN mismatch contra SmartOLT.
  - **Etapa 2** — Insumos **FTTH** (drop/esticador/conector_fast) e **Rede** (cabo_rede/conector_rede) **separados visualmente em cards distintos** (amarelo FTTH · azul Rede), textarea Observações, botões Voltar/Finalizar.
  - Validação: se faltar MAC ou foto do equipamento em instalação/retirada → `photo-required-modal` bloqueia avanço. Form state preserva tudo ao voltar Etapa 2 → Etapa 1.
- **Validação E2E (testing_agent iter90)**: 7/7 pytest (`test_iter89_ocr_sn_and_fotos.py`) + Playwright 100% no fluxo do wizard (Step1 → Modal photo-required → Upload foto → Step2 → Voltar preserva → Step2). Validação manual curl: ticket `tkt-29199e719f` (instalacao) finalizado com sucesso usando apenas 1 foto base64 após o fix do mínimo.



✅ **Sugestão de insumos com IA no Wizard de Finalização** (16/05/2026 — iter91):
- **Backend** novo endpoint `POST /api/lousa/public/suggest-supplies` (`/app/backend/routes/lousa.py` L2202): recebe `{ticket_id?, type, neighborhood?, company_id}` e retorna `{qtd_drop, esticadores, conectores_fast, cabo_rede, conectores_rede, sample_size, source, rationale}` baseado na **mediana das últimas 30 notas finalizadas do mesmo tipo**. Estratégia em cascata: (1) bairro específico → (2) empresa-wide → (3) defaults sãos por tipo (instalacao/troca = 80m drop · suporte = 20m · retirada = 0). Threshold mínimo `sample_size>=3` para usar mediana.
- **Frontend** novo bloco `suggest-supplies-card` (`/app/frontend/src/LousaMobile.js` L1148): card azul tracejado no topo da Etapa 2 com botão "Sugerir" — chama o endpoint e pré-preenche todos os 5 campos de insumos. Vira verde após aplicar mostrando rationale ("Baseado na mediana de N instalações finalizadas em {bairro}"). Botão "Refazer" permite re-sugerir.
- **Validação**: 4/4 pytest (`test_iter91_suggest_supplies.py`) — defaults, retirada zerada, caminho da mediana (drop = 82 entre 70/80/85/90), fallback bairro→empresa.
- testids: `suggest-supplies-card`, `suggest-supplies-btn`.

✅ **Card de Performance do Técnico (gamificação suave)** (16/05/2026 — iter92):
- **Backend** `GET /api/lousa/public/tech-performance/{cid}` (`/app/backend/routes/lousa.py` L2331): retorna `{closed_today, success_rate, avg_minutes, rank, total_techs, streak, badge}`. Agregação MongoDB: notas finalizadas do dia (UTC) por colaborador, ranking entre técnicos da empresa, streak de dias consecutivos com pelo menos 1 fechada (cap 30 dias).
- **Badges motivacionais**: "🏆 Líder do dia" (rank=1 com >1 técnicos) · "💯 100% sucesso" (≥3 fechadas com 100%) · "🔥 N dias seguidos" (streak≥5) · "⚡ Em ritmo forte" (≥5 fechadas) · "Bora começar o dia!" (0 fechadas) · fallback "Bom trabalho!".
- **Frontend** novo componente `PerformanceCard` no topo da Lousa do colaborador (`/app/frontend/src/LousaMobile.js` L704): card colorido por desempenho (azul padrão · ouro pra líder · verde pra 100% · cinza zerado), 4 stats grandes (Fechadas · % sucesso · Tempo médio · Ranking), badge canto direito, pílula 🔥 streak quando ≥2 dias. Auto-refresh a cada 60s.
- **Validado**: 4/4 pytest (`test_iter92_tech_performance.py`) — 404 desconhecido · shape correto · badge "100% sucesso" com 4 fechadas seed · badge "Bora começar" para técnico zerado. Screenshot Playwright: DIOGO renderiza "1 fechada · 100% sucesso · 4min · 1º de 1" em gradient azul.
- testids: `tech-performance-card`, `tech-perf-badge`.

✅ **Mural Público de Ranking (TV no escritório)** (16/05/2026 — iter93):
- **Backend** `GET /api/lousa/public/leaderboard?company_id=co-demo&limit=10`: agrega notas finalizadas do dia agrupadas por técnico, ordenadas por volume desc, hidrata com nome + foto (`avatar_data_url` ou `google_picture`). Retorna `{rank, collaborator_id, name, photo_url, closed_today, success_rate, avg_minutes, badge}` por técnico.
- **Frontend** novo componente fullscreen `LeaderboardMural.js`: rota pública `/mural` e `/leaderboard` (sem auth — para TV/mural). Layout: header **"RANKING DO DIA"** + relógio JetBrains Mono ao vivo, podium 1º/2º/3º com avatares e gradient colorido por posição (ouro/prata/bronze), lista 4º-10º em cards. Auto-refresh 30s. testids `leaderboard-mural`, `mural-podium-1/2/3`, `mural-row-{cid}`, `mural-clock`.
- **Validado**: 4/4 pytest + screenshot Playwright (DIOGO HENRIQUE como 1º · Líder com foto real, 1 fechada, 100% sucesso, 5min/nota).

✅ **Sistema de Conquistas/Medalhas persistentes** (16/05/2026 — iter94):
- **Backend** `GET /api/lousa/public/achievements/{cid}`: catálogo de 10 medalhas calculadas on-the-fly via agregação MongoDB sobre o histórico completo do técnico. Retorna `{medals[], earned_count, total_count, stats}`.
- **Catálogo (10 medalhas)**: 🌱 Primeira nota · 🔟 Dezena · 💯 Centena · 🏅 Mil Mestre · 🔧 Instalador (10) · ⚙️ Instalador Master (100) · 🔥 Streak 7 · 🌋 Streak 30 · 📡 Sinal de Ouro (RX>-22 em 50+ instalações) · ⚡ Veloz (<30min médio em 50+ notas).
- **Frontend** novo `AchievementsCard.js` no LousaMobile (após PerformanceCard): card roxo gradient com barra de progresso dourada e grid expansível de 10 medalhas (earned em gold com glow · bloqueadas em cinza tracejado). Toggle "Recolher/Ver todas".
- **Frontend mural**: PodiumCard exibe até 6 medalhas earned ao lado do nome do top 3 com `+N` para excedentes.
- **Validado**: 4/4 pytest (`test_iter94_achievements.py`) + screenshot. DIOGO HENRIQUE: 1/10 medalhas (Primeira nota brilha em ouro).
- testids: `achievements-card`, `achievements-toggle`, `achievements-grid`, `medal-{id}[-earned]`, `mural-medals-{place}`.

✅ **Modo Boss — chamados urgentes com alerta visual + sonoro + WhatsApp proativo** (16/05/2026 — iter95):
- **Backend** (`/app/backend/routes/lousa.py`): novo valor `urgente` no `Priority` Literal. `PRIORITY_RANK` rebalanceado: `{urgente:-1, prioridade:0, horario:1, normal:2}` — urgentes aparecem PRIMEIRO em todas as queries ordenadas. Ao criar ticket com `priority="urgente"`, função helper `_send_boss_mode_whatsapp` dispara mensagem proativa pro cliente via Baileys (`POST http://localhost:3002/send`) e persiste em `aihub_wa_messages` com `context="boss_mode_urgent_ticket"`. Best-effort: falha do sidecar não derruba o create.
- **Frontend** (`/app/frontend/src/LousaMobile.js`): bolha urgente renderiza com borda VERMELHA 2px, sombra ampliada vermelha, tag "🚨 URGENTE · BOSS" no topo, e animação CSS keyframe `boss-mode-pulse` (1.6s loop). Detector de novos urgentes dispara **beep duplo (Web Audio API: 880Hz → 660Hz, 420ms)** + **vibração (180·90·180·90·280ms)** quando um urgente novo aparece após o primeiro render (evita spam ao abrir o app).
- **Validado**: 3/3 pytest (`test_iter95_boss_mode.py`) — create urgente OK · priority inválido 422 · urgente ranqueia ANTES de horario na lista. Screenshot Playwright: ticket "Boss Test" pulsando em vermelho no topo da Lousa de DIOGO.
- Compatibilidade total com sistema de medalhas, performance e mural existentes (novos rankings respeitam o `PRIORITY_RANK` atualizado).

✅ **Smart Route — otimização TSP greedy (Nearest Neighbor) no App do Técnico** (16/05/2026 — iter96):
- **Backend** `POST /api/lousa/public/optimize-route` (`/app/backend/routes/lousa.py`): recebe `{collaborator_id, current_lat, current_lng, apply}` e retorna `{optimized[{id,name,address,distance_km}], total_km, stops, estimated_minutes, applied}`. Considera apenas tickets do dia com `status` pendente/aguardando + `priority="normal"` + `latitude/longitude` válidos (urgentes/horario têm slot fixo). Algoritmo: distância de Haversine + nearest-neighbor greedy começando da posição atual do técnico. Se `apply=true`, persiste novo `position` em cada ticket.
- **Frontend** novo componente `SmartRouteCard` no LousaMobile (após AchievementsCard): card laranja/ciano com botão "Calcular" → pede `navigator.geolocation` (high accuracy) → mostra preview com lista ordenada (nome · bairro · km · "(próxima)" no 1º). Botão "Aplicar" persiste e refaz a Lousa. Estado disabled quando não há `priority="normal"`. Mostra `reason` quando ok=false.
- **Validado**: 3/3 pytest (`test_iter96_smart_route.py`) — sem candidatos · ordem Haversine correta (Perto antes de Longe) · apply persiste new positions. Screenshot Playwright (DIOGO): card renderiza tanto disabled quanto enabled.
- testids: `smart-route-card`, `smart-route-preview-btn`, `smart-route-apply-btn`, `smart-route-list`, `smart-route-error`.

✅ **GESTÃO E METAS + GESTAO_IA + Gamificação + Geofence Alert + Admin Smart Route** (16/05/2026 — iter97):
**Backend** (`/app/backend/`):
- `routes/lousa.py`:
  - `tech-performance/{cid}` agora retorna `points_today` calculado por tipo (reparo=1pt · retirada=1.5pt · instalação=3pt · troca_endereco=3pt).
  - Medalha **"📦 Retirador"** (10+ retiradas) adicionada ao catálogo (total 11 medalhas).
  - `POST /api/lousa/public/geofence-ping`: recebe lat/lng do técnico, persiste `last_position` no colaborador, e se ele estiver em chamado aberto + fora do raio de 500m por >5min, cria bolha `type="alerta_geofence"` urgente piscando vermelho na coluna do próprio técnico. Dedup via `geofence_state.alert_fired`.
  - `POST /api/lousa/admin/optimize-route` (gestor only): reutiliza Smart Route public, mas pega `last_position` do colaborador automaticamente.
  - `GET/POST /api/lousa/admin/dashboard-config` (gestor): toggles globais `{show_performance, show_achievements, show_smart_route, show_points, enable_geofence_alerts}` com defaults sãos.
  - `GET /api/lousa/public/dashboard-config/{cid}`: público para o app do técnico ler os toggles.
- `services/gestao_ai.py` (NOVO): **GESTAO_IA** com `generate_gestao_report` usando **Claude Sonnet 4.5 via Emergent LLM Key**. System prompt com 15+ KPIs ISP (FTR, TMR, TMA, SLA, retorno, taxa sucesso, pontos/técnico, streak, sinal médio, churn). Agrega 7 dias atual vs 7 dias anterior, calcula delta %, top/bottom 3 técnicos por pontos, e gera JSON estruturado com: resumo executivo, tendência, KPIs com status (✅/⚠️/🚨), destaques positivos, alertas, ações priorizadas (com responsável: Operações/Comercial/Estoque/RH/TI) e coaching individual.
- `routes/gestao_ia.py` (NOVO): `POST /api/gestao-ia/generate` + `GET /api/gestao-ia/latest` (persiste em `gestao_reports`).

**Frontend** (`/app/frontend/src/`):
- Nova aba **"📊 GESTÃO E METAS"** em `LousaAdminPanel.js` (sub-tab ao lado de Quadro e CENTRAL_ONT) renderizando `lousa/GestaoMetasPanel.js`:
  - Banner "Cards visíveis no app do técnico" com 5 toggles em cards verde/cinza (admin liga/desliga).
  - Botão "🤖 Gerar análise com GESTAO_IA" que dispara Claude e renderiza relatório com gradient azul escuro, KPIs em grid (com 🚨/⚠️/✅), ações recomendadas e coaching sugerido.
  - Tabela TOP técnicos por pontos (gamificação).
  - Bloco "Hoje · ranking ao vivo" com link para /mural.
- `LousaMobile.js`: lê config pública e respeita toggles (esconde cards desativados). Faz geofence-ping a cada 60s usando `navigator.geolocation` (apenas se `enable_geofence_alerts=true`). PerformanceCard mostra coluna "Pontos" entre Fechadas e % sucesso (controlado por `show_points`).
- `LousaAdminPanel.js`: cada coluna de técnico ganha botão **"🗺️ Rota"** (`optimize-route-{cid}`) que dispara `/lousa/admin/optimize-route` usando GPS persistido do técnico.
- Bolhas com `type="alerta_geofence"` renderizam com borda vermelha 2px + animação CSS `lousa-alert-blink` (keyframe halo pulsante).

**Validado**: 8/8 pytest (`test_iter97_gestao_metas.py`) — pontos, retirador, dashboard config get/post/public, geofence sem chamado, geofence cria alert + dedup, admin optimize 400 sem GPS, GESTAO_IA gera análise real via Claude Sonnet 4.5. Screenshot Playwright: aba renderiza relatório executivo completo com 6 KPIs, 7 ações priorizadas e coaching para DIOGO/VANDO.
- testids: `gestao-metas-panel`, `dashboard-toggles`, `toggle-{key}`, `gestao-ia-run-btn`, `gestao-ai-report`, `top-techs-section`, `leaderboard-today`, `lousa-subtab-gestao_metas`, `optimize-route-{cid}`.

✅ **Modo Concorrente (SWOT) na GESTAO_IA** (16/05/2026 — iter98):
- **Backend** `POST /api/gestao-ia/competitive-analysis` (`/app/backend/services/gestao_ai.py`): nova função `generate_competitive_analysis(company_id, market_input)` que coleta snapshot interno enxuto (sem chamar LLM duas vezes — refatorado para evitar latência dupla) + recebe texto livre do gestor com dados de mercado (concorrentes, preços, churn, expansão) e chama **Claude Sonnet 4.5** com prompt especializado em análise SWOT competitiva ISP. Persiste em `gestao_competitive`. `GET /latest` recupera. Validação: input < 20 chars → 400. Parser JSON tolerante a truncamento (recupera até último `}` válido).
- **Prompt inclui benchmarks ISP**: churn médio 2-4%, NPS bom >50, penetração 25-35%, ARPU R$90-130, CAC R$200-450 — para a IA contextualizar números reais.
- **Frontend** (`/app/frontend/src/lousa/GestaoMetasPanel.js`): nova section roxa "⚔️ GESTAO_IA · Modo Concorrente" com:
  - Textarea grande para input de mercado
  - Botão "⚔️ Gerar SWOT competitivo"
  - Renderização do schema completo: resumo estratégico · 4 quadrantes SWOT (💪 Forças verde, ⚠️ Fraquezas laranja, 🚀 Oportunidades ciano, ⚡ Ameaças vermelho) · Concorrentes identificados com tag ALTA/MEDIA/BAIXA · Bairros a priorizar · Ações curto prazo · Veredicto final em dourado.
- **Validado**: 4/4 pytest (`test_iter98_competitive.py`) — 400 curto · 401/403 sem auth · SWOT schema completo · GET latest. Screenshot Playwright: análise real do Claude detectou Sumicity como ameaça ALTA, sugeriu retenção no Centro com upgrade defensivo + campanha de indicação.
- testids: `competitive-section`, `competitive-input`, `competitive-run-btn`, `competitive-result`, `competitive-error`.

✅ **Modo Cliente Cancelando — Playbook de Retenção** (16/05/2026 — iter99):
**Backend** (`/app/backend/services/gestao_ai.py` + `routes/gestao_ia.py`):
- `RETENTION_DEFAULTS`: `{enabled, trigger_risk, discount_pct, visit_window_hours, auto_send_whatsapp, create_urgent_ticket, message_template}`. Template suporta placeholders `{nome}`, `{discount_pct}`, `{visit_window_hours}`.
- `GET/POST /api/gestao-ia/retention/config` (gestor): lê/atualiza com validações: trigger_risk ∈ {alto, critico}, discount_pct ∈ [0, 100], visit_window_hours ∈ [1, 168].
- `POST /api/gestao-ia/retention/trigger`: dispara manualmente. `fire_retention_playbook` (1) envia WhatsApp via Baileys com template formatado, (2) cria ticket urgente `type="retencao"` sem técnico, (3) registra no `retention_mural`. Idempotência: não duplica se já há entry `open/in_progress` para o phone. Respeita `enabled=false`.
- `GET /api/gestao-ia/retention/mural` lista últimas 50.
- `PATCH /api/gestao-ia/retention/mural/{rid}` muda status entre `open|in_progress|won|lost`.

**Frontend** (`/app/frontend/src/lousa/RetentionPlaybookCard.js` — novo):
- Card vermelho gradient no topo da aba GESTÃO E METAS.
- Toggle global ativar/desativar.
- 5 campos editáveis: risco que dispara · desconto % · janela visita h · enviar WhatsApp · criar bolha.
- Textarea grande do template.
- Botão "💾 Salvar regras" (verde quando dirty) + "⚡ Disparar manual" + "✕ Descartar".
- Modal disparo manual com phone/nome/motivo.
- Mural com lista de casos coloridos por status + chips de ação rápida.

✅ **Orçamento — Importar Pronto (sobe → imprime)** (16/05/2026 — iter100):
- **Backend** (`/app/backend/routes/budget.py`):
  - `_extract_items_via_ai` agora pede `unit_price` no JSON; popula `manual_override` e `avg_price` com o preço do documento original.
  - Parser CSV reconhece colunas `preco/preço/valor/unitario/price/valor_unitario` e normaliza formato BR (`R$ 1.234,56` → `1234.56`).
  - **Novo** `_extract_items_via_vision` para fotos/prints (.png .jpg .jpeg .webp) via LLM Vision (Emergent LLM Key) — extrai itens + preços de uma imagem.
  - Upload limit aumentado de 5MB → 10MB.
  - Response do upload retorna `items_with_price` + `ready_to_print` (true se ≥30% dos itens vieram com preço). Quando `ready_to_print=true`, status do budget vira `analyzed` direto (skip `/analyze`).
- **Frontend** (`/app/frontend/src/BudgetPanel.js`):
  - Input file `accept=".csv,.pdf,.docx,.txt,.png,.jpg,.jpeg,.webp,image/*"`.
  - Botão renomeado para **"📤 Importar pronto (PDF/imagem/CSV)"** com tooltip explicativo.
  - Após upload, se `ready_to_print=true`, mostra confirm "Abrir PDF para imprimir agora?" → abre `budgetPdfUrl(bid)` em nova aba. Fluxo final: **sobe arquivo → confirma → PDF abre com sua cara, com os preços importados**.
- **Validado**: 5/5 pytest (`test_iter100_budget_import_pronto.py`) — CSV com preços marca ready=true · formato BR R$1.234,56 · CSV sem preços fica draft · PDF gera com preços importados (18KB válido) · imagem PNG aceita pelo endpoint.

**Validado**: 5/5 pytest (`test_iter99_retention.py`) + screenshot Playwright (edita discount=35, salva, botão muda para "✓ Sem mudanças").
- testids: `retention-playbook-card`, `retention-toggle-enabled`, `retention-discount`, `retention-save-btn`, `retention-manual-trigger-btn`, `retention-row-{rid}`, `retention-status-{won|lost}-{rid}`, etc.

✅ **Upgrade Baileys 6.7.16 → 7.0.0-rc11 (LID resolution nativa)** (16/05/2026 — iter102):
- **Package** `/app/whatsapp-service/package.json`: bump `@whiskeysockets/baileys` para `^7.0.0-rc11` (`package.json.bak.iter102` mantido como backup).
- **Server** `/app/whatsapp-service/server.js`: ao receber mensagem inbound de LID, tenta resolver via `sock.signalRepository.lidMapping.getPNForLID(fromJid)` antes de cair no LID anônimo. Quando resolve, loga `"LID resolvido via lidMapping.getPNForLID"` e usa o telefone real direto — gestor não precisa mais clicar em "Vincular telefone".
- **Verificado**: Sidecar reiniciou, conectou ao WhatsApp como `5521965680949` ("Patrocínio 🇧🇷") e criou a **"Own LID session"** (suporte nativo agora ativo). Status `connected: true`. Erros "Bad MAC" iniciais são apenas sessões legacy do 6.7.16 que precisam ser refeitas — clientes reconectam automaticamente.
- **Compat**: API CommonJS mantida (`require("@whiskeysockets/baileys")` ainda exporta `makeWASocket`, `useMultiFileAuthState`, `jidNormalizedUser`, `isLidUser`, `DisconnectReason`). Nenhuma alteração no backend Python.
- **Rollback**: `cp /app/whatsapp-service/package.json.bak.iter102 /app/whatsapp-service/package.json && cd /app/whatsapp-service && npm install --silent && sudo supervisorctl restart whatsapp-service`.
✅ **WhatsApp Railway + Boleto Automático + Disparo Manual** (17/05/2026 — sessão fork):
- **Railway Sidecar** (`https://whatsapp-sidecar-production-6336.up.railway.app`):
  - Dockerfile sem `apk add python3/make/g++` (build leve, evita OOM no plano free)
  - Volume persistente 5GB em `/data/auth_info`
  - Bearer auth removida (modo aberto — sidecar isolado por URL obscura)
  - `WA_WEBHOOK_BASE = https://dual-combine-3.emergent.host/api` (produção)
  - Filtro `status@broadcast` / `@newsletter` no `messages.upsert`
- **Boleto Automático via Isabella** (`/app/backend/services/boleto_flow.py`):
  - Detecta intenção: boleto, 2ª via, pix, fatura, vencimento, atraso, débito (regex multi-padrão)
  - Busca cliente em `subscriber_phones` (com `normalized_number`) + fallback `atlaz_clients_cache.phone`
  - Cross com `subscriber_invoices.subscriber_external_id` (strip de prefixo `ATLAZ-`)
  - Lista TODAS faturas em aberto · monta mensagem com link/PIX/linha digitável/vencimento
  - Estado persistente em `boleto_flow_state` (pede CPF se não localiza)
- **Disparo Manual de Boletos** (`/app/backend/routes/disparo_boleto.py` + `/app/frontend/src/DisparoBoletoCard.js`):
  - `POST /api/disparo-ia/boletos/preview` — filtros days_min/max/only_overdue
  - `POST /api/disparo-ia/boletos/send` — async task em background com throttle (default 2s)
  - `dry_run=true` simula sem enviar · `custom_intro` prefixa mensagem
  - `GET /runs/{id}` polling de progresso · `GET /history` listagem
  - Card no DisparoIaPanel logo após KPIs · modal de confirmação · histórico expansível
  - Atualmente 228 candidatos (R$ 23.112,46) elegíveis no banco
- **Rede IA — Ranking Gamificado** (`/app/backend/routes/rede_ia.py`):
  - `GET /api/rede-ia/stats/by-technician?period=all|month|week`
  - Snapshot da praça/filial do técnico no momento do cadastro
  - Frontend: tag colorida primeiro_nome + medalhas 🥇🥈🥉 top3 + coluna Filial
- **Tempo "ONLINE HÁ" SmartOLT** (`/app/backend/routes/smartolt.py`):
  - Calcula uptime a partir de `last_status_change` quando ONU está Online
  - Formatos: `2d 14h`, `5h 32m`, `12m`
- **Webhook token sync**: `WA_INBOUND_TOKEN = JAALRyFdv9z7…` realinhado entre Railway e backend
- **Banco limpeza**: 730 msgs `+status` removidas + 1 conversa órfã
- **Isabella reativada**: `wa_autoreply_config` reinserida com `enabled=True` (estava None)

### 📌 Roadmap WhatsApp Multi-Tenant SaaS (postponed para Junho/2026):
**Plano A (MVP, ~30min):**
- Coleção `wa_tenant_config` `{company_id, sidecar_url, sidecar_token, inbound_token, status}`
- Refatorar `_sidecar_post()` lendo URL por tenant
- Tela admin "Configurações WhatsApp por Empresa" (URL/Token/Test/Status)
**Plano B (médio prazo):**
- Botão "Provisionar Railway" via API
- Self-service QR Code por tenant no painel próprio
- Métricas por tenant (msgs enviadas, custo)
**Plano C (escala 20+ clientes):**
- Multi-tenant em 1 container (MultiBaileys)
- Dashboard global de health-check
- Auto-recovery de sessões caídas
- Billing automático por uso


---

## 🎨 [17/Maio/2026] Restauração do Wallpaper Customizado Ligo no WhatsApp Chat

**Contexto:** Após "Re-deploy changes" sincronizando Preview → Produção, o usuário relatou que o wallpaper customizado (KAUE/MAYAR/LIGO + ícones WiFi) havia sumido da tela WhatsApp Chat.

**Diagnóstico realizado:**
- ✅ Arquivo fallback estático `/app/frontend/public/wa-wallpaper-ligo.png` (1.5 MB, 15/Mai) **CONTINHA** a arte customizada correta (LIGO, KAUE, MAYAR, WiFi)
- ❌ DB `aihub_settings.wa_chat_wallpaper` (co-demo) tinha um wallpaper **GENÉRICO** salvo via `PUT /api/whatsapp-baileys/wallpaper` (180 KB, padrão WhatsApp emojis/ícones) que sobrescrevia o fallback no chat
- ✅ Código de `WhatsAppChatLayout.js` (linhas 84/259-262/1558/1884) e `WaWallpaper.js` corretos: carregam DB primeiro com fallback para o arquivo estático

**Fix aplicado:**
- Re-encodado o arquivo estático em base64 (~2 MB data URL, dentro do limite de 8 MB) e enviado via `PUT /api/whatsapp-baileys/wallpaper` para sobrescrever o DB com o conteúdo correto.
- DB agora reflete a arte customizada do Ligo. Validado visualmente no painel "Configuração → Papel de parede do chat WhatsApp" (mock messages + pattern Ligo visível).

**Próximas tarefas em fila (pós-fix):**
- 🟡 Reconectar Baileys/Railway: sidecar gerando QR válido (~56s), aguardando usuário escanear no Atendimento IA → Configuração → "Conectar WhatsApp por QR Code"
- WhatsApp History Tab no Perfil do Cliente (P2)
- Vincular cliente manualmente para números desconhecidos no Chat (P2)
- Banco Inter PIX Dinâmico (P1)
- Multi-tenant WhatsApp SaaS (P1, postponed para Junho/2026)


---

## 🔧 [17/Fev/2026] Isabella V6.70 — Diagnóstico SmartOLT Refinado (LOS→Lousa, Offline→Humano)

**Contexto:** Refinamento do fluxo de manutenção automática da Isabella. Decisão do gestor: LOS deve gerar bolha de reparo automaticamente na Lousa (sem tentar reboot — não resolve fibra rompida); Offline deve transferir direto pro Atendimento Especializado (sem reboot, sem ticket — diagnóstico remoto incerto). Power Fail mantém oferta de agendamento.

**Mudanças aplicadas:**
- `services/subscriber_connection.py`:
  - `REBOOT_FIRST_STATUSES = set()` — nenhum reboot automático nas inbounds (função `try_reboot_onu` permanece disponível pra acionamento manual futuro)
  - `TICKET_TRIGGER_STATUSES = {"los", "power fail"}` — removido `offline` (vira handoff humano)
  - Novo `format_offline_transfer_for_prompt()` — bloco instruindo Isabella a transferir com frase exata
  - Novo `is_offline_handoff_message(text)` — regex detecta a frase gatilho na resposta da Isabella
  - `format_for_prompt` atualizado: LOS menciona Lousa explicitamente, Offline aponta protocolo de transferência
- `routes/whatsapp_baileys.py`:
  - Orquestração simplificada na inbound: LOS → `ensure_repair_ticket` direto; Offline → `format_offline_transfer_for_prompt`; Power Fail mantido
  - Novo bloco pós-envio: se `is_offline_handoff_message(reply)`, move `wa_conversations` pra `aguardando` com `handoff_reason: "isabella_offline_diagnosis"`
- `migrations/isabella_diagnostico_v670.py` — fragmento V6.70 criado e ativado, V6.60 desativado

**Validação:**
- ✅ 28/28 pytest em `tests/test_smartolt_isabella_flow.py` (regras, formatters, helpers, regex de handoff, dedupe de tickets, filtro Offline)
- ✅ Sandbox `/api/whatsapp-baileys/isabella/test` (cenário LOS): "Identifiquei... interrupção... NÃO peço reset... Já abri chamado #... Posso agendar pra HOJE 13-18 ou amanhã 09-12?"
- ✅ Sandbox (cenário Offline): "...aparece como desconectado... Vou transferir você agora pro nosso Atendimento Especializado..." (frase gatilho exata, prompt 39kB ~4.2s no DeepSeek)

**Status:** Funcional. Pronto pra produção.
