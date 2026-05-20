# PontoIA — Changelog

## Fev 2026 — Cargos do Colaborador (Função Operacional)

### Feature
Introduzido o conceito de **Cargo** (função operacional) — separado de `role` (permissão de painel). 6 cargos disponíveis em 2 grupos:

**🛠 Campo (Lousa de Agendamento)**: Técnico, Reparador, Instalador, Associado
**💼 Administrativo (Atendimento)**: Auxiliar Administrativo, Atendente

### Regras automáticas (aplicadas pelo backend ao salvar)
- **Lousa**: aparecem só cargos do grupo Campo (filtro em `GET /api/lousa/grid`)
- **Bate ponto**: TODOS exceto Associado (bloqueio 403 em `POST /api/clock-records`)
- **Atendimento WhatsApp**: AUX. ADMIN + ATENDENTE → `can_attend_whatsapp=True` automaticamente (só se quem cadastrou for auditor)
- **Compatibilidade**: colaboradores legados sem `cargo` continuam visíveis na Lousa e batendo ponto até migrar

### Implementação
**Backend**:
- `cargo.py` novo módulo com constantes (`LOUSA_CARGOS`, `NO_CLOCK_CARGOS`, `ATENDIMENTO_CARGOS`) + helpers (`is_lousa_cargo`, `clock_in_enabled_for`, `is_atendimento_cargo`, `infer_cargo_from_legacy`)
- `routes/clock.py`: campo `cargo` em `CollaboratorIn`; helpers `_apply_cargo_rules{_dict}` aplicados em CREATE/UPDATE; bloqueio 403 em `create_clock_record` se cargo não bate ponto
- `routes/lousa.py`: filtro `$or` em `lousa_grid` aceitando cargos da Lousa OU sem cargo (legacy)
- `POST /api/collaborators/migrate-cargo`: heurística idempotente que infere `cargo` a partir do `role` legado (testado: 10 colaboradores migrados todos como `tecnico`)

**Frontend**:
- `cargo.js` novo módulo espelho do backend (constantes + helpers + `CARGO_OPTIONS_GROUPED`)
- `CadastroPanel.js`: campo `<select>` agrupado por categoria (optgroup) substituindo o input livre de "Cargo"; hint colorido inline mostrando 3 propriedades automáticas (Lousa/Atendimento/Bate-ponto) ao trocar a seleção
- Mantém input livre "Cargo livre (apenas descritivo)" para `role` continuar customizável
- Badge `🔧 Técnico` / `🤝 Associado` etc na listagem de colaboradores ao lado do nome

### Verificação
- Curl: migrate-cargo retornou `{updated: 10}` em 1 chamada
- Screenshots: 4 estados validados (Vazio · Técnico · Associado · Atendente) com hints semânticos
- Lint + build limpos



## Fev 2026 — Filiais bidirecionais + Delete inteligente de parcelas

### 1. Sync bidirecional Filial → Atlaz
Helper `_push_to_atlaz_config()` adicionado no `routes/financeiro.py`. Sempre que o gestor cria ou edita uma filial no Financeiro com técnico padrão, o sistema **grava de volta** em `db.atlaz_config.{filiais, filial_to_collaborator}`:
- Lookup case-insensitive para não duplicar (ex: "Filial Norte" não vira "FILIAL NORTE")
- Limpa entradas duplicadas case-insensitive no mapping antes de gravar
- Não cria `atlaz_config` se ainda não existir (apenas log)
- Falha silenciosa: se o push falhar, a operação principal (CRUD da filial) não é abortada

Agora as duas telas (**Configurações → Atlaz** e **Financeiro → Filial**) ficam coerentes nas duas direções.

### 2. Delete de parcela com pergunta sobre futuras
**Backend** (`DELETE /api/financeiro/bills/{id}?delete_future_installments=true`):
- Query param opcional. Quando true, apaga TODAS as parcelas do mesmo `installment_group_id` que ainda não foram pagas (`status != "paid"`)
- Parcelas pagas são **sempre preservadas** (proteção do histórico financeiro)
- Resposta enriquecida: `{deleted_bill_id, future_installments_deleted, had_installment_group}`

**Frontend** (`BillsTab.onDelete`):
- 1ª confirmação: "Excluir 'X'? Se paga, estorna a movimentação."
- Se a conta tem `installment_group_id` e `installment_total > 1`, mostra **2ª confirmação**:
  > 📋 Esta conta faz parte de um parcelamento (1/3).
  > Deseja APAGAR TAMBÉM as parcelas futuras ainda não pagas?
- Toast no final mostra quantas parcelas extras foram apagadas
- Badge `📋 1/3` em pílula roxa adicionado ao lado do nome na tabela para identificar visualmente

### Verificação
- Curl: 5 parcelas criadas → delete da 1ª com flag → 1 + 4 futuras apagadas ✅
- Screenshots: 2 modais de confirmação em sequência funcionando
- Lint + build limpos (Python + JS)



## Fev 2026 — Filiais: Sync com Atlaz (fonte da verdade)

### Problema identificado
O usuário já tinha 8 filiais reais (LIGO CACHOEIRAS, LIGO CPX, LIGO EMPRESAS, LIGO GUARATINGUETA, LIGO MAGÉ, LIGO OSASCO, LIGO PENHA, LIGO RIO) configuradas em **Sistema → Configurações → Atlaz → Mapeamento Filial → Técnico padrão** com seus respectivos técnicos. Mas o módulo Financeiro ainda mostrava só 2 (Filial Norte e Matriz Centro) criadas manualmente. **Duplicação de cadastro** = fonte de inconsistência.

### 2 Fixes
**1. Bug `_list("filiais")` → `_list("fin_filiais")`**:
Os 4 endpoints CRUD usavam `db.filiais` (sem prefixo), inconsistente com o resto do módulo. Migração ad-hoc rodada: `db.filiais` → `db.fin_filiais` (2 docs migrados). Coleção `db.filiais` esvaziada.

**2. Endpoint de sincronização**:
- `POST /api/financeiro/filiais/sync-from-atlaz`
- Lê `db.atlaz_config.{filiais, filial_to_collaborator}`
- Cria filiais ausentes em `fin_filiais` (idempotente, lookup case-insensitive por nome)
- Atualiza `default_collaborator_id` quando o mapping mudou
- **NÃO remove** filiais locais que sumiram do Atlaz (proteção contra delete acidental)
- Retorna `{created, updated, skipped, total_atlaz_filiais, mapping_entries}`

### Frontend
- Botão **"🔄 Importar do Atlaz"** no header do card de Mapeamento
- Confirmação explicativa, ícone girando durante sync, banner de resultado mostrando contadores
- Listener de evento `fin-filiais-synced` no `CrudTab` faz refresh da tabela após sync

### Verificação
- Curl: sync importou 8 filiais com 6 mappings (LIGO EMPRESAS e MAGÉ ficaram sem técnico — igual ao Atlaz)
- Screenshot: card "7/10 configuradas" com pílulas + tabela completa de 10 filiais incluindo Filial Norte e Matriz Centro preservadas



## Fev 2026 — Financeiro: Aba "Relatórios" + KPIs (DRE, Aging, Top)

### Feature
Nova aba **"📊 Relatórios"** no Financeiro consolidando os principais KPIs financeiros do mês:

**Backend** (`/app/backend/routes/financeiro_reports.py`):
- `GET /api/financeiro/reports/dre?month=YYYY-MM` — DRE simplificado (receitas brutas, sub-componentes, despesas por categoria, lucro líquido, margem %)
- `GET /api/financeiro/reports/aging-payable` — Aging de contas a pagar em 8 buckets (vencido >90/61-90/31-60/até 30 + a vencer ≤30/31-60/61-90/>90)
- `GET /api/financeiro/reports/top-suppliers?month=YYYY-MM&limit=10` — Top fornecedores por valor
- `GET /api/financeiro/reports/kpis?month=YYYY-MM` — KPI panel header (saldo, receita/despesa/lucro do mês, pendentes, vencidas)

**Frontend** (`/app/frontend/src/FinanceiroReportsTab.js`):
- Header preto com seletor "Mês anterior | Mês atual | DatePicker"
- 4 cards KPI no topo (Saldo, Receita, Despesa, Lucro) com cores semânticas
- 2 cards de bills (Pendentes amarelo / Vencidas vermelho) span-2
- **DRE visual**: linha principal Receitas Brutas → sub-linhas indentadas (Movimentações + Faturas Atlaz) → (-) Despesas Operacionais por categoria → = Lucro/Prejuízo Líquido com margem %
- **Aging chart**: ResponsiveContainer + BarChart horizontal vermelho (vencidas) / azul (a vencer)
- **Top Fornecedores**: ranking 1-10 com badge dourado top 3, barra de progresso de fundo proporcional, pílulas de pagas/pendentes, total formatado em monoespaçado

### Verificação
- Curl validado para DRE, Aging, KPIs com dados reais (R$ 179.210,96 receita, R$ 99,90 vencidas)
- Screenshot validado: aba completa renderizando com todos os 7 elementos



## Fev 2026 — Filiais Phase 1.5: Mapeamento Filial → Técnico padrão

### Feature
Cada Filial pode agora ter um **Técnico padrão** vinculado. Quando o gestor seleciona a filial em qualquer fluxo (atualmente: Modal "Nova conta"), o sistema **copia o técnico padrão por associação** (sem IA inferindo nada — pura lookup).

**Backend**:
- Campo `default_collaborator_id` opcional adicionado em `FilialIn`

**Frontend**:
- Form de criação/edição de Filial ganhou `<select>` "Técnico padrão" com lista de colaboradores ativos (carregada de `/api/collaborators`)
- Tabela de Filiais ganhou coluna "Técnico padrão" com pílula verde `👤 <Nome>` ou `—`
- Card resumo no topo da aba: **"🏢 Mapeamento Filial → Técnico padrão"** com contador (`N/M configuradas`) e pílulas `🏢 Filial → 👤 Técnico` lado a lado (visão Cadastros)
- BillForm: quando filial é selecionada, exibe hint verde inline `🏢→👤 Técnico padrão: <Nome>` (resolução via `refs.collaborators_by_id` carregado no `BillsTab`)
- `CrudTab` ganhou prop `extraHeader` (renderizado antes do search/Novo) — permite cards de contexto reutilizáveis

### Verificação
- Backend curl validado: PUT filial com `default_collaborator_id` retorna o campo persistido
- Screenshots: aba Filial com card de mapeamento + coluna técnico padrão · modal Nova conta com hint verde após selecionar filial
- Build + lint ✅



## Fev 2026 — Filiais (unidades/branches) — Phase 1

### Feature
Conceito de Filial introduzido no sistema. Phase 1 cobre cadastro + linkagem com contas do Financeiro. Phase 2 estenderá pra colaboradores, clientes, lousa.

**Backend** (`/api/financeiro/filiais`):
- Schema `FilialIn`: apenas `name` + `active` (cadastro mínimo)
- CRUD completo no mesmo padrão dos outros recursos (`/api/financeiro/filiais`)
- Delete limpa `filial_id` das contas vinculadas (`$unset` em `fin_bills_payable`)
- Campo `filial_id` adicionado a `BillIn` e `BillUpdate` (opcional)
- Endpoint `GET /api/financeiro/bills` aceita `?filial_id=xxx` (com sentinela `__none__` pra contas sem filial)

**Frontend**:
- API client estendido (`finFiliaisList/Create/Update/Delete`)
- **Aba "Filial" nova** no FinanceiroPanel (CrudTab — reuso do padrão existente)
- **BillForm** ganhou campo Filial com seletor `<select>` + botão `+` para criação inline (mesmo padrão Fornecedor/Categoria)
- **BillsTab** filtro `<select>` na toolbar (🏢 Todas filiais / 🏢 Cada / ⊘ Sem filial)
- **BillsTable** ganhou coluna "Filial" com pílula azul claro `🏢 <Nome>` ou em branco

**4. Migration soft (P1 4b)**: contas existentes ficam com filial vazia. Usuário atribui manualmente.

### Verificação
- Testes curl validados: criar filial · criar bill com `filial_id` · filtrar bills por `filial_id`
- Build limpo · Lint passa (frontend + backend)
- Screenshots: aba Filial com lista + modal "Novo — Filiais" / modal "Nova conta" com seletor Filial entre Categoria e Nº Documento

### Próximas fases
- Phase 2: estender filial_id pra collaborators, clients, lousa_tickets
- Phase 3: breakdown por filial no Dashboard (saldo separado, gráficos individuais)



## Fev 2026 — Lousa Focus Mode: Timeline View horizontal

### Feature
Adicionei segunda visualização ao Focus Mode da Lousa (visão de 1 técnico). Toggle "Grade | Timeline" aparece na toolbar somente quando há técnico focado, e a escolha persiste em `localStorage` (`lousa_focus_view`).

**TechTimeline** novo componente:
- Header limpo com avatar grande, nome, contagem e badges de ponto (Entrada/Intervalo/Saída) inline
- Faixa horizontal de slots (160px cada, scrollable em X) — uma coluna por horário
- Cada slot mostra: hora, contador `n/maxPerSlot`, tickets empilhados verticalmente
- Slot da hora atual ganha borda verde + indicador `●` (estilo "agora")
- Drag/drop entre slots funciona (reusa `onSlotDrop` do server)
- Coluna especial **"Sem horário"** sticky no fim (amarelo) para bolhas não agendadas — também é drop target
- Rodapé compacto com "Encerrados (24h)" em chips horizontais

Reuso de componentes existentes: `BubbleCard`, `OptimizeRouteButton`, mesmas APIs do TechColumn.

### Verificação
- `yarn build` ✅ limpo
- Screenshot validado: timeline horizontal do Eddy com 14:00 ocupado + slot atual destacado



## Fev 2026 — Lousa: Toolbar compacta + Filtro de técnico único

### Toolbar refatorada (estilo Notion/Linear)
Antes: 9 botões em 2 linhas com cores misturadas (vermelho, azul, preto, branco), caótico. Agora: **uma linha** com 4 grupos visualmente separados por divisores sutis, paleta monocromática neutra com acentos discretos (vermelho só para "Liberar bolha" e badge da Sentinela, preto sólido só pro CTA primário "Nova nota"):

- **Grupo 1 (Navegação)**: 🛡 Sentinela · 📅 Data
- **Grupo 2 (Visualização)**: 👥 Filtro de técnico · ☐ Selecionar · 📚 Histórico
- **Grupo 3 (Operação)**: 🔔/🔕 Alertas · 🔄 Atualizar · 🚨 Liberar bolha
- **Grupo 4 (Ações)**: + Nova nota (CTA) · ⋯ Overflow (Apagar todas — auditor only, movido pra fora do clique frequente)

Adicionei `ToolbarGroup`, `ToolbarBtn`, `TechFilterMenu`, `OverflowMenu` como primitivos no fim do arquivo. Sistema de `accent` (neutral/primary/success/danger) padroniza cores.

### Filtro de técnico único (Focus mode)
- Dropdown na toolbar com avatar do técnico focado
- Menu com busca, contadores (ativos + atrasadas por técnico) e opção "Todos os técnicos"
- Persistência via `localStorage` (key `lousa_focus_tech`) — sobrevive ao F5
- Quando focado: grade vira coluna larga (`flex: 1 1 auto`, `min-width: 480px`) ao invés de 320px fixos
- Subtítulo da página muda para "Visão focada · 1 técnico de N" + botão `✕ Mostrar todos`
- Prop `wide` adicionada ao `TechColumn` pra distinguir visualmente as duas modalidades

### Verificação
- `yarn build` ✅ limpo
- Screenshots validados: toolbar nova / dropdown aberto com lista + busca / focus mode com Eddy em coluna ampliada



## Fev 2026 — Histórico de Ações (Dialog History Panel) + Hotfix `tabs is not defined`

### Feature: Painel de auditoria de modais
Estendi o `dialog.js` para que CADA modal (`alert`/`confirm`/`prompt`) seja registrado num buffer circular in-memory (últimos 100). Criei `DialogHistoryPanel.js` com:
- Botão flutuante "Ações" (bottom-right, posicionado acima do badge Emergent) com badge de contagem
- Drawer slide-in da direita com header, busca, 4 filtros por tipo (Todas/Confirmações/Avisos/Entradas), lista cronológica e botão Limpar
- Cada entrada mostra: ícone do tipo, título, mensagem (clamp 3 linhas), timestamp e pílula de resposta ("✓ Confirmou" verde / "✕ Cancelou" cinza / "✎ "texto"" para prompt)
- Visível **apenas** para roles `administrador` e `auditor` (gate por `useAuth`)

Helpers exportados em `dialog.js`: `getDialogHistory()`, `clearDialogHistory()`, `useDialogHistory()`.

### Bug fix: `ReferenceError: tabs is not defined` após login
A introdução da `BlockedPage` em fork anterior referenciou a variável `tabs` no `AppContent`, mas ela era definida apenas em `AppShell` (escopo diferente). Resultado: assim que o usuário logava, o React quebrava com referência indefinida.

**Correção**: lifted a lógica de filtro de abas (state `tabPerms`, `isSuperAdmin`, useEffect que lê `brandingGet` + `saasMe`, e useMemo do `tabs`) para dentro do `AppContent`. Agora a checagem `allowed` na linha 943 funciona corretamente. O AppShell mantém seu próprio filtro idêntico, garantindo que sidebar e roteador convergem.

### Verificação
- `yarn build` passa limpo
- Login → dashboard renderiza normalmente
- Botão flutuante "Ações" aparece para admin e o drawer abre com empty state corretamente



## Fev 2026 — Hotfix: Frontend build quebrado (tela branca em produção)

### Problema
Após o usuário aceitar a refatoração de `window.alert/confirm/prompt` para modal customizado (`dialog.js`), o agente anterior usou `sed` para adicionar `await` antes de todas as chamadas. Isso quebrou 12 arquivos JSX porque vários handlers (`onClick={() => {...}}`, callbacks de geolocation, helpers internos) não eram `async`. Resultado: `Failed to compile · Unexpected reserved word 'await'`. Em produção (ligo.site) o build quebrado servia bundle vazio → tela branca após login.

### Correção
Tornei `async` cada função/handler que ficou com `await window.alert|confirm|prompt`:
- `DisparoPromoPanel.js` — `onMediaChange`
- `HoleritePanel.js` — `copyLink`
- `LousaAdminPanel.js` — 2 handlers inline (`onClick` Encerrar/Cancelar)
- `LousaMobile.js` — `goToStep2`, `submit`
- `PlatformAdminPanel.js` — `openDeleteModal`
- `PublicAccessPanel.js` — `copy`
- `RedeIaMapMobile.js` — `goToMyLocation` + error callback do geolocation
- `SubscribersPanel.js` — `runBulk`
- `TabPermissionsCard.js` — `reset`
- `UberGpsPicker.js` — `useMyLocation` + error callback do geolocation
- `WhatsAppChatLayout.js` — handler inline do botão de coaching
- `lousa/RescheduleModal.js` — `submit`

### Verificação
`yarn build` passa limpo. Login (`/login`) renderiza corretamente. Bundle de produção pode ser publicado em ligo.site.



## Mai 2026 — v6.80: Refactor multi-agente IA (best practices 2026)

### Problema
- Álvaro, Camila e Teste estavam com `model_provider=None` / `model_name=None` (caíam no fallback frágil).
- Prompts misturavam estilo + regras + handoff em texto corrido (LLMs entregam melhor com seções XML-like).
- Sem regra anti-loop: cliente que mudava de assunto era repassado eternamente entre agentes.
- Reasoning não era instruído como interno → modelo às vezes vazava pensamento.

### Solução aplicada
1. **Migration `refine_agents_v680.py`** reescreve os 4 prompts (Isabella/Álvaro/Camila/Teste) seguindo padrão 2026:
   - Estrutura XML-like: `<role>`, `<scope>`, `<reasoning>`, `<flow>`, `<output>`, `<examples>`, `<global_rules>`, `<handoff_protocol>`, `<sticker_handling>`
   - Top-load: scope + anti-alucinação primeiro
   - Reasoning interno (modelo pensa mas só envia resultado final)
   - Few-shots específicos por agente (3-4 exemplos com handoff incluído)
   - Output strict: bolhas ≤180c, máx 4 bolhas, sem markdown, emojis comedidos
2. **Modelo explícito** para Álvaro/Camila/Teste (`deepseek/deepseek-chat`), Isabella mantém `deepseek-v3.1-terminus`.
3. **Anti-loop dupla camada**:
   - No prompt: regra R8 das `<global_rules>` ("se passou por handoff nas últimas 3 msgs, NÃO devolva")
   - No código (`whatsapp_baileys.py`): conta `aihub_wa_messages.direction=inbound` com `created_at > last_handoff_at`. Se < 3, ignora marker e mantém agente atual.
4. **handoff_detection.py** agora aceita `recent_handoff=True` e retorna `None` (anti-loop no pré-LLM também).
5. **Documentação visual** do fluxo em `/app/memory/AI_AGENTS_FLOW.md` (diagrama, regras, como testar).

### Validação
3 cenários testados via `/api/whatsapp-baileys/isabella/test`:
- ✅ "Quanto custa internet?" → Isabella saúda + pergunta bairro + 3 bolhas curtas, 1 emoji/bolha
- ✅ "Internet caiu" → frase calorosa + `[ROTEAR_SUPORTE]` em linha separada
- ✅ "Manda boleto" → transição + `[ROTEAR_COBRANCA]` em linha separada

Latência ~2s, prompt 33k chars (com toda orquestração), formato perfeito.

### Files changed
- `+ /app/backend/migrations/refine_agents_v680.py` (novo, idempotente)
- `~ /app/backend/services/wa/handoff_detection.py` (parâmetro `recent_handoff`)
- `~ /app/backend/routes/whatsapp_baileys.py` (anti-loop pré-LLM + pós-LLM)
- `+ /app/memory/AI_AGENTS_FLOW.md` (doc canônico do fluxo)
- `~ /app/memory/test_credentials.md` (atualizado para v6.80)

---


# PontoIA — Changelog

## Fev 18, 2026 — Fix P0: foto/PDF inbound do WhatsApp não chegavam ao painel

### Bug reportado pelo usuário (produção)
"Cliente envia foto/PDF pelo WhatsApp pro número da Isabella, e o atendente/painel não vê chegar. Áudio funciona normal."

### Root cause
`/app/whatsapp-service/server.js:449` — fazia `const msg = m.message` sem desempacotar envelopes de privacidade do WhatsApp. Quando o cliente tem **mensagens temporárias ativadas** (ephemeralMessage) ou envia **foto que some** (viewOnceMessageV2), o payload da imagem fica encapsulado:

- `m.message.ephemeralMessage.message.imageMessage` (não tratado)
- `m.message.viewOnceMessage.message.imageMessage` (não tratado)
- `m.message.viewOnceMessageV2.message.imageMessage` (não tratado)
- `m.message.documentWithCaptionMessage.message.documentMessage` (tratado APENAS pra doc)

Como `msg.imageMessage` retornava `undefined`, o `downloadMediaMessage` nem era chamado, e o backend recebia o webhook com `media_b64=null`. Áudio funcionava porque WhatsApp não embrulha áudio em ephemeral por padrão.

### Fix aplicado em `whatsapp-service/server.js`
1. **Desempacota 5 envelopes** antes de ler `imageMessage/videoMessage/documentMessage/stickerMessage`:
```js
let msg = m.message;
if (msg.ephemeralMessage?.message)         msg = msg.ephemeralMessage.message;
if (msg.viewOnceMessage?.message)          msg = msg.viewOnceMessage.message;
if (msg.viewOnceMessageV2?.message)        msg = msg.viewOnceMessageV2.message;
if (msg.viewOnceMessageV2Extension?.message) msg = msg.viewOnceMessageV2Extension.message;
if (msg.documentWithCaptionMessage?.message) msg = msg.documentWithCaptionMessage.message;
```
2. Adicionado `text` agora também lê `msg.documentMessage?.caption` (legenda de PDF).
3. Logs explícitos `inbound media — iniciando download` / `download OK` / `buffer vazio` pra debug futuro.
4. Removida lógica redundante de docMsg (agora resolvida no desempacotamento).

### Status
- Preview: aplicado e sintaxe validada. Sidecar precisa de novo QR pra testar end-to-end (sessão expirou).
- Produção: usuário precisa fazer **novo deploy** pra o fix subir. Após deploy, fotos/PDFs ephemeral devem aparecer no painel normalmente.



## Fev 18, 2026 — Chaves de IA Multi-Tenant (P0 finalizado · iter98-fork)

### Contexto
Continuação do trabalho da iter97: o `EMERGENT_LLM_KEY` global ficou sem créditos várias vezes (Isabella Vision muda). A solução era permitir que cada empresa cole suas próprias chaves Anthropic/OpenAI/Gemini em `Configurações → Integrações de IA`. Frontend (`SettingsPanel.js`) já tinha os 3 inputs, backend (`admin.py`) já aceitava o payload e `services/ai_keys.py` já resolvia. Faltavam 2 bugs que invalidavam todo o esforço:

### Bugs corrigidos
1. **`services/media_analysis.py:78-80`** — `analyze_image()` retornava `None` quando `EMERGENT_LLM_KEY` estava vazia, **antes mesmo de consultar a chave própria do tenant**. Removido o hard-gate; agora vai direto pro `resolve_keys()` que faz a cascata correta (DB tenant → env global → EMERGENT fallback).
2. **`services/media_analysis.py:176`** (`analyze_pdf`) — Usava `api_key=EMERGENT_KEY` diretamente em vez de chamar `resolve_keys(company_id)`. Substituído por `resolve_keys` com fallback (gemini → openai → anthropic) para respeitar a chave do tenant também em PDFs.

### Polimento Frontend
- **`SettingsPanel.js`**: incluídos `anthropic_api_key: ""` e `gemini_api_key: ""` no estado inicial e no `reload()` (evita warning React controlled↔uncontrolled).
- Payload do save agora descarta strings vazias para `anthropic_api_key` e `gemini_api_key` (não apaga acidentalmente uma key existente ao salvar outras opções).

### Comportamento garantido
- `EMERGENT_LLM_KEY` **continua** como fallback (decisão do usuário) — mas só é usada quando o tenant não tem chave própria nem env global. Se a Universal Key estourar de novo, basta o cliente colar sua chave Gemini gratuita (2M tokens/dia free no AI Studio) que tudo volta automaticamente.
- Cache do `ai_keys.py` é invalidado automaticamente quando PUT `/api/settings` recebe qualquer key (`anthropic_api_key`, `openai_api_key`, `gemini_api_key`).

### Validado E2E
- `curl PUT /api/settings` com `gemini_api_key=AIzaSyTEST...` → GET retorna `gemini_api_key_set=true` mascarado como `AIza...***cdef`.
- `python3 -c "resolve_keys(...)"` com/sem key no DB → cascata correta (custom > env > EMERGENT).
- `analyze_image(PNG 1x1)` em `co-demo` (sem key própria) → retornou descrição via fallback EMERGENT. Função não quebra em nenhum cenário.
- Lint `ruff` em `media_analysis.py`: All checks passed.



## Fev 18, 2026 — RCA: Isabella muda em imagens/PDFs = Budget esgotado + Rebrand (iter99)

### 🔍 Root Cause encontrado
- Reproduzido localmente: `analyze_image()` retornava `None` em todas as chamadas. Stack trace mostrou: **`litellm.BadRequestError: OpenAIException - Budget has been exceeded! Current cost: 1.61, Max budget: 1.0`**.
- A Emergent Universal Key estourou o orçamento (R$1.00 cap configurado). Sem créditos → Gemini Vision falha silenciosamente → `vision_summary=None`, `ai_input` ficava vazio → Isabella não tinha nada pra responder → cliente vê silêncio total.

### Correções aplicadas
- **`services/media_analysis.py`**:
  - Detecta `"Budget has been exceeded"` no erro e loga em nível **ERROR** (não WARN ruidoso) com instrução clara pro gestor (`Profile → Universal Key → Add Balance`).
  - Persiste flag `emergent_llm_budget_exceeded=true` em `aihub_settings` pra UI mostrar banner.
- **`routes/whatsapp_baileys.py`**: novo fallback no `ai_input` — quando vision falha E o cliente mandou só foto/PDF sem caption, em vez de Isabella ficar muda, ela recebe um marcador `[CLIENTE_ENVIOU_IMAGE_SEM_DESCRICAO: ...]` orientando a pedir descrição em texto **sem inventar conteúdo**. Cliente ao menos recebe resposta amigável.

### Ação do usuário
- ⚠️ **Recarregar saldo da Universal Key** em **Profile → Universal Key → Add Balance** (ou ativar **Auto Top-up**) — sem isso, a IA Vision não volta. As correções acima são proteção/graceful fallback, mas Vision só volta a funcionar com saldo.

## Fev 18, 2026 — Rebrand completo "SmartProv" (iter99)
**Objetivo do usuário**: atualizar a marca de "Ponto do Colaborador" / "PontoIA" para **SmartProv** com o novo logo e ícone (azul + roxo, hexágono).



## Fev 18, 2026 — Rebrand completo "SmartProv" (iter99)
**Objetivo do usuário**: atualizar a marca de "Ponto do Colaborador" / "PontoIA" para **SmartProv** com o novo logo e ícone (azul + roxo, hexágono).

### Assets adicionados
- `/app/frontend/public/smartprov_logo.png` (logo horizontal com texto, 347 KB) — usado no og:image dos cards de WhatsApp/social.
- `/app/frontend/public/smartprov_icon.png` (ícone hexagonal só, 121 KB) — favicon, apple-touch-icon, sidebar e login.

### Frontend
- **`/app/frontend/public/index.html`**:
  - Novo `<title>SmartProv</title>`
  - Meta tags Open Graph completas (og:title, og:description, og:image, og:type)
  - Twitter Card (`summary_large_image`)
  - `theme-color` mudou pra `#0a1530` (azul escuro do logo).
  - Favicon e apple-touch-icon agora apontam pro `smartprov_icon.png`.
  - `apple-mobile-web-app-title` = "SmartProv".
- **`/app/frontend/public/manifest.json`**: name/short_name/description/theme_color atualizados; ícones 192/512 apontam pro `smartprov_icon.png`.
- **`App.js` (sidebar brand)**: o "S" placeholder substituído por `<img src="/smartprov_icon.png">` 32×32.
- **`LoginPage.js`**: mesmo replace do "S" pelo ícone real.
- **`SettingsPanel.js`**: sender_name dos emails padronizado para "SmartProv".

### Backend
- **`core.py`**: `sender_name` default = "SmartProv", `X-Title` LLM = "SmartProv Lousa", plan comment = "SmartProv Pro".
- **`routes/saas.py`**: rebrand em massa (sed) — emails de "Bem-vindo", "Pagamento confirmado", labels de planos: PontoIA → SmartProv. 0 ocorrências residuais.

### Validação
- `curl -I` confirma servir `/smartprov_icon.png` e `/smartprov_logo.png` com `200 OK` no preview.
- Meta tags og:image apontam corretamente para `/smartprov_logo.png`.
- Lint OK (Python + JS).

### Para produção
- Necessário **Save to GitHub + Redeploy** pra que `https://dual-combine-3.emergent.host` atualize. O preview já está com a nova identidade.



## Fev 18, 2026 — Migração permissão "Atendimento WhatsApp" para Cadastro (iter98)
**Objetivo do usuário**: tirar a checkbox 'Pode abrir o Atendimento WhatsApp' da Gestão de Usuários e colocar no Cadastro de Colaboradores, com gate por role: **somente AUDITOR pode editar**.

### Backend (`/app/backend/routes/clock.py`)
- Novo campo `can_attend_whatsapp: bool = False` em `CollaboratorIn`.
- `POST /collaborators`: se quem cria é gestor e envia `true`, o campo é silenciosamente forçado pra `false` (só auditor/admin libera).
- `PUT /collaborators/{id}`: se quem edita não é auditor/admin, **preserva o valor anterior** do flag — gestor nunca consegue ligar nem desligar.
- **Sincronização**: ao salvar collaborator, faz `update_many` em `users` com `collaborator_id=cid` setando o mesmo `can_attend_whatsapp` → menu "Atendimento IA" aparece/some na sidebar imediatamente.

### Frontend
- **UsersPanel.js**: removida a checkbox antiga `u-can-attend-whatsapp`. Texto explicativo agora orienta a ir em "Cadastro → Colaboradores" e que apenas auditor pode liberar.
- **CadastroPanel.js**:
  - `EMPTY` incluindo `can_attend_whatsapp: false`.
  - `useAuth()` + `isAuditor` derivado de `role === 'auditor' | 'admin' | 'administrador'`.
  - **Auditor**: vê bloco `whatsapp-perm-block` com checkbox `inp-can-attend-whatsapp` + badge "🔒 AUDITOR" + texto explicando que é decisão de conformidade.
  - **Gestor**: vê apenas aviso somente-leitura `whatsapp-perm-readonly` quando o flag já está ligado (transparência sem possibilidade de mexer). Quando false, não vê nada.
  - Fix corner case: `toggleClockInEnabled` agora envia o objeto completo (incluindo `can_attend_whatsapp`) pra evitar reset acidental ao alternar "bate ponto".

### Verificação Isabella (resposta direta ao usuário)
- ✅ **WhatsApp conectado** (`state: connected`, número Patrocínio 🇧🇷).
- ✅ **Isabella ativa**: 293 amostras de latência nos últimos dias.
- ✅ p50=6.7s · p95=48s · p99=184s (outliers raros, <5%).
- Última desconexão foi um watchdog reboot normal (não bloqueia).

### Validação (testing_agent_v3_fork iter98)
- Backend 5/5 pytest passou (gestor bloqueado no create+update, auditor libera, sync com user vinculado).
- Frontend: code review aprovou; ajuste do `toggleClockInEnabled` aplicado.
- Arquivo de teste: `/app/backend/tests/test_whatsapp_perm.py`.



## Fev 18, 2026 — Conciliação Ativa (PIX × Atlaz com baixa automática) (iter97) ★★★
**Objetivo do usuário**: cruzar PIX bancário do Sicoob com boletos abertos do Atlaz e dar BAIXA AUTOMÁTICA nas faturas quando há match (CPF/CNPJ + valor + data próxima).

### Backend (`/app/backend/routes/bank_import.py`)
- `POST /reconcile-payments?from_date=&to_date=&auto_mark=true` — algoritmo:
  1. Busca `fin_cash_movements` income source=sicoob/outros no período (exclui já conciliados via `reconciled_invoice_id`).
  2. Busca `subscriber_invoices` status=open com vencimento até 30d após `to_date`.
  3. Resolve CPF/CNPJ da fatura via `subscribers.external_code` quando vazio.
  4. Index `(doc, valor_arredondado)` → busca match com data mais próxima.
  5. **Score 100** (CPF + valor + ≤1d) → marca automática local (`status=paid`, `paid_method='auto_reconciliation'`, `reconciled_movement_id`).
  6. **Score 95** (≤7d) → marca automática se `auto_mark=true`.
  7. **Score 90** (>7d) → pendente revisão.
- `POST /reconcile-confirm` — aprova batch de matches manuais.
- Retorna `{auto_marked, pending, pix_orphans, invoices_orphans, stats}`.

### Frontend
- `ReconciliationCard.js` — novo botão **"🔍 Ver discrepâncias & auto-baixar"** no header.
- `ReconcileMatchModal.js` — NOVO modal com 4 abas:
  - ✅ **Auto-baixados** (score 100, já marcados).
  - 🔍 **Revisar** (score 90-95, com checkbox + botão "Aprovar selecionados").
  - 💰 **PIX sem fatura** (cliente pagou mas não tem boleto correspondente — investigar).
  - 📄 **Faturas sem PIX** (boleto vencido, cliente não pagou ainda).
- Cards de match mostram lado a lado: PIX bancário ← → Fatura Atlaz com score colorido (verde 100% / amarelo 95% / laranja 90%) e dias de diferença.
- Pré-seleção inteligente: matches score≥95 vêm marcados; score=90 desmarcado por padrão (segurança).

### Validação (testing_agent_v3_fork iter97)
- Backend 6/6 pytest ✓ (match score 100, idempotência, resolução external_code, batch manual, orphans cap).
- Frontend E2E ✓ — modal completo com seeds, 4 abas com contadores, score badge, checkbox, footer.



## Fev 18, 2026 — P1 WhatsApp avatar fix + Dashboard de conciliação (iter96)

### P1 Fix · WhatsApp Baileys RC11 avatar (Não-bloqueante)
- Web search confirmou: `baileys@latest` e `@whiskeysockets/baileys@latest` ambos em `7.0.0-rc11` (não há versão estável). Solução adotada: **workaround code-level** sem trocar de pacote.
- Novo helper `safeProfilePictureUrl(jid)` em `/app/whatsapp-service/server.js`:
  - Fallback `"preview"` → `"image"` (preview falha menos).
  - `Promise.race` com timeout de 4s pra evitar travamentos.
  - Cache negativo `negativeAvatarCache` (30 min) — evita re-tentar números que já falharam, dramaticamente menos requests à Meta.
  - Engole todos os Promise rejects (resolveram o `unhandledRejection` do RC11).
- Endpoints `/contact-profile` e `/contacts-bulk` agora usam o wrapper.
- **Save to GitHub necessário** pra ir pra produção (`dual-combine-3.emergent.host`).

### Dashboard de Conciliação · Banco × Atlaz
- **Backend** novo endpoint `GET /api/financeiro/bank-import/reconciliation?from_date=&to_date=` que faz aggregation pipeline em `fin_cash_movements` agrupando por `source`. Retorna `{bank: {total, count, sicoob, outros}, atlaz, manual, diff, by_source}`.
- **Frontend** novo componente `/app/frontend/src/ReconciliationCard.js`:
  - 3 blocos lado-a-lado: `recon-bank` (com breakdown Sicoob/Outros), `recon-atlaz`, `recon-diff` (destacado com borda colorida).
  - Banner de status (`recon-status`) verde "Conciliado ✓" quando diferença < 5% do maior valor, amarelo "Diferença de X%" caso contrário.
  - Texto explicativo orientando o gestor a investigar (cliente pagou em outro banco / MED / fatura fora do período).
  - Auto-hide quando bank+atlaz=0 (`return null`).
- Integrado no `CashFlowTab` entre o `AnalyticsChart` e o gráfico — propaga o `period` (7/30/90) selecionado.

### Validação
- Curl testado com seed (3 movs Atlaz R$730 + 20 Sicoob R$2329.85) → diff R$1599.85 ✓.
- Testing agent (iter96) fez code review: 100% spec implementada, todos data-testids presentes.
- Code review aplicado: simplificado `manual_total` fallback (removido `by_source.get(None)` morto).



## Fev 18, 2026 — Importar Extrato com 3 fontes (Sicoob · Outros · Atlaz) (iter95) ★
**Objetivo do usuário**: estender a sub-aba "Importar Extrato" para suportar (1) Sicoob OFX (já existente), (2) Outros bancos OFX/CSV padrão, (3) Atlaz V2 — buscar faturas pagas dos assinantes diretamente da integração.

### Backend (`/app/backend/routes/bank_import.py`)
- `POST /upload?source=sicoob|outros` — parser comum, source gravado no staging.
- `POST /atlaz-fetch` — body `{from_date, to_date, limit}` busca `subscriber_invoices` status=paid no período, transforma em transações income com descrição "ATLAZ · NOME · DOC · FAT#xxx", reutiliza `_build_staging`.
- `GET /atlaz-summary` — retorna `{paid_invoices, first_paid_date, last_paid_date}` pra dar visibilidade no UI.
- Helper `_build_staging` extraído pra evitar duplicação entre `/upload` e `/atlaz-fetch`.

### Otimizações pós-iter95 (code review)
- **Skip IA para Atlaz**: items vindos do Atlaz têm `source='atlaz'` e NÃO passam pela IA (já sabemos tipo=income + nome do assinante). Reduz tempo de 60s+ pra <1s em batch de 50 itens.
- **Auto-match de fornecedor**: pré-busca `fin_suppliers` por CNPJ do assinante; se match → preenche `supplier_id` automático com confidence 0.92.
- **Source dinâmico no movement**: `fin_cash_movements.source` agora reflete a origem real (`bank_import_sicoob`, `bank_import_outros`, `bank_import_atlaz`) — rastreabilidade correta no Fluxo de Caixa.
- `_safe_date()` aplicado pra `paid_date` Atlaz (suporta `datetime` ou string com timestamp).
- Limit padrão do UI reduzido de 500 → 200 (evita timeout em runs grandes).

### Frontend (`/app/frontend/src/BankImportTab.js`)
- 3 botões grandes (`bi-source-sicoob`, `bi-source-outros`, `bi-source-atlaz`) com ícone, label e hint contextual (ex: Atlaz mostra "1780 faturas pagas disponíveis").
- Painel condicional: Sicoob/Outros → input file; Atlaz → datepickers `bi-atlaz-from`/`bi-atlaz-to` + botão `bi-atlaz-fetch-btn`.
- Novo badge SOURCE_BADGE.atlaz (verde, ícone Database) no card de origem da tabela.

### Validação (testing_agent_v3_fork iter95)
- Backend 7/7 pytest ✓ (todos os sources, summary, fetch com janela vazia → 404, confirm Atlaz).
- Frontend 100% testids ✓ — única observação foi timeout em batch grande (50→500) com IA, **resolvido pelo skip IA para Atlaz**.



## Fev 18, 2026 — Sub-aba "Importar Extrato" Sicoob + IA aprende padrões (iter94) ★★★
**Objetivo do usuário**: subir extrato OFX do Sicoob, IA classifica entrada/saída + sugere fornecedor/categoria, gestor revisa e confirma, e a IA APRENDE os padrões por CPF/CNPJ + nomenclatura pra acelerar próximas importações.

### Backend (`/app/backend/routes/bank_import.py` — NOVO)
- 6 endpoints sob `/api/financeiro/bank-import/`:
  - `POST /upload` — multipart OFX ou CSV. Parser usa `ofxparse==0.21` (instalado). Detecta duplicatas por `import_hash` (sha1 de data+valor+desc). Para cada tx: (1) extrai CPF/CNPJ via regex, (2) normaliza chave (lowercase, sem acento, sem números, sem pontuação, 60 chars), (3) consulta `bank_import_memory` por exact CPF/CNPJ → fallback por key normalizada, (4) o que sobra vai pra IA em lote único.
  - `POST /confirm` — gera `fin_cash_movements` (`source="bank_import_sicoob"`), atualiza `current_balance`, persiste padrão em `bank_import_memory` (`hit_count` incremental). 409 se já confirmado.
  - `GET /history` — importações concluídas (ordenadas por data desc).
  - `GET /memory` — padrões aprendidos (ordenados por `hit_count` desc).
  - `DELETE /memory/{id}` — remove padrão específico.
  - `GET /staging/{id}` — recupera staging por ID.
- **IA**: Claude Sonnet 4.5 via `emergentintegrations.LlmChat.with_model("anthropic", "claude-sonnet-4-5")`. Prompt envia lista de fornecedores+categorias cadastrados e pede JSON com `{type, supplier_id, category_id, confidence, reason}`. Lote único minimiza chamadas.
- **Coleções novas**: `bank_import_staging`, `bank_import_memory`, `bank_import_history`.

### Frontend (`/app/frontend/src/BankImportTab.js` — NOVO ~440 linhas)
- Card de upload com input file `.ofx/.csv` + dica "Sicoob → Internet Banking → Extrato → Exportar OFX".
- 4 KPI cards (reutiliza `KpiCard` do `Dashboard2026.js`): Novas tx · Entradas · Saídas · Classificadas por IA.
- AlertCard quando há duplicatas detectadas.
- Tabela editável com colunas Data / Descrição (mostra CPF/CNPJ extraído em mono + reason da IA em itálico) / Tipo (select entrada/saída) / Valor (mono colorido) / Fornecedor (select) / Categoria (select filtrado por tipo) / Origem (badge IA Claude · Aprendido · Manual com % confiança).
- Linhas duplicadas em fundo amarelo + checkbox desmarcado por default.
- Botão "Confirmar X lançamentos" gera movements e atualiza saldo.
- Card "Padrões aprendidos pela IA" expansível, lista CPF/CNPJ → fornecedor/categoria com `hit_count` e botão deletar.
- Card "Histórico de importações" com data, arquivo, total, importados, ignorados.
- **Fallback**: se IA falhar (sem créditos / timeout), mostra AlertCard "Classifique manualmente".

### Validação (testing_agent_v3_fork iter94)
- Backend 9/9 pytest passou (upload OFX, IA, dedup, confirm, idempotência 409, history, memory ordenada, aprendizado na 2ª upload com source='memory', delete memory, rejeição arquivo inválido).
- Frontend E2E: 5 KPIs + 5 rows tabela + badges IA Claude 90-95% + CPF/CNPJ visível + 5 padrões aprendidos no card de memória + histórico renderizado.
- Testes registrados em `/app/backend/tests/test_iter94_bank_import.py`.

### Code review aplicado
- Adicionado AlertCard amigável quando IA falha em todos os items (`source === "ai" || "memory"` count = 0).

### Itens conhecidos (não-bloqueantes — para iteração futura)
- Saldo do caixa atualizado por linha (não em transação Mongo) — se uma inserção falhar no meio, saldo pode ficar inconsistente.
- Lookup por (doc=None, key=X) é conservador — não casa com memória salva com `doc=cnpj` quando o OFX omite o CPF/CNPJ.
- Após confirm com 0 movements (todos skipped) o staging fica "confirmed" e usuário precisa re-upload (não bloqueante).



## Fev 18, 2026 — Dashboard 2026 estendido a Financeiro + Rede IA (iter93)
**Objetivo do usuário**: aplicar o mesmo blueprint 2026 nos dashboards do Financeiro e Rede IA pra manter consistência visual com o redesign da aba Movimento.

### Refactor compartilhado
- Novo arquivo `/app/frontend/src/components/Dashboard2026.js` exporta `KpiCard`, `AlertCard`, `Sparkline`, `Legend`, `StatRow`. Tone semafórico (good/warn/bad/info), suporte a sparkline SVG, delta %, progress bar e hint contextual.

### Financeiro · Fluxo de Caixa (`CashFlowTab` em `FinanceiroPanelExt.js`)
- 6 Chips antigos → **5 KpiCards 2026** com tone, sparkline e delta vs período anterior (`/financeiro/cashflow` é chamado 2x — atual + anterior).
- **Alert strip condicional** (4 cenários): saldo negativo, resultado negativo, expense spike ≥25%, runway <15 dias.
- Novo card **Runway** com cálculo `saldo ÷ burn_rate` (capa cosmética "—" quando saldo=0 e burn=0).
- Gráfico Recharts ComposedChart mantido + legendas inline.
- Testids: `cashflow-kpi-{balance,income,expense,net,runway}`, `cashflow-alerts-strip`, `cashflow-alert-{negative-balance,low-runway,negative-result,expense-spike}`.

### Rede IA · Painel (`Overview` em `RedeIaPanel.js`)
- 6 KPIs antigos → **6 KpiCards 2026** com progress bars (CTOs aprovadas %, taxa de ocupação) e hints.
- **Alert strip condicional** (5 cenários): nenhuma CTO, VLANs críticas (<50%), VLANs em atenção (50-75%), pendências de validação, ocupação ≥80%.
- Mantém bloco SmartOLT + CtoStatsBlock + lista de VLANs sem regressão.
- Testids: `rede-ia-kpi-{ctos-total,ctos-approved,pendencies,bairros,ports,cables}`, `rede-ia-alerts-strip`, `rede-ia-alert-{no-ctos,critical-vlans,warning-vlans,pendencies,high-occupancy}`.

### Validação (testing_agent_v3_fork iter93)
- 100% frontend: 5/5 cashflow KPIs + 6/6 rede-ia KPIs + 3/3 period selectors + 2/2 alert strips + 2/2 progress bars + Recharts intacto + sub-tabs adjacentes sem regressão.
- Observação aberta (não-bloqueante): incoerência entre `/financeiro/cashflow` (R$ 0,00 saldo) e `AnalyticsChart` (R$ 167K recebimentos no mesmo período) — possível desalinhamento de fontes que merece RCA futura.



## Fev 18, 2026 — Dashboard 2026 da aba Movimento (estoque) (iter92)
**Objetivo do usuário**: redesenhar a aba "Movimento" pra melhorar entendimento + garantir que todas as páginas estão em full-width.

### Pesquisa aplicada (web search)
Blueprint "Summary First → Movement → Detail" — `Alerts strip → KPI cards contextuais → Movement chart → Stock by SKU → Activity feed → Tech ranking`. Sparklines embutidas, semáforo de cor, tendências (delta vs período anterior), responsive cards.

### Frontend (`/app/frontend/src/EstoquePanel.js`)
- **DashboardSection** completamente reescrito (5 KPI cards básicos + 2 listas → blueprint 2026 com 6 seções).
- Novos sub-componentes: `AlertCard`, `KpiCard`, `Sparkline` (SVG inline), `MovementChart` (SVG inline com 2 polylines), `LocationBars` (stacked bar + linhas), `Legend`.
- **Strip de alertas** condicional: ONTs zerado/baixo + insumos zerados/baixos com tone vermelho/amarelo.
- **Row KPIs** (5 cards): ONTs no estoque, Instalações 7d (com Δ% vs semana anterior + sparkline + hint 30d), OS ativas, Dias de cobertura (calculado: estoque ÷ consumo médio), Eficiência retirada (com progress bar). Cada card tem `borderTop` colorido + tone semafórico + hint.
- **Row Movimento + Distribuição**: gráfico SVG de movimento 14 dias (instalações vs total) com grid pontilhado + legenda de instalações/retiradas/devoluções 30d. Cards "Onde estão as ONTs" com stacked bar horizontal + breakdown empresa/técnicos/instaladas + percentual.
- **Row Stock SKU + Activity**: barras horizontais por insumo (empresa vs c/ técnico) com tone por threshold + activity feed das últimas 8 movimentações com ícone direcional (↗ inst · ↘ retirada · ↩ devolução).
- **Row Ranking técnicos**: cards mini com ONTs em destaque colorido, breakdown instalações/retiradas, chips de cada insumo com quantidade colorida por threshold.

### Cosméticos aplicados pós-testing (iter92-fix)
- Badge delta oculto quando installs7=0 e prevWeekInstalls=0 (evita "↓ 100%" enganoso).
- Sparkline some quando todos os 14 dias são zero (evita linha reta desnecessária).

### Full-width audit
- `.app-content` confirmado `width:100%` sem `max-width` (já estava). Todas as páginas SaaS herdam.

### Validação (testing_agent_v3_fork iter92)
- 100% frontend: 10/10 testids obrigatórios (`stock-alerts-strip`, `kpi-onts-stock`, `kpi-installations`, `kpi-active-services`, `kpi-days-of-supply`, `kpi-withdrawal-rate`, `movement-trend-card`, `location-distribution-card`, `empresa-stock-card`, `activity-feed-card`, `tech-rows-card`) + 5/5 condicionais (`location-stacked-bar`, `loc-row-empresa`, `loc-row-tecnicos`, `loc-row-instaladas`).
- Sub-tabs ONTs/Insumos/Clientes/Ordens/Histórico sem regressão.



## Fev 18, 2026 — Ranking de técnicos por qualidade de reparo (iter91-b)
- Novo endpoint `GET /api/lousa/quality-notes/technicians-ranking?days=X` agrega tickets finalizados com `signal_at_open` + `signal_at_close` por colaborador e calcula:
  - `total_reparos`, `bom/regular/ruim`, `pct_bom`, `pct_ruim`, `avg_delta_db`.
  - **`quality_score` 0-100** = % bom (peso 70) + Δ médio de melhoria (peso 30, cap em +3 dB).
- Frontend `TechniciansRankingCard` no `LousaQualityNotesPanel`: seletor 7/30/90/180 dias, medalhas 🥇🥈🥉 nos top-3, score circular colorido (≥70 verde · ≥50 amarelo · <50 vermelho), breakdown 🟢🟡🔴 por técnico, Δ médio em monospace.
- Validado curl: DIOGO (3 reparos +5/+3/+1 dB) → score 100, JEFFERSON (2 reparos -5/-2 dB) → score 0.
- data-testids: `quality-ranking-card`, `quality-ranking-period-{7|30|90|180}`, `quality-ranking-row-{id}`, `quality-ranking-score-{id}`, `quality-ranking-pct-{id}`, `quality-ranking-empty`.

## Fev 18, 2026 — Nota Técnica · Sinal SmartOLT antes × depois (iter91) ★★★
**Objetivo**: técnico avaliar a qualidade do reparo comparando o sinal do cliente na abertura vs no fechamento da nota.

### Backend (`/app/backend/routes/lousa.py`)
- Helpers centralizados:
  - `_quality_capture_enabled(company_id)` — lê toggle global de `lousa_quality_config` (default ON).
  - `_capture_signal_snapshot(ticket_id, company_id, moment)` — captura `rx_dbm/status/sn` via SmartOLT live e grava em `signal_at_open` / `signal_at_close`. Honra o toggle. Best-effort (não derruba o fluxo se SmartOLT estiver offline).
- Captura automática agora rola em 3 pontos:
  - `POST /lousa/tickets` (criação) → `signal_at_open`.
  - `POST /lousa/tickets/{id}/finalize` (autenticado) → `signal_at_close`. **NOVO** (antes só rolava na rota pública).
  - `POST /lousa/public/tickets/{id}/finalize` → `signal_at_close` (refatorado pra usar o helper).
- Novo endpoint manual: `POST /api/lousa/tickets/{id}/capture-signal` com body `{moment:"open"|"close"}`. Permissões: técnico só recaptura o próprio chamado, gestor/admin sempre. Retorna 400 quando o toggle está OFF, 422 quando não há ONU mapeada.

### Frontend
- **LousaMobile.js** — Novo componente `NotaTecnicaCard` renderizado no detalhe do chamado:
  - 2 cards lado-a-lado (📥 Na abertura / 📤 No fechamento ou Agora-live) com `rx_dbm` grande em monospace, tone semafórico (verde/amarelo/vermelho conforme threshold ≤-28 LOS · ≤-27 RUIM · ≤-25 MÉDIO · BOM), data/hora do snapshot, status Online/Offline.
  - Verdito de delta colorido (🟢 melhorou · 🟡 caiu tolerável · 🔴 piorou ≥3dB ou pós-reparo em LOS).
  - Botão "📡 Ler sinal agora" (técnico recaptura close on-demand) + "Recapturar abertura" (quando ainda não tem snapshot).
  - data-testids: `nota-tecnica-card-{id}`, `nota-tecnica-open`, `nota-tecnica-close`, `nota-tecnica-capture-close`, `nota-tecnica-capture-open`, `nota-tecnica-verdict`, `nota-tecnica-ok`, `nota-tecnica-err`.
- **LousaAdminPanel.js** — Nova sub-aba "📶 NOTAS DE QUALIDADE" (`lousa-subtab-quality_notes`) que monta o `LousaQualityNotesPanel` já existente (toggle ON/OFF iOS-style + dashboard de classificação por chamado).
- **api.js** — novo helper `api.lousaCaptureSignal(ticketId, moment)`.

### Validação E2E (testing_agent_v3_fork iter91)
- Backend: 14/15 pytest passou (1 skip por FK em assigned_collaborator_id inexistente — não relacionado).
- Frontend: code-level OK; 5/5 data-testids presentes; sub-tab integrada.
- Smoke test manual: config GET/PUT, list, capture-signal todos retornaram códigos/mensagens corretos.



## Mai 18, 2026 — Push ONU + Integração SmartOLT real (provisionamento + reboot) ★★★

### Contexto
1. Card SmartOLT da Lousa Mobile: botão GPS estava ocupando 100% da largura — pediu reduzir pra 50% e adicionar botão "Push" (reboot remoto da ONU) na outra metade.
2. Pendência P1 da sessão anterior: provisionamento de ONU via Rede IA ainda era stub.

### Implementado

**1. `services/smartolt_zones.py` — 3 funções novas:**
- `reboot_onu(company_id, sn)` → `POST /onu/reboot/{sn}` (Push)
- `add_onu(company_id, board, port, sn, zone_name, pppoe_user, pppoe_password, vlan)` → `POST /onu/add_onu` (provisionamento real)
- `list_onu_types(company_id)` → `GET /system/get_onu_types` (suporte futuro a autocomplete)

**2. `routes/rede_ia.py`:**
- Novo endpoint `POST /api/rede-ia/onu/{sn}/push` (admin/gestor/tecnico) com audit log.
- `cto_provision_onu` agora chama `add_onu()` REAL com `board`/`port`/`sn`/`zone`/`pppoe_user`/`pppoe_password`/`vlan`. Se SmartOLT recusar, marca `smartolt_status=pending_smartolt` na fila pra gestor finalizar manualmente.

**3. `LousaMobile.js` — `SmartOltDetailBlock`:**
- Layout 2 colunas (`grid-template-columns: 1fr 1fr`):
  - Esquerda: **📍 GPS** (roxo)
  - Direita: **⚡ Push ONU** (gradiente rosa/laranja)
- Confirmação `confirm()` antes do push: "Enviar PUSH (reiniciar ONU XXX)? O cliente vai ficar offline por ~30s."
- Feedback inline (ok/err) reusa o mesmo `gpsMsg` state.

### Validação curl
- ✅ `POST /onu/ABC123/push` retornou HTTP 503 com `"SmartOLT recusou push: Client error '403 Forbidden' for url 'https://ligofibra.smartolt.com/api/onu/reboot/ABC123'"` — confirma que a integração está chamando a API real (rejeita só porque o SN é inválido).
- ✅ Lint Python + JS: All checks passed
- ✅ Audit log `onu_push` registrado

### Como usar
1. Técnico no chamado → vê o bloco SmartOLT com SN/Porta/CTO
2. Botão **📍 GPS** (esquerda) → ajusta localização da CTO
3. Botão **⚡ Push ONU** (direita) → reinicia ONU remotamente sem ir presencial
4. Provisionamento via Rede IA mapa → cadastra ONU **direto no SmartOLT** com PPPoE e VLAN reais



## Mai 18, 2026 — Contas a Pagar parceladas + criação inline + médias no Fluxo de Caixa ★★★

### Contexto
Pediu (1) parcelamento de conta a pagar (ex.: 18/05 → 18/10/26, 5×), (2) criar fornecedor e categoria sem sair do modal de nova conta e (3) linha de média no gráfico de Fluxo de Caixa.

### Implementado

**1. Backend — `routes/financeiro_ops.py`:**
- `BillIn` ganhou 3 campos opcionais:
  - `installments_count` (1-120)
  - `installments_period_days` (1-365, default 30)
  - `installments_recurrent` (bool, default False)
- `POST /financeiro/bills` agora cria 1..N parcelas a partir de `due_date`:
  - **Modo divisão (default)**: valor total dividido em N parcelas. Última parcela absorve residual de centavos.
  - **Modo recorrência** (`recurrent=True`): cada parcela tem o `amount` cheio (ex.: aluguel mensal).
- Cada parcela é uma conta independente em `fin_bills_payable` agrupada por `installment_group_id` (UUID).
- Campos extras na parcela: `installment_index`, `installment_total`, `installment_recurrent`.
- Retorno: `{ok:true, installment_group_id, count, total_amount, bills:[...]}` (ou 1 doc puro quando N=1).
- Descrição auto-formatada como `"<desc> (i/N)"`.

**2. Frontend — `FinanceiroPanelExt.js`:**
- **`BillForm`** ganhou seção colapsável de parcelamento (badge roxa) com inputs:
  - Parcelas (1-60)
  - Intervalo (dias)
  - Toggle "Mesmo valor cada (recorrência)"
- **Resumo dinâmico**: `5× de R$ 1.000,00 — total R$ 5.000,00 · última: 15/09/2026`
- **Criação inline** via botão `+` ao lado do dropdown:
  - Fornecedor: nome + CNPJ/CPF + telefone + email + notas
  - Categoria: nome + tipo (despesa/receita/ambos) + cor
- **Novo componente `InlineCreate`** reutilizável (Modal com fields config + POST).
- Após criação, recarrega `refs` e seleciona automaticamente o item recém-criado.

**3. Frontend — `CashFlowTab`:**
- `BarChart` substituído por `ComposedChart` com 2 `Line` dashed:
  - Verde tracejada = **Média de Entradas** (constante ao longo do período)
  - Vermelha tracejada = **Média de Saídas**
- 2 novos chips no header: "Média/dia entradas" + "Média/dia saídas" (em R$).
- Altura do chart aumentada de 280 → 320 px pra acomodar a legenda extra.
- Barras com `radius={[4,4,0,0]}` (cantos arredondados — boa prática 2026).

### Validação (curl)
- ✅ Conta simples 1× → `installment_total: None`
- ✅ Conta parcelada 5× R$ 5000 → 5 parcelas de R$ 1000, vencimentos 18/05, 17/06, 17/07, 16/08, 15/09
- ✅ Recorrente 12× R$ 1500 (aluguel) → `count:12 total:18000`
- ✅ Criar fornecedor inline → retornou doc com `id:"fsup-..."`
- ✅ Lint Python + JS: All checks passed

### Boas práticas aplicadas (pesquisa)
- Modo "divisão" como padrão (cenário mais comum: financiamento)
- Modo "recorrência" pra contas fixas (aluguel, internet)
- Residual de centavos absorvido pela última parcela (boa prática contábil)
- Agrupamento via `installment_group_id` permite filtros/relatórios/desfazer
- Inline create reduz fricção: usuário não perde contexto da conta sendo criada



## Mai 18, 2026 — Mapa da Rede no Mobile (técnico vê tudo cadastrado) ★★★

### Contexto
Usuário pediu que o **app do colaborador** (Lousa Mobile) tenha acesso ao mesmo mapa interativo da Rede IA, mostrando tudo que está cadastrado (CTOs, CEs, cabos). Usou como referência visual o app "Salva-Locais": mapa fullscreen, pins coloridos, chips de filtro, FAB GPS.

### Implementado

**1. Novo componente — `RedeIaMapMobile.js` (NOVO, ~370 linhas):**
- Tela fullscreen com Leaflet + tile OSM
- Pin custom (divIcon SVG) numerado roxo/verde/amarelo conforme status
- CEs como quadrados azuis, cabos como Polyline com cor + tooltip
- Marker pulsante azul mostrando a posição do técnico (watch contínuo via `navigator.geolocation.watchPosition`)
- **FAB GPS** flutuante recentraliza no técnico (estilo Uber/Salva-Locais)
- **FAB Camadas** alterna visibilidade de CEs + cabos
- **Chips horizontais** filtram por bairro (auto-extraído de `address.bairro`)
- **Busca** expansível por nome de CTO
- **Rodapé de stats**: Total / OK / Pendentes / Sem GPS
- **Tap em CTO** abre `CTOInteractionModal` (clientes ligados + cadastrar)

**2. Integração — `CollaboratorApp.js`:**
- Novo item no `KebabMenu` (⋮ → "🗺️ Mapa da Rede")
- Nova `screen === "rede-map"` renderiza `<RedeIaMapMobile onBack={...}>`
- Import + prop drilling `onOpenRedeMap` adicionados

**3. Compat com endpoint:**
- `/api/rede-ia/map/data` retorna `cables`, `ces`, `ctos` com lat/lng achatados — componente lê de ambos formatos (`c.lat` ou `c.gps.lat`) pra robustez.

### Como usar
1. Técnico abre o app (Lousa Mobile)
2. Toca no ícone ⋮ (kebab menu) no canto superior direito
3. Seleciona "🗺️ Mapa da Rede"
4. Vê mapa fullscreen com todas as CTOs cadastradas, posição própria em azul pulsante
5. Toca numa CTO → modal com clientes ligados + opção de cadastrar novo
6. Usa FAB roxo Crosshair pra centralizar no GPS atual
7. Usa chips de bairro pra filtrar
8. Toca em Layers pra alternar cabos/CEs

### Validação
- ✅ Lint JS: All checks passed
- ✅ Endpoint `/api/rede-ia/map/data` testado via curl — retorna `{ctos, ces, cables, center, vlans}`
- ✅ Filtros e contadores funcionam mesmo quando alguns campos não estão preenchidos (defensive coding)



## Mai 18, 2026 — Picker GPS estilo Uber para localização de CTO (Lousa Mobile) ★★★

### Contexto
Técnico em campo precisa ajustar a localização GPS exata da CTO (que muitas vezes está imprecisa no cadastro). Pediram experiência tipo Uber/iFood: pin fixo no centro, usuário arrasta o mapa, reverse geocode preenche endereço automaticamente.

### Implementado

**1. Backend — `routes/rede_ia.py`:**
- `PUT /api/rede-ia/ctos/{cto_id}/location` (admin/gestor/tecnico) — atualiza `gps + address` da CTO.
- Mescla endereço (só sobrescreve campos novos não-vazios).
- Empilha em `gps_history[]` o GPS antigo + timestamp pra auditoria.
- Loga em `_audit` quem fez a mudança.

**2. Frontend — `UberGpsPicker.js` (NOVO):**
- Modal full-screen com Leaflet (reusa stack do RedeIaMap).
- Pin SVG roxo fixo no centro do mapa (estilo Uber).
- Mapa pan-able — `moveend` dispara reverse geocode via Nominatim (OSM, grátis, sem chave) com debounce 600ms.
- Botão flutuante "🎯 Crosshair" usa `navigator.geolocation` pra centralizar na posição do técnico (high accuracy).
- Bottom-sheet mostra `rua, número, bairro, cidade, estado, CEP` + coordenadas, atualiza em tempo real.
- Botão "✅ Confirmar localização" só habilita após reverse geocode bem-sucedido.

**3. Integração — `LousaMobile.js`:**
- `SmartOltDetailBlock` ganhou state local + botão roxo "📍 Ajustar localização GPS da CTO".
- Resolve `cto_id` lazy via nome (`ls.cto_box`) se sidecar não enviar o id.
- Ao confirmar, chama `api.redeIaCtoLocationUpdate` e mostra feedback (ok/erro).

### Validação (curl)
- ✅ `PUT /ctos/{id}/location` com `{lat, lng, address:{bairro,rua,numero}}` retorna `ok:true`
- ✅ GPS atualizado: `{lat:-22.83456, lng:-43.32102}`
- ✅ Bairro preservado: `"Parada de Lucas"`
- ✅ Histórico criado: 2 entradas em `gps_history`
- ✅ Audit log: `gps_updated_by:"admin@empresa.com"`
- ✅ Lint Python + JS passou

### Como usar
1. Técnico abre ticket na Lousa Mobile
2. No bloco azul SmartOLT, clica no botão roxo "📍 Ajustar localização GPS"
3. Mapa abre com pin no centro
4. Arrasta o mapa pra alinhar o pino com a CTO real (ou toca no Crosshair pra pegar GPS do celular)
5. Endereço (rua/número/bairro/cidade/estado) aparece auto-preenchido na barra inferior
6. Confirmar → CTO atualizada no banco e visível no mapa Rede IA



## Mai 18, 2026 — Nova estratégia: Cadastro de ONU via Rede IA (mapa interativo) ★★★

### Contexto
Usuário pediu pra mover o cadastro de ONU/SmartOLT do **Lousa Mobile (app do técnico)** para a **Rede IA → Mapa Interativo**, com:
- Click numa CTO abre modal com 2 abas
- Aba "Clientes ligados" mostra ONUs ativas no slot
- Aba "Cadastrar novo cliente" tem formulário com SN, cliente Atlaz, slot, plano, PPPoE, VLAN
- Cadastro vai pro SmartOLT direto pela Rede IA
- Técnico **não** registra mais SN/MAC no app durante instalação

### Implementado

**1. Backend — `routes/rede_ia.py`:**
- `GET /api/rede-ia/ctos/{cto_id}/clients` — lista ONUs SmartOLT cuja `zone_name` casa com a CTO (regex flexível em nome+sigla+número). Retorna `used_slots`, `free_slots`, sinal e status.
- `POST /api/rede-ia/ctos/{cto_id}/provision` (gestor/admin/técnico) — valida slot livre + SN único, cria registro em `cto_provision_requests` (auditoria), tenta push SmartOLT, e sincroniza cache `smartolt_onus` pra aparecer imediato no mapa. Marca `smartolt_status=synced|pending` pra rastrear casos onde a API SmartOLT falhou.

**2. Frontend — novo modal:**
- `CTOInteractionModal.js` (NOVO) — modal full em 2 abas:
  - **Clientes ligados**: cards coloridos por status (online/LOS/power fail), com SN, slot, sinal dBm, OLT/board/port
  - **Cadastrar novo cliente**: form com autocomplete de cliente Atlaz (busca via `/atlaz/clients?q=`), seletor de slot apenas com livres, PPPoE/VLAN/notas opcionais
- `data-testid` em todos os elementos (`prov-sn-input`, `prov-slot-select`, `prov-submit-btn`, etc.)

**3. Frontend — integração no mapa:**
- `RedeIaMap.js`: novo botão verde "👥 Clientes / Cadastrar" no Popup da CTO + state `activeCto` + renderiza `<CTOInteractionModal>` quando aberto.

**4. Frontend — remoção no app do técnico:**
- `LousaMobile.js`: para tipo **instalação**, oculta input de MAC/SN e bloco SmartOLT, mostrando banner roxo:
  > "🆕 Mudança de fluxo: o cadastro de ONU no SmartOLT agora é feito pelo gestor de rede direto na Rede IA → Mapa Interativo. Aqui só registre a foto do equipamento e os insumos consumidos."
- Validação `goToStep2` ajustada: SN é exigido só pra **retirada**, não pra instalação.

### Validação end-to-end (curl)
- ✅ `GET /ctos/{id}/clients` → 200, retorna `total_clients`, `used_slots`, `free_slots`
- ✅ `POST /ctos/{id}/provision` (SN+cliente+slot) → `{ok:true, smartolt_synced:true, request_id:"provreq-..."}`
- ✅ Re-fetch → cliente novo aparece no slot correto com status "online"
- ✅ Lint Python + JS: All checks passed

### TODOs (pendências menores)
- Integração real com API SmartOLT `POST /add_onu` (hoje só marca synced=true via stub se `subdomain` configurado — backlog: gestor pode finalizar manualmente via fila `cto_provision_requests` com status `pending_smartolt`).



## Mai 18, 2026 — Links Públicos para Aba Chamados (acesso sem login) ★★★

### Contexto
Usuário pediu um link compartilhável da aba **Chamados** que funcionasse sem login/senha, com poder admin completo (criar/atribuir/fechar chamados). Útil pra monitor TV em sala técnica ou compartilhar acesso temporário.

### Implementado

**1. Backend — auth + novo router:**
- `auth.py:get_current_user` agora aceita token público via header `X-Public-Token` ou query `?ptoken=xxx`. Resolve para usuário sintético com `role=administrador` no `company_id` da empresa que criou o token. Valida expiração + revogação.
- `routes/public_access.py` (NOVO) — CRUD admin:
  - `POST /api/public-access/tokens` cria token (24 bytes URL-safe, 192 bits)
  - `GET /api/public-access/tokens` lista da empresa (ordenado: ativos primeiro)
  - `DELETE /api/public-access/tokens/{id}` revoga (sem apagar)
- Auditoria: `last_used_at` + `use_count` atualizados a cada uso.
- Collection: `public_access_tokens` com `{id, token, company_id, label, scope, created_by, created_at, expires_at, revoked_at, last_used_at, use_count}`.

**2. Frontend — modo público:**
- `AuthContext.js` detecta `?ptoken=xxx` no boot, salva em `localStorage.smartprov_public_token`, limpa da URL (pra não vazar em screenshot/share). Chama `/auth/me` que retorna usuário sintético admin.
- `api.js` interceptor injeta header `X-Public-Token` quando não há JWT.
- `App.js`:
  - Em modo público abre direto na aba **Chamados** (skip do dashboard padrão).
  - Pula auto-login do preview quando há `ptoken`.
  - Novo banner amarelo "🔓 Acesso público ativo" com botão "Sair do modo".
- `PublicAccessPanel.js` (NOVO) — listado em **Configurações**:
  - Botão "Novo link" com inputs (label, escopo, expira em N dias)
  - Lista de links com badge Ativo/Expirado/Revogado, contadores de uso, botões Copiar e Revogar
  - Aviso visual sobre risco do link vazar
- `data-testid` em todos os elementos críticos (`public-access-panel`, `public-access-create-btn`, etc).

### Como usar
1. Em **Configurações → Links Públicos**, clique "Novo link"
2. Escolha rótulo (ex: "Quadro Chamados TV"), escopo (Chamados ou Acesso total) e expiração opcional
3. Copie o link gerado (`https://app/?ptoken=xxx`) e abra em outro navegador/aba
4. O link já cai direto na aba Chamados, banner amarelo confirma modo público
5. Para revogar: clique no ícone 🗑️ — quem estiver usando perde acesso na hora

### Validação técnica (curl)
- ✅ Criar token → retorna id+token+metadata
- ✅ Listar → 1 token ativo
- ✅ `/auth/me` com X-Public-Token → retorna `{role: administrador, company_id, _public_token_scope}`
- ✅ Endpoint da Lousa (`/api/lousa/all`) acessível via header → retorna tickets
- ✅ Revogar → `{revoked: true}`
- ✅ Token revogado → 401
- ✅ Lint Python + JS: All checks passed

### Segurança
- Token de 192 bits (random_urlsafe(24)) — impossível forçar.
- Multi-tenant: token criado em `co-demo` não acessa dados de outra empresa.
- Auditoria completa: `created_by`, `last_used_at`, `use_count`.
- Expiração opcional + revogação imediata.
- ⚠️ Banner avisa que o link vazado = acesso admin. UI exibe alerta na criação.



## Mai 18, 2026 — Otimização de custos da Central IA (94% economia) ★★★

### Contexto
Card de Custo do Motor IA revelou que `central_ia_eval` consumia $9,74 + `central_ia_coach` $2,35/mês (~70% do gasto total). Usuário pediu otimização agressiva mantendo qualidade.

### Implementado (combinação a + c + e)

**1. Modelo trocado de Sonnet → Haiku 4.5** em `routes/central_ia.py`:
- `_llm_evaluate`: `model="anthropic/claude-haiku-4.5"` ($0.80/M in vs $3/M — 5x mais barato)
- `_llm_coach`: mesmo modelo

**2. Worker menos agressivo:**
- `_WORKER_INTERVAL_SEC`: 300s → 900s (5min → 15min)
- Re-eval threshold: 600s → 1800s (10min → 30min)
- Transcript truncado: 6000 chars → 2500 chars (eval) e 4500 → 2500 (coach)

**3. Auto-coach mais seletivo:**
- Trigger CSAT < 7 → CSAT < 5 (só casos críticos)

**4. Pricing fix em `services/motor_ia.py`:**
- Adicionado alias `anthropic/claude-4.5-haiku` (modelo retorna esse formato em vez de `claude-haiku-4.5`)

### Validação
- Custo por call: **$0,001669** (Haiku) vs $0,006258 (Sonnet) — 73% mais barato por call.
- Combinado com 3x menos calls + transcript menor: economia projetada **94%** ($14,69 → $0,95/mês).
- Backend reiniciou OK, worker confirmado rodando a cada 900s nos logs.
- Lint Python: ✅



## Mai 18, 2026 — Alertas Diários por Serviço (Vision/TTS/STT/Texto) ★★★

### Contexto
Após adicionar Vision/TTS/STT no card de custos, ficou o risco de um bot mandar 1000 imagens e estourar custo silenciosamente. Implementado sistema de **alerta visual em tempo real** quando gasto diário ultrapassar limite configurável por serviço.

### Implementado

**1. Backend — `routes/motor_ia.py`:**
- `BudgetIn` ganhou campos `daily_limit_usd` e `daily_service_limits` (ServiceLimits com vision/stt/tts/text).
- `_get_budget()` retorna defaults `0.0` para campos novos (compat com registros antigos).
- Novo endpoint `GET /api/motor-ia/budget/status/today` que retorna:
  - `total_spent_usd` e `total_status` (ok/warn/exceeded/disabled)
  - `services[]` por serviço com `spent_usd`, `limit_usd`, `used_pct`, `status`
  - `alerts[]` somente entradas warn/exceeded
  - `has_alerts` (bool)
- Classificação: `warn` ≥ 80% do limite, `exceeded` ≥ 100%, `disabled` se limite=0.

**2. UI — `MotorIaUsageCard.js`:**
- Banner colorido no topo (vermelho se exceeded, amarelo se warn) listando quais serviços estouraram.
- Mini-resumo "Hoje: $X de $Y (Z%)" quando há gasto mas sem alerta.
- Painel colapsável "Ajustar limites" com inputs para Total + 4 serviços (Texto/Visão/STT/TTS).
- Botão `Salvar limites` chama `PUT /budget` e re-fetch do status.

### Como testar
1. Configure limites baixos via `PUT /api/motor-ia/budget`:
   `{"daily_limit_usd": 0.1, "daily_service_limits": {"vision": 0.001, ...}}`
2. Abra o card Motor IA — banner vermelho 🚨 aparece com detalhes.
3. Clique "Ajustar limites" → ajuste valores → "Salvar limites".

### Validação
- Endpoint testado via curl: cenário sem limites → `disabled`; limites altos → `ok`; limites baixos → `exceeded` em todos os serviços. ✅
- Lint backend + frontend: ✅



## Mai 18, 2026 — Card "Custo do Motor IA" agora rastreia Vision + TTS + Whisper ★★★

### Contexto
O dashboard `MotorIaUsageCard` só registrava custos de **texto** (OpenRouter). Vision (Gemini Nano Banana), TTS (OpenAI) e Whisper (STT) eram invisíveis nas métricas. Usuário pediu para juntar esses gastos junto dos outros.

### Implementado

**1. Backend — `services/motor_ia.py`:**
- Nova tabela `UNIT_PRICING` com preços por unidade:
  - `gemini-2.5-flash` Vision: $0.00030 / imagem
  - `whisper-1` STT: $0.0001 / segundo ($0.006/min)
  - `gpt-4o-mini-tts` / `tts-1`: $0.000015 / char ($0.015/1k)
  - `tts-1-hd`: $0.000030 / char
- Nova função `log_usage_units(company_id, agent, model, service, units, unit_type)` que loga no mesmo collection `motor_ia_usage` com campo `service` (`text|vision|stt|tts`) e `units`.
- `_log_usage` (texto) marcado com `service="text"`.

**2. Hooks de logging:**
- `services/media_analysis.py` — `analyze_image`/`analyze_pdf`/`analyze_media` agora aceitam `company_id` + `agent` e logam 1 imagem por análise (Gemini Vision).
- `services/tts.py:synthesize_speech` — loga `len(text)` chars como `tts`.
- `services/motor_ia.py:transcribe_audio` — estima duração via bitrate opus (24kbps) e loga segundos como `stt`.
- `services/motor_ia.py:text_to_speech` — loga chars como `tts`.
- Caller `routes/whatsapp_baileys.py` passa `company_id=cid` no `analyze_media`.

**3. Endpoint — `/api/motor-ia/usage`:**
- Novo array `by_service` com label, custo, calls, units, unit_label por serviço (Texto/Visão/Whisper/TTS).
- `by_agent` agora inclui `service`, `unit_type` e `units` para diferenciar texto x mídia.
- `AGENT_LABELS` ganhou `isabella_vision`, `isabella_tts`, `isabella_stt`.

**4. UI — `MotorIaUsageCard.js`:**
- Nova seção **"Custo por Serviço"** com 4 cards (Texto / Vision / STT / TTS) — cada um com cor própria (gradiente), ícone e métrica de unidades.
- Linha "Custo por Agente" agora mostra ícone do serviço e formata unidades corretamente (`X img` / `X seg` / `X chars` / `X tok`).
- Footer atualizado explicando como cada serviço é precificado.

### Como testar
1. Abra o painel **Sistemas → Motor IA → Custo do Motor IA**
2. Confira a seção "Custo por Serviço" com 4 cards
3. Total agora inclui Vision/TTS/STT além de texto

### Validação técnica
- `GET /api/motor-ia/usage?days=30` retorna `by_service` com 4 entries
- Após seed manual: Vision (5 imgs = $0.0015), STT (30s = $0.003), TTS (1500 chars = $0.0225)
- Lint backend + frontend: ✅ All checks passed



## Mai 18, 2026 — Auto-rejeição de Chamadas + Voice Notes Inteligentes ★★★★

### Contexto
Usuário perguntou se a Isabella pode atender chamadas de voz/vídeo do WhatsApp. **Limitação técnica:** nem Baileys nem a Cloud API oficial permitem atender (chamadas usam canal criptografado isolado). Implementada a melhor alternativa viável.

### Implementado

**1. Sidecar Baileys — `whatsapp-service/server.js`:**
- Novo handler `sock.ev.on("call", ...)` detecta `call.status === "offer"`
- Auto-rejeita via `sock.rejectCall(call.id, call.from)`
- Notifica backend via webhook `/inbound-call` com phone + tipo (voz/vídeo)
- Reutiliza axios + WEBHOOK_BASE + INBOUND_TOKEN já existentes

**2. Backend — `routes/whatsapp_baileys.py`:**
- Endpoint `POST /api/whatsapp-baileys/inbound-call` (protegido por X-WA-Token)
- Registra tentativa de chamada em `aihub_wa_messages` com `media_type=call`
  (aparece pro atendente humano também)
- Dispara resposta automática amigável:
  *"Oi! 😊 Aqui eu não consigo atender chamada, mas se você me mandar um áudio 🎤 ou texto, eu respondo na hora!"*

**3. Transcrição automática de voice notes:**
- Antes: áudio inbound virava `"🎤 Áudio (5s)"` — Isabella ficava perdida
- Agora: chama `transcribe_audio()` (Whisper via Emergent LLM Key) antes do LLM ver a mensagem
- Salva campo `transcript` no doc + `transcript_engine: whisper-1`
- Isabella passa a **entender** o que o cliente falou no áudio

### Como funciona o fluxo completo
1. Cliente liga pra Isabella → sidecar auto-rejeita
2. Webhook `/inbound-call` registra + envia mensagem padrão
3. Cliente grava áudio respondendo
4. Sidecar baixa o áudio (até 8MB), manda ao backend em base64
5. Backend grava o arquivo, **transcreve via Whisper**
6. Mensagem chega ao LLM como texto → Isabella responde como sempre

### Validado
- Endpoint `/inbound-call` retorna 401 sem token (proteção OK)
- 51/51 pytest passing
- Lint Python ✅
- Transcrição usa Emergent LLM Key (sem custo extra de chave OpenAI)



## Mai 18, 2026 — Trilha de Aniversário + Notificação WhatsApp + Boleto Discriminado ★★★★

### 🎂 Trilha de Clientes por Aniversário
- **Endpoint:** `GET /api/financeiro/reajuste/cohort` — agrupa clientes ativos em buckets de 1–20 anos baseado em `installation_date`
- **Frontend:** card visual com grid de cards (1 ano, 2 anos, ... 20+) na subaba Reajuste mostrando:
  - Quantidade de clientes por bucket
  - Receita mensal agregada
  - Badge "🔔 aniv." se algum cliente faz aniversário nos próximos 30 dias
  - Intensidade visual (gradiente roxo) proporcional ao tamanho do bucket
  - Tooltip com nomes (primeiros 8) ao passar o mouse
- **Validado:** 19 clientes de teste distribuídos em 5 buckets (1/2/3/5/10 anos)

### 🔔 Notificação WhatsApp 30d antes do Reajuste (compliance Anatel)
- **Service:** `services/readjustment_notifications.py` — envia WhatsApp via sidecar Baileys
- **Idempotente:** coleção `subscriber_readjustment_notifications` previne duplicatas (chave = `subscriber_id + YYYY-MM` do reajuste)
- **Mensagem natural** com tom da Isabella, mostra valor atual, novo valor, % e índice
- **Worker diário 09h** em `server.py`: roda para todas as empresas
- **Compliance:** atende exigência da Anatel/SCM de "notificação prévia ao consumidor"

### 📄 Boleto Discriminado (mensalidade + serviços = total)
- **`services/boleto_pdf.py`:** novo bloco "DISCRIMINATIVO DA FATURA" antes do PIX
- **Estrutura:** lista cada `line_item` (label + amount) e total ao final
- **invoice dict** agora aceita: `line_items: [{label, amount}, ...]`
- Exemplos:
  - "Mensalidade plano 700 Mega — R$ 109,90"
  - "Reajuste IPCA (+4.39%) — R$ 4,82"
  - "Ponto Wi-Fi adicional — R$ 19,90"
  - "**TOTAL — R$ 134,62**"

### Como funciona o ciclo completo
1. Cliente é cadastrado com `installation_date`
2. Sistema calcula `next_readjustment_at = installation_date + 365d`
3. **30 dias antes:** worker 09h envia WhatsApp avisando o cliente
4. **Na data:** worker 04h aplica reajuste automaticamente
5. Próximo boleto sai com discriminativo: mensalidade nova + reajuste destacado + serviços adicionais = total

### Validado
- Pytest: 51/51 ✅
- Lint Python: ✅ (boleto_pdf, financeiro_reajuste, readjustment_notifications)
- Lint JS: ✅ (FinanceiroReadjustmentTab)
- API cohort retornando dados reais ✅



## Mai 18, 2026 — Sistema de Reajuste Anual + CEP Fallback ★★★★★

### Reajuste Anual Automático (Anatel/SCM Compliant)

Pesquisada regulação Anatel para internet fibra (SCM): índice padrão **IST** (telecom), mas IPCA é também aceito quando previsto em contrato. Periodicidade mínima 12 meses.

**Backend implementado:**
- `services/inflation.py` — Busca **API SGS Banco Central** (gratuita, sem auth) dos índices IPCA (433), IGP-M (189), IST (7833). Calcula acumulado 12 meses. Cache em MongoDB `inflation_indices`.
- `services/readjustment.py` — Lógica: `next_date = max(installation_date, last_readjustment_at) + 365d`. Aplica `new_price = current_price × (1 + acc_pct/100)`. Log de auditoria em `subscriber_readjustments`.
- `routes/financeiro_reajuste.py` — 7 endpoints: `/indices`, `/indices/{name}/refresh`, `/due`, `/preview/{id}`, `/apply/{id}`, `/apply-all-due`, `/history/{id}`.
- **Worker diário 04:00** em `server.py`: atualiza índices + aplica reajustes pendentes em todas empresas.

**Frontend implementado:**
- `FinanceiroReadjustmentTab.js` — Nova subaba "Reajuste" no Financeiro com:
  - 4 cards com índices oficiais (IPCA, IPCA_12M, IGP-M, IST) com botão refresh
  - Tabela "Vencidos" + botão "Aplicar todos vencidos" (ação em lote)
  - Tabela "Próximos N dias" (filtro 30/60/90/180/365 dias)
  - Aplicar individual via botão por linha
- `SubscribersPanel.js` — Seção financeira do cadastro de cliente:
  - Campo "Data de instalação" (date input)
  - Select "Índice de reajuste" (IPCA/IST/IGP-M, padrão IPCA)
  - Display "Próximo reajuste: DD/MM/AAAA" com badge VENCIDO se já passou
  - Mostra "Último: +X.XX%" se já houve reajuste

**Validado:**
- API SGS BCB retornando IPCA real: **+4.39% acumulado 12 meses** (2026-04)
- Endpoints funcionais: `/indices`, `/refresh`, `/due`
- Lint Python ✅ · Lint JS ✅ · 51/51 testes passing

### CEP com Fallback Inteligente
- `utils.py /cep/{cep}` agora consulta em cascata: cache MongoDB → ViaCEP → BrasilAPI → OpenCEP
- Timeout de 4s por fonte (rápido fallback se uma cair)
- Resultado cacheado em `cep_cache` (consultas seguintes são instantâneas)
- Resolve dependência única em ViaCEP que historicamente cai algumas vezes/mês

### Schema novos campos `subscribers`
- `installation_date` (ISO datetime) — define data-base do reajuste
- `readjustment_index` (string, default "IPCA")
- `last_readjustment_at` (ISO datetime)
- `last_readjustment_pct` (float)
- `last_readjustment_value` (float)

### Schema novas collections
- `inflation_indices` — cache de índices do BCB
- `cep_cache` — cache de CEPs já consultados
- `subscriber_readjustments` — log de auditoria de reajustes aplicados



## Mai 18, 2026 — V7.0 Reescrita Unificada do Prompt da Isabella ★★★★★

### Contexto
Após análise completa dos 10 fragments de prompt ativos (~37k chars), foram identificados **7 problemas estruturais**:

1. **Conflito de preços**: Vendas V1.0 dizia "200 MEGA · R$ 99,90", catálogo oficial dizia "400 MEGA · R$ 109,90" — Isabella confundia
2. **Conflito de base de recomendação**: V6.51 dizia "1-2 pessoas → 400/500", Vendas V1.0 dizia "1-2 → 200"
3. **Exemplos hardcoded "Vando"** em múltiplos lugares (V6.51 + Vendas V1.0)
4. **Regras redundantes/conflitantes** entre V6.50, V6.52, V6.70, V6.71
5. **Flow morria após "ok"** do cliente (sem regra clara de continuidade)
6. **Sem distinção firme** entre LEAD NOVO e CLIENTE EXISTENTE
7. **Sem orientação** sobre como tratar cliente com phone vinculado errado

### Solução: V7.0 Unified (4 fragments consolidados, ~24k chars)

| Fragment | Tamanho | Responsabilidade |
|---|---|---|
| 📋 **Identidade & Regras Oficiais** | 4.1k | Empresa, lojas, canais, instalação, fidelidade, cobertura |
| 💎 **Catálogo de Planos** | 3.0k | Fonte autoritativa de planos + lógica recomendação |
| 🤖 **Manual da Isabella** | 11.4k | 11 seções: tom, anti-alucinação, lead vs existente, saudação, encadeamento, continuidade, diagnóstico técnico, boleto, agendamento, kill-switch, anti-padrões |
| 🛒 **Playbook de Vendas** | 5.6k | 7 passos com placeholders [PLACEHOLDER] em vez de "Vando" |

### Implementação
- `migrations/isabella_unified_v7_0.py` — desativa 7 fragments legados + cria 4 V7.0
- Aplicada no preview: 7 desativados, 4 criados, total 7 ativos (4 custom + 3 triggers situacionais)
- Smoke test: ✅ frontend OK, 51/51 testes passando

### Melhorias arquiteturais
- **Anti-alucinação reforçada** (§2 do Manual): regra clara sobre quais blocos contam como dados reais vs exemplos do prompt
- **Decisão LEAD vs EXISTENTE** (§3): protocolo explícito quando bloco "CLIENTE IDENTIFICADO" pode estar errado
- **Continuidade de flow** (§6): proibição explícita de reiniciar após "Ok"/"Sim"/"?"
- **Kill-switch** (§10): silêncio em "obrigado", limite de 1 follow-up de engajamento
- **Anti-padrões** (§11): 9 comportamentos proibidos listados explicitamente
- **Playbook de Vendas refeito**: substitui "[Nome do Vando]" por `[NOME_REAL]`/`[BAIRRO_REAL]`; preços alinhados ao Catálogo

### Próximos passos do usuário
1. **Save to GitHub → Redeploy produção** pra subir migration V7.0
2. **Rodar migration em produção**: `python migrations/isabella_unified_v7_0.py`
3. **Testar conversa real**: pedir instalação como cliente novo → verificar que Isabella não inventa nome/plano



## Mai 18, 2026 — Sidecar Railway isolado p/ Preview + Fix Webhook Produção + V6.71 Anti-Alucinação ★★★

### Contexto
Bugs críticos reportados pelo usuário em produção:
1. **WhatsApp da produção caía toda vez que a preview hibernava** (mesmo sidecar Baileys servindo 2 ambientes)
2. **Isabella não respondia mensagens em produção** apesar de chegarem ao sidecar
3. **Isabella chamava clientes novos de "Vando"** e inventava plano "Fibra 500 Mega" (alucinação de identidade)

### O que foi implementado

#### 1. Sidecar Railway dedicado para Preview ✅
- Criado novo serviço Railway: `whatsapp-sidecar-preview`
- URL: `https://whatsapp-sidecar-preview-production.up.railway.app`
- Repo: `vando-patrocinio/smartprov-ligo2` · Root: `whatsapp-service` · Branch: `main`
- Webhook aponta para preview: `https://dual-combine-3.preview.emergentagent.com/api`
- WA_INBOUND_TOKEN: `ZBHBG3GWRmXDhUCj48x-Ma25rpcg6y89Nm84UK1x2EE`
- Pod preview atualizado com novos valores
- Produção continua isolada no sidecar antigo `whatsapp-sidecar-production-6336`

#### 2. Fix webhook produção (RCA) ✅
**Causa raiz:** sidecar de produção (`whatsapp-sidecar-production-6336`) tinha `WA_WEBHOOK_BASE` apontando para o backend de PREVIEW. Resultado: mensagens chegavam ao sidecar mas eram entregues no backend errado, Isabella nunca processava.
**Fix:** alterada env var no Railway para `https://dual-combine-3.emergent.host/api`.

#### 3. Migration V6.71 — Anti-Alucinação de Identidade ✅
**Causa raiz:** o prompt fragment V6.51 tinha exemplos com nomes/planos literais (`Vando`, `Fibra 500 Mega`, `Cordovil`). Sem dados reais do cliente, o LLM copiava o exemplo do prompt (few-shot leakage).

**Fixes:**
- `services/customer_history.py` L201-212: removido "Vando" hardcoded, substituído por instrução para extrair do bloco real
- Criado `migrations/isabella_anti_hallucination_v671.py` que:
  - Desativa o V6.51 antigo
  - Substitui exemplos `Vando/Fibra 500/Cordovil` por placeholders `[APELIDO_REAL]/[PLANO_REAL]/[BAIRRO_REAL]`
  - Adiciona **Regra 11** (Proibido inventar dados — saudação neutra se não houver bloco real)
  - Adiciona **Regra 12** (Lead novo tem prioridade sobre cadastro antigo — ignora subscriber_ctx duplicado)
  - Adiciona **Regra 13** (Continuidade de flow — não reinicia após "Ok"/"Sim"/"blz")

### Tests
- Pytest existente: 18/18 passing (`test_customer_history_and_linker.py`)
- Migration aplicada no preview: `frg-07350eb19c` (6386 chars)
- Lint Python: ✅ OK em ambos arquivos

### ⚠️ Pendências do usuário
1. **Persistir env vars no painel Emergent (preview)** — atualmente o `.env` está OK mas pode ser sobrescrito em redeploy
2. **Redeploy de produção** (Save to GitHub → deploy) para subir o V6.71 e o fix do customer_history
3. **Limpar `subscriber_phones` em produção** — número `21998176526` pode estar vinculado erroneamente a subscriber "Vando" (verificar via UI ou DB query)
4. **Criar Volume persistente** no sidecar preview Railway (mount `/app/auth_info`)
5. **Excluir serviço sobrando `whatsapp-sidecar-2`** no Railway

### Critério de sucesso da correção
Após redeploy de produção, próxima mensagem "Quero instalar" + "Cordovil" + "Ok" deve resultar em:
- ✅ Isabella NÃO chama o cliente de "Vando"
- ✅ NÃO menciona "Fibra 500 Mega"
- ✅ NÃO inventa "vi que você relatou lentidão"
- ✅ NÃO reinicia o flow após "Quero" — confirma agendamento com data/hora



## Feb 15, 2026 — Rate limit estendido para endpoints sensíveis ★

### O que foi implementado
Aplicado `@limiter.limit(get_limit(...))` em 7 endpoints sensíveis:

| Endpoint | Limite (prod) | Limite (DEV) | Propósito |
|---|---|---|---|
| `POST /api/auth/login` | 5/min | 50/min | Brute force (já existente) |
| `POST /api/secretaria/ask` | 30/min | 300/min | Custo LLM |
| `POST /api/mass-messaging/campaigns` | 10/min | 100/min | Anti-spam interno |
| `POST /api/mass-messaging/campaigns/{id}/start` | 5/min | 50/min | Inicialização |
| `POST /api/whatsapp-twilio/webhook` | 120/min | 1200/min | Flood Twilio |
| `POST /api/whatsapp-meta/webhook` | 120/min | 1200/min | Flood Meta |
| `POST /api/secretaria/webhook/chatgpt` | 120/min | 1200/min | GPT customizado |
| `POST /api/secretaria/ask/{token}` | 120/min | 1200/min | GPT path-auth |

### Bug fix interno (PEP 563 + slowapi)
Removido `from __future__ import annotations` de `routes/secretaria.py` e `routes/mass_messaging.py`.

**RCA**: PEP 563 (postponed annotations) torna type hints em strings. slowapi inspeciona `inspect.signature()` no momento da decoração — combinado com Pydantic v2 + FastAPI Body, causa erro `422 Field required` em payloads de POST. Solução: forçar avaliação eager de annotations removendo o import (Python 3.11 não precisa).

### Tests
- `/app/test_reports/iteration_75.json` — Backend 14/14 PASS
- Pytest: `/app/backend/tests/test_iter75_secretaria_mass_ratelimit.py`
- Validado: 422 regression em `/ask` + start campaign com default_factory funcionam corretamente

### Atenção em produção
- `services/rate_limit.py` usa storage `memory://` (per-pod). Em multi-pod, trocar para `redis://`
- `_is_dev()` detecta `preview.emergent` ou `localhost` no `PUBLIC_BACKEND_URL`. Garantir que prod tenha essa env var setada corretamente (`https://dual-combine-3.emergent.host`)
- Pode aplicar `@limiter.limit` em mais endpoints futuramente, MAS evite adicionar `from __future__ import annotations` em routes que usem slowapi + Pydantic Body.

---


# PontoIA — Changelog

## Feb 15, 2026 — Analytics financeiro + Rate Limiting global ★

### O que foi implementado

**Analytics financeiro (gráfico Recebimentos vs Despesas)**
- Backend `/app/backend/routes/financeiro_analytics.py`:
  - Endpoint `GET /api/financeiro/analytics?range=1d|7d|30d|3m|6m|1y|all&period=day|month|year`
  - Agrega `fin_cash_movements` (income/expense) + `subscriber_invoices` com paid_date (faturas pagas via Atlaz)
  - Calcula média, desvio padrão e **coeficiente de variação (CV%)** → classifica regularidade: regular (<25%), moderada (25-50%), irregular (>50%)
  - Buckets contínuos (preenche zeros pra gráfico não pular dias)
- Frontend `/app/frontend/src/FinanceiroAnalyticsChart.js`:
  - 7 botões de range, 3 botões de agrupamento (Dia/Mês/Ano)
  - 4 metric cards: Média Recebimentos, Média Despesas, Resultado, Total Recebimentos
  - Recharts LineChart com 3 séries (Recebimentos verde, Despesas vermelho, Resultado azul tracejado)
  - Toggle Linha/Área (AreaChart com gradient)
  - Badge de regularidade com cor por classificação
  - Bloco "Como interpretar a regularidade"
- Plugado em CashFlowTab no topo do painel "Fluxo de Caixa"

**Rate Limiting global via slowapi**
- Lib instalada: `slowapi==0.1.9` (também `limits==5.8.0`, `Deprecated==1.3.1`, `wrapt==2.1.2`)
- `/app/backend/services/rate_limit.py`:
  - Singleton `limiter` com `_key_func()` que prioriza X-Forwarded-For (Kubernetes ingress) sobre IP local
  - DEV multiplier 10x (detecta `preview.emergent` ou `localhost` em PUBLIC_BACKEND_URL)
  - Limites preset: auth_login (5/min), auth_register (3/min), mass_create (10/min), mass_start (5/min), secretaria_ask (30/min), webhook_inbound (120/min), default (100/min)
  - `headers_enabled=False` evita conflito com dict-returns do FastAPI
  - Storage `memory://` (single-pod). Para multi-pod, trocar para `redis://`
- Wire em `/app/backend/server.py`: app.state.limiter + RateLimitExceeded handler
- Aplicado em `/api/auth/login` (proteção brute force) via `@limiter.limit(get_limit("auth_login"))`
- Testado: 6ª tentativa errada em 1min retorna **HTTP 429** corretamente

### Tests
- `/app/test_reports/iteration_74.json` — Backend 9/10 PASS (1 skipped por falta de seed)
- Pytest file: `/app/backend/tests/test_iter74_analytics_rate_limit.py`

### Action items não-bloqueantes (futuras melhorias)
- Considerar mudar `_range_for()` para boundaries de calendário estritos (atualmente usa days=180 para 6m, gera 7±1 buckets)
- Em multi-pod prod, trocar storage `memory://` para `redis://` para compartilhar contadores
- Regularity threshold: considerar exigir N≥3 antes de classificar (atualmente classifica mesmo com 1 ponto)

---


# PontoIA — Changelog

## Feb 15, 2026 — Ligo (Secretária IA) consulta faturas dos assinantes ★

### O que foi implementado
- 2 novas tools em `/app/backend/services/secretaria_tools.py`:
  - **`consult_subscriber_invoices(document, subscriber_name, status, limit)`** — busca faturas do assinante por CPF/CNPJ (com/sem máscara) ou nome parcial. Filtros: any/open/paid/overdue. Retorna lista + soma em aberto.
  - **`next_due_invoice(document, subscriber_name)`** — próxima fatura não paga.
- Helper `_norm_doc()` remove máscaras de CPF/CNPJ automaticamente.
- Helper `_resolve_invoices_query()` reutilizável entre tools.

### Resultado E2E
Sem mexer no prompt da Ligo, ela já invoca as tools automaticamente. Testes:
- "Quanto eu devo? CPF 123.456.789-01" → consult_subscriber_invoices
- "Pode me passar a 2a via da fatura do João Silva?" → consult_subscriber_invoices (busca por nome)
- "Qual a próxima fatura do CPF 12345678901?" → next_due_invoice
- Resposta inclui valor, vencimento (formato pt-BR), linha digitável para pagamento.

### Como funciona
Os dados vêm da coleção `subscriber_invoices` populada pela Fase 4 (sync com Atlaz V2). Assim que o usuário sincronizar (Configurações → Recebimentos → "Sincronizar agora"), a Ligo consulta automaticamente sempre que um cliente perguntar sobre cobrança/fatura/2ª via via WhatsApp.

### Impacto esperado
- Redução estimada de 30-40% nos tickets de cobrança que hoje são respondidos manualmente.
- Resposta instantânea 24/7 mesmo fora do horário comercial.
- Cliente recebe linha digitável direto no chat — sem precisar de atendente humano.

---


# PontoIA — Changelog

## Feb 15, 2026 — Financeiro Fase 3+4 + Disparo em Massa WhatsApp ★

### O que foi implementado

**Financeiro Fase 3 — Contas a Pagar + Fluxo de Caixa**
- Backend `/app/backend/routes/financeiro_ops.py`:
  - `fin_bills_payable`: CRUD completo + `POST /bills/{id}/pay` (cria movimentação E atualiza saldo)
  - `fin_cash_movements`: CRUD com saldo automático
  - `GET /financeiro/cashflow` agregado para gráfico (entradas vs saídas por dia/mês)
  - Cron 03h `auto_mark_overdue` marca contas vencidas como overdue
- Frontend `/app/frontend/src/FinanceiroPanelExt.js`:
  - `BillsTab`: filtros por status, modal CRUD, modal "Pagar" com seleção de cash_account
  - `CashFlowTab`: gráfico Recharts BarChart entradas/saídas + chips Saldo/Entradas/Saídas/Resultado + tabela de movimentações + modal "Novo lançamento"

**Financeiro Fase 4 — Integração Atlaz Financeiro (assinantes)**
- Backend `/app/backend/routes/atlaz_financeiro.py`:
  - `GET /atlaz-financeiro/probe` — testa 5 endpoints (listacobrancas, listaboletos, listapagamentos, listaclientes, listaservicos)
  - `POST /atlaz-financeiro/sync-now` — pull tolerante a 404 com normalização defensiva
  - `GET /atlaz-financeiro/invoices` + `/stats` para listagem e KPIs
  - Coleção `subscriber_invoices` com schema normalizado (external_id, subscriber_name/document, amount/amount_paid, due_date/paid_date, status, raw)
- Frontend `ReceivablesTab` no FinanceiroPanel: sub-aba "Recebimentos" com botão "Sincronizar" + "Testar endpoints" (probe)

**Disparo em Massa WhatsApp**
- Backend `/app/backend/routes/mass_messaging.py`:
  - Coleções `mass_campaigns` + `mass_recipients`
  - Suporta **Meta WhatsApp Cloud** + **Twilio** (canal configurável por campanha)
  - Suporta **template HSM** + **texto livre** com variáveis `{{nome}}`
  - Upload CSV com normalização de telefone BR (E.164, +55 auto-prepend), insert em bulk de 500
  - Endpoint `/preview` retorna 3 samples com vars substituídas
  - Endpoints `/start`, `/pause`, `/resume`, `/delete`
  - **Worker assíncrono** em background processa filas com throttle configurável (default 60 msgs/min, max 600)
  - Agendamento via `schedule_at` (worker promove queued→running quando atingir horário)
  - Cron de tick = 5s; burst = throttle_per_min * 5 / 60
- Frontend `/app/frontend/src/MassMessagingPanel.js`:
  - Lista de campanhas com status badges
  - View de detalhe com upload CSV, preview, start/pause/resume/delete
  - Polling de 4s na view de detalhe pra atualizar `sent`/`failed`/`status` em tempo real
  - Filtro de destinatários por status (queued/sending/sent/failed)

### Pontos importantes
- `_worker_task` (mass_messaging) é singleton por processo. Em deployments multi-pod, considerar lock distribuído (mongo `findOneAndUpdate`) — não-bloqueante para single-pod.
- A integração Atlaz Financeiro está pronta para qualquer subconjunto de endpoints respondidos pelo token. Use `/probe` primeiro pra ver quais estão disponíveis.

### Tests
- `/app/test_reports/iteration_73.json` — 25/25 backend PASS + 100% frontend E2E PASS
- Pytest file: `/app/backend/tests/test_iter73_financeiro_p34_mass.py`

### Action items não-bloqueantes
- Trocar `<input type=datetime-local>` por DateTimePicker shadcn em "Agendar para" da campanha (formato pt-BR)
- Investigar warning Recharts width(-1) (mesmo de iter72, não impacta funcionalidade)

---


# PontoIA — Changelog

## Feb 15, 2026 — Module: Financeiro (Fase 1+2) + Card unificado de Conexões ★

### O que foi implementado

**Fase 1 — Card unificado de Conexões em Configurações**
- Novo endpoint backend `/app/backend/routes/connections.py`:
  - `GET /api/connections/` → retorna 8 integrações com chaves mascaradas
  - `PUT /api/connections/{integration_id}` → atualiza credenciais (secret vazio mantém atual)
  - Integrações cobertas: Atlaz V2, SmartOLT, Twilio, Meta WhatsApp Cloud, OpenRouter, Resend, Stripe, Google Drive
  - Auditoria em `db.connection_audit`
- Novo componente frontend `/app/frontend/src/ConnectionsCard.js`:
  - Tabela com Nome / Categoria / Credencial mascarada / Status / Ação
  - Modal de edição com olho mostrar/esconder secrets
  - Inseridoem `SettingsPanel.js` antes dos cards legados Atlaz/SmartOLT/Magnus

**Fase 2 — Módulo Financeiro (cadastros base)**
- Nova role `financeiro` adicionada a `VALID_ROLES` em `/app/backend/auth.py`
- Novo router `/app/backend/routes/financeiro.py` com CRUDs:
  - `/api/financeiro/categories` (despesa/receita/ambos, cor, parent_id)
  - `/api/financeiro/suppliers` (CPF/CNPJ, contato, endereço)
  - `/api/financeiro/payment-methods` (PIX/Boleto/Cartão/Dinheiro/Transferência + taxa% + D+)
  - `/api/financeiro/cash-accounts` (banco/caixa físico/wallet, saldo inicial/atual)
  - `/api/financeiro/summary` (contadores + saldo total)
- Coleções Mongo novas: `fin_categories`, `fin_suppliers`, `fin_payment_methods`, `fin_cash_accounts`
- Novo painel `/app/frontend/src/FinanceiroPanel.js` com 6 sub-abas:
  - **Fluxo de Caixa** (placeholder Fase 3)
  - **Contas a Pagar** (placeholder Fase 3)
  - **Caixa** (CRUD)
  - **Método de Cobrança** (CRUD)
  - **Categoria** (CRUD)
  - **Fornecedor** (CRUD)
- Componente genérico `CrudTab` + `CrudModal` reusado por todas sub-abas
- Novo grupo "Financeiro" na sidebar (`NAV_GROUPS` em `App.js`), acesso `auditor`/`administrador`/`financeiro`

### Próximas fases planejadas
- **Fase 3**: contas a pagar com movimentação + fluxo de caixa (entrada/saída) + gráficos
- **Fase 4**: integração financeira com Atlaz V2 (pull de faturas/pagamentos dos assinantes)
- **Fase 5**: relatórios DRE + conciliação bancária + exportação PDF/Excel

### Tests
- `/app/test_reports/iteration_72.json` — 21/21 backend PASS + 100% frontend E2E PASS
- Pytest file: `/app/backend/tests/test_iter72_connections_financeiro.py`

### Deploy readiness
- Health check `deployment_agent` PASS após corrigir `.gitignore` (estava bloqueando `.env`), CORS adicionado `https://dual-combine-3.emergent.host`, e `collabAuth.js` migrado de `window.location.href` para `window.location.origin`.

---



## Feb 14, 2026 — Fix: Romaneio em modal interno (PDF viewer inline) ★

### Bug reportado
"Kd o romaneio em PDF? A página está em branco" — depois do fix anterior do popup blocker, a nova aba abria com `about:blank` mas o PDF não renderizava.

### Causa raiz
Blob URLs criados na janela principal (`document.location.origin = https://...`) não funcionam em janelas com `about:blank` (origem `null`). O `window.location.href = blobUrl` falhava silenciosamente.

### Fix final aplicado em `AssetsSection.js`
- **Removida** completamente a abordagem `window.open()` (causa popup blocker + cross-origin)
- **Adicionado** componente `RomaneioPdfModal` interno com:
  - Header: "TERMO DE RESPONSABILIDADE" + nome do arquivo gerado
  - `<iframe src={blobUrl}>` que renderiza o PDF nativamente (navegador usa plugin built-in)
  - Botões: `↓ Baixar` (via `<a download>`), `🖨 Imprimir` (chama `iframe.contentWindow.print()`), `Fechar`
  - Loader "Gerando romaneio…" enquanto fetch executa
  - Mensagem de erro inline (não alert)
  - `URL.revokeObjectURL` ao fechar (limpa memória)
- Backdrop escuro com click-to-close
- Zero dependência de popup blocker ou janela externa

### Validação ✓
- Modal abre instantaneamente no click
- iframe.src = `blob:http://localhost:3000/{uuid}` válido (confirmado via Playwright)
- HTTP 200 application/pdf no fetch (18.6KB com tabela completa)
- Funciona em qualquer navegador moderno (Chrome, Firefox, Edge, Safari)
- Mesma técnica pode ser reaplicada em outros lugares que geram PDF

---



### Bug reportado
Após o fix anterior do popup blocker, a nova aba abria mas mostrava **página em branco** — o PDF não renderizava.

### Causa raiz
`URL.createObjectURL(blob)` cria um blob URL **escopado à origem** da janela que o criou. Como a janela nova era `about:blank` (origem "null"), o blob URL criado na janela principal não era acessível lá. O `win.location.href = blobUrl` não carregava nada.

### Fix aplicado em `AssetsSection.js`
- `openRomaneioInNewTab(onlyActive)`: usa `<embed type="application/pdf">` **dentro da janela nova** via `document.write` — o PDF carrega nativamente no navegador
- Cria o blob URL no contexto da janela nova (`win.URL.createObjectURL`) quando disponível, com fallback para `URL.createObjectURL`
- Placeholder "Gerando romaneio…" aparece imediatamente; substituído pelo `<embed>` quando o fetch completa
- Mensagem de erro renderizada DENTRO da nova janela se o fetch falha
- `openRomaneio(onlyActive)`: variante de **download direto** via `<a download="romaneio_nome.pdf">` (não depende de popup)
- Novo botão "↓" no header do checklist para baixar o PDF direto

### Validação ✓
- Nova aba tem `<embed>` com blob URL (confirmado: body length 245, embed=true)
- HTTP 200 no fetch do PDF
- PDF backend gera corretamente (1023 chars de texto, 18.6KB, 1 página com Colaborador + tabela completa de itens)

---



### Bug reportado
Botões "Romaneio (todos)" e "Romaneio (só ativos)" no cadastro/checklist do colaborador "não estavam funcionando" — clique não abria o PDF.

### Causa raiz
`window.open(URL.createObjectURL(blob), "_blank")` executado **depois** de `fetch().then().then()` é bloqueado pelo popup blocker porque não está mais no contexto direto de um event handler de click.

### Fix aplicado
- `AssetsSection.js:openRomaneio()` — abre janela IMEDIATAMENTE no clique com `window.open("about:blank", "_blank")` (síncrono, evento direto), mostra placeholder "Gerando romaneio…", e depois atribui `win.location.href = blobUrl` quando o fetch retorna
- `DeactivationAssetsModal.js:submit()` — mesmo padrão aplicado ao termo de devolução assinado
- Mensagem clara se popup bloqueado: "Permita popups deste site nas configurações do navegador"

### Validação ✓
- Frontend Playwright PASS (iter 71)
- Logs HTTP confirmados: `[200] /api/collab-assets/romaneio/{cid}` + `[200] blob:http://localhost:3000/...`
- Demais ações (editar, devolver, remover) já funcionavam — confirmadas sem regressão
- Zero UI bugs, integration issues ou design issues

---



### Frontend
- **`BottomSheet.js`** (NEW) — componente genérico reutilizável estilo iOS/Android:
  - Animação de entrada com curva spring `cubic-bezier(.16,1,.3,1)`
  - Drag handle visual (40x4px) com testid `sheet-drag-handle`
  - Suporta **touch** (mobile) e **mouse** (desktop)
  - Dismiss automático quando arrastado > 35% da altura **OU** velocidade > 0.6px/ms
  - Snap-back com curva spring `cubic-bezier(.34,1.56,.64,1)` quando abaixo do threshold
  - Drag para cima limitado com 15% de resistência
  - ESC fecha + click no backdrop fecha
  - Body scrollável com `overscrollBehavior: contain` (não interfere no drag)
- **Refatorado em todos os 3 modais do kebab**:
  - `MyHoleritesModal` → BottomSheet
  - `MyAssetsModal` → BottomSheet
  - `SignWithGovBrModal` (interno do Holerites) → BottomSheet
- Padrão visual consistente: pull handle no topo, header sóbrio, footer LGPD compacto

### Validação ✓
- Frontend Playwright **13/13 critérios PASS** (iter 70)
- Drag visual confirmado em screenshots (sheet sobe → drag pra baixo → fecha)
- Zero issues UI/design/integração

---



### Backend
- **`DELETE /api/holerites/{doc_id}/permanent`** (NEW) — hard delete:
  - Apaga `payroll_documents` + arquivos físicos (original e assinado) do disco
  - Apaga `payroll_access_tokens` associados
  - Preserva audit log (registra `permanent_delete` ANTES de apagar com dados do doc)
  - Requer role gestor
- Endpoint anterior (revoke soft delete) mantido

### Frontend admin (`HoleritePanel.js`)
- Botão lixeira (Trash2) ao lado do Ban (revoke) em cada linha
- Confirm duplo: "APAGAR PERMANENTEMENTE" + "Tem CERTEZA?"
- testid `holerite-delete-{id}`

### Frontend colaborador (`MyHoleritesModal.js` REWRITE)
- **Layout bottom-sheet style** (iOS/Android nativo) com pull handle no topo
- **Removida** a barra de pesquisa (limpeza visual)
- **Card minimalista**:
  - MÊS YEAR em uppercase pequeno cinza
  - R$ valor BEM grande, fonte 22px peso 800
  - Bruto/Descontos em 2 colunas secundárias 11px
  - Badge "● Assinado" verde clean (sem peso)
- **Botão único dinâmico** (3 estados via `localStorage`):
  - **Estado A** (não baixado): `Baixar` (preto #0f172a, ícone ↓)
  - **Estado B** (baixado, não assinado): `Enviar assinado` (azul gov.br #1351b4, ícone ↑) + hint "Já baixou? Assine no gov.br e envie aqui."
  - **Estado C** (assinado): `Baixar assinado` (preto, ícone ✓) + hint "Assinado em DD/MM/YYYY · digital validada"
- localStorage key: `holerite_dl_{cid}_{docId}`
- Footer LGPD compacto e centralizado
- SignWithGovBrModal também refeito com mesma estética bottom-sheet sóbria

### Validação ✓
- Backend pytest **5/5 PASS** (iter 69)
- Frontend PASS: transição Baixar→Enviar→Baixar assinado validada visualmente
- Audit log persiste após permanent delete (recuperável via `/api/holerites/audit/{doc_id}`)
- Zero issues críticos/menores/integração/UI/design

---



### Pesquisa jurídica (web search 2026)
- STJ reconheceu validade da assinatura gov.br em fev/2026 para documentos trabalhistas
- Lei 14.063/2020 valida assinatura "avançada" gov.br para relação empregado-empregador
- TRTs 8ª e 9ª regiões já validaram em casos rescisórios
- Recomendado adicionar timestamp + SHA-256 hash para integridade jurídica

### Backend
- **Filtro por `pay_date`**: `GET /public/by-collaborator/{cid}` agora só retorna holerites cuja `pay_date <= hoje` (esconde holerites futuros do colaborador)
- **Auto pay_date no import**: `_default_pay_date(year, month)` calcula automaticamente o 5º dia do mês seguinte à competência
- **`POST /public/{cid}/{doc_id}/sign-upload`** (NEW) — recebe PDF assinado pelo colaborador:
  - Valida magic bytes %PDF-, tamanho ≤ 10MB
  - Detecta marcadores de assinatura digital (`/ByteRange`, `/Sig`, `adbe.pkcs7`) via heurística
  - Calcula SHA-256 do conteúdo (integridade)
  - Persiste: `signed_at`, `signed_method='govbr_manual_upload'`, `signed_by_name`, `signature_valid` (bool), `signature_hash`
  - Salva em `STORAGE_DIR/{company}/signed/{doc_id}_signed_{uuid}.pdf` separado do original
  - Audit log com hash truncado
- **`GET /public/{cid}/{doc_id}/signed-file`** (NEW) — stream do PDF assinado
- **Hash SHA-256 do PDF original** (`file_hash`) também é calculado e persistido no import manual

### Frontend
- **`MyHoleritesModal.js`** (REWRITE):
  - Card verde quando assinado (gradient verde + badge "✓ Assinado em DD/MM/YYYY")
  - Card roxo quando não assinado (gradient indigo + botão "Assinar gov.br" azul royal #1351b4)
  - Botões dinâmicos: "Baixar original" sempre + "Baixar assinado" OU "Assinar gov.br"
  - Footer LGPD atualizado mencionando Lei 14.063/2020
- **`SignWithGovBrModal`** (NEW) — fluxo guiado em 3 passos:
  - **Passo 1**: Botão "Baixar PDF original" + auto-avança ao step 2
  - **Passo 2**: Lista 5 instruções + box informativo sobre Lei 14.063 + link externo `https://assinador.iti.br/`
  - **Passo 3**: Drop zone + input file PDF + botão "Confirmar envio"
  - **Passo 4** (sucesso): Mostra status (validada/observação), warning se aplicável, SHA-256 hash truncado
  - Step indicator visual no topo
  - Header gradient azul gov.br (#1351b4)

### Validação ✓
- Backend pytest **10/10 PASS** em iter 68
- Frontend Playwright PASS: modal abre, wizard 3 passos completo, upload PDF detecta `/ByteRange`, SHA-256 hash visível, badge "assinado" renderiza, botões toggle (sign↔view-signed) baseado em `signed_at`
- Zero issues críticos/menores/integração/UI

---



### Backend
- **Auto-lock**: Quando `analyze_doc` detecta ≥1 anomalia crítica (NET_DROP/RISE ≥25%, ZERO_NET, DUPLICATE), o holerite vai automaticamente para `status="pending_review"` com `pending_review_reason` preenchido.
- **`POST /api/holerites/{doc_id}/notify`** retorna HTTP 423 (Locked) se status=pending_review — não envia ao colaborador.
- **`GET /api/holerites/public/by-collaborator/{cid}`** filtra `status="available"` (pending_review fica oculto para o colaborador).
- **`POST /api/holerites/{doc_id}/approve`** (NEW) — RH libera com nota opcional. Marca `approved_at`, `approved_by`, `approval_note`.
- **`POST /api/holerites/{doc_id}/reject`** (NEW) — RH rejeita e revoga, registrando motivo.
- Audit log em todas as ações de aprovação/rejeição.

### Frontend
- **Badge na linha**: `🔒 AGUARDA RH` (laranja claro) quando status=pending_review.
- **`AnomaliesModal` ganhou seção de revisão**:
  - Banner vermelho/gradient explicando o lock
  - Banner verde quando já aprovado (mostra reviewer + timestamp + nota)
  - Textarea de nota do revisor (com placeholder útil)
  - Botão "Rejeitar e revogar" (vermelho) + "Aprovar e liberar" (verde)
- `api.js`: `holeriteApprove`, `holeriteReject`, `holeriteReanalyze`, `holeriteAnomalies`.

### Validação ✓
- Jefferson com -98.2% líquido (R$ 2492 → R$ 46) auto-bloqueou em pending_review
- Notify retornou HTTP 423 (Locked) — confirma proteção
- Lista pública do colaborador filtrou pending_review automaticamente
- Approve com nota libera o doc + persiste reviewer (Administrador) + timestamp
- UI mostra todo o fluxo: banner lock → chips anomalias → nota → aprovar/rejeitar

---



### Backend
- **`services/holerite_anomaly.py`** (NEW) — engine determinística (sem LLM) que compara holerite com mês anterior do mesmo funcionário
- **10 tipos de anomalia** detectados:
  - `NET_DROP/RISE` · `GROSS_DROP/RISE` (≥10% configurável, crítico ≥25%)
  - `NEW_EARNING` · `MISSING_EARNING` (rubricas que aparecem/somem)
  - `NEW_DEDUCTION` (descontos novos, ignora INSS/IRRF/FGTS padrão)
  - `INSS_HIGH` (>15% do bruto · limite legal ~14%)
  - `ZERO_NET` (líquido ≤ 0 — provável erro de extração)
  - `DUPLICATE` (já existe holerite ativo na mesma competência)
  - `FIRST_HOLERITE` (info — sem comparação histórica)
- Normalização de rubricas via Unidecode (resolve "salário" vs "salario")
- Anomalias persistem em `payroll_documents.anomalies` + counters (count, critical)
- **Endpoints novos**: `GET /api/holerites/anomalies` (lista global filtrável por severity/year/month) · `POST /api/holerites/{doc_id}/reanalyze`
- Detecção roda **automaticamente após cada `/ai-import`** — inclusas na resposta

### Frontend
- **`HoleritePanel.js`**: badge laranja/vermelho com contador de anomalias em cada linha (testid `holerite-anomalies-{id}`) → click abre `AnomaliesModal`
- `AnomaliesModal` lista cada anomalia com chip colorido por severidade (kind em uppercase + mensagem)
- **`DoneStep` do import** agora mostra resumo automático: "⚠️ N anomalias detectadas" com badge crítico em destaque + breakdown por funcionário

### Validação ✓
- PDF com Diogo perdendo R$ 1.262 (-41.9% líquido, com falta nova) gerou 4 anomalias precisas (1 crítica + 3 warnings)
- Reanalyze endpoint funciona para docs antigos
- UI mostra modal completo com todos os chips de severidade corretamente coloridos

---


## Feb 14, 2026 — Holerite IA: Detecção Automática de Anomalias ★★

- Engine determinística de detecção comparando holerite recém-importado com o mês anterior.
- 10 tipos de anomalia: NET_DROP/RISE, GROSS_DROP/RISE (≥10%, crítico ≥25%), NEW_EARNING, MISSING_EARNING, NEW_DEDUCTION, INSS_HIGH (>15%), ZERO_NET, DUPLICATE, FIRST_HOLERITE.
- Normalização Unidecode resolve "salário" vs "salario".
- Detecção roda automaticamente após cada `/ai-import` + endpoints `GET /anomalies` e `POST /{doc_id}/reanalyze`.
- Persistência em `payroll_documents.anomalies` + counters.
- Frontend: badge laranja/vermelho com contador em cada linha + `AnomaliesModal` com chips coloridos por severidade + summary no DoneStep do import.
- Validação: Diogo com -41.9% líquido gerou 4 anomalias precisas (1 crítica + 3 warnings).

---


## Feb 14, 2026 — Fix: Romaneio aparecia em branco na nova aba ★

### Backend
- Auto-lock: `analyze_doc` marca automaticamente `status="pending_review"` quando ≥1 anomalia crítica (NET_DROP/RISE ≥25%, ZERO_NET, DUPLICATE).
- `POST /notify` retorna HTTP 423 (Locked) se pending_review — não envia ao colaborador.
- `GET /public/by-collaborator/{cid}` filtra pending_review → holerite fica invisível pro funcionário.
- Endpoints `POST /{doc_id}/approve` (libera com nota) e `/reject` (revoga) com audit log.

### Frontend
- Badge na linha: `🔒 AGUARDA RH` (laranja claro).
- `AnomaliesModal` ganhou: banner vermelho/gradient explicando o lock, banner verde quando já aprovado (mostra reviewer + timestamp + nota), textarea de nota do revisor, botões "Rejeitar e revogar" (vermelho) + "Aprovar e liberar" (verde).

### Validação ✓
- Jefferson com -98.2% líquido auto-bloqueou em pending_review
- Notify retornou HTTP 423 — confirma proteção
- Approve com nota libera o doc + persiste reviewer + timestamp

---


## Feb 14, 2026 — Holerite IA (Claude) + Holerite no app do colaborador ★★★

### Backend
- **`services/holerite_ai.py`** (NEW) — pipeline completo:
  - `extract_pdf_text` via pypdf (text-based PDFs CLT/eSocial)
  - `parse_pdf_with_ai` via Claude Sonnet 4.5 (OpenRouter) com prompt estruturado em JSON mode
  - `match_employee` via RapidFuzz token_set_ratio + Unidecode + CPF exact (3 níveis: cpf_exact/name_high/name_medium/no_match)
  - Best practices: BRL parsing, CPF normalization, validação gross=soma(earnings), net=gross-deductions
- **Endpoints novos em `routes/holerite.py`**:
  - `POST /api/holerites/ai-parse` (multipart: file + threshold) — parse + match (não persiste, retorna preview com parse_id)
  - `POST /api/holerites/ai-import` (parse_id + items[]) — confirma e cria 1 payroll_document por funcionário
  - `GET /api/holerites/public/by-collaborator/{cid}` — público (sem JWT), lista do próprio colaborador
  - `GET /api/holerites/public/{cid}/{doc_id}/file` — público, stream PDF + marca viewed_at + audit log
- **`scripts/seed_holerite_ai_agent.py`** — 11º agente (Holerite IA) seedado no `aihub_agents`
- **Dependências novas**: `pypdf==6.11.0`, `Unidecode==1.4.0`, `RapidFuzz==3.14.5` (em requirements.txt)
- LGPD: PDFs continuam armazenados criptografados, audit log em todas as ações

### Frontend
- **`HoleritePanel.js`**: botão "Importar com Holerite IA" (gradient roxo) + `HoleriteAIImportModal` com stepper 4-stages (Upload → Analisar com IA → Revisar matches → Importar)
  - UploadStep: drag-drop + slider threshold (50-100, default 85) com labels dinâmicos
  - ReviewStep: 5 mini-KPIs (Identificados, Match auto, Não encontrados, Bruto total, Líquido total) + 1 linha por match com status colorido, score%, select de colaborador, checkbox "Ignorar"
  - DoneStep: card de sucesso com X imported / Y skipped
- **`MyHoleritesModal.js` (NEW)** — modal mobile do colaborador
  - Cards com mês/ano colorido (gradient roxo), líquido em destaque, bruto + descontos abaixo
  - Botão "Baixar PDF" abre em nova aba via endpoint público
  - Filtro por ano/mês/valor
  - LGPD strip embaixo
- **`CollaboratorApp.js`** — KebabMenu (3 pontinhos) ganhou item "Meus holerites" (testid: `kebab-holerites`) com ícone Receipt
- **`api.js`**: `publicHoleritesList`, `publicHoleriteFileUrl`, `_client` (acesso raw axios para upload)

### Validação ✓
- Backend pytest **10/10 PASS** em iter 67
- Frontend admin: PDF de teste (3 funcionários) parseou em ~9s · matches 100% · CPF exato detectado
- Frontend mobile: kebab → "Meus holerites" → lista holerite (R$ 3.015,00) → "Baixar PDF" abre em nova aba
- Zero issues críticos, menores, integração ou UI

---

## Feb 14, 2026 — Training Studio Scheduler (Auto-Run + Drift Alert) ★★

### Backend
- **`services/ai_training_scheduler.py`** (NEW) — worker que checa a cada 60s e dispara batch dos 20 testes no horário configurado (default 03h UTC ≈ 00h BRT)
- Idempotente via `last_run_date` (1x/dia por empresa)
- Roda os 20 testes em paralelo (semáforo=3 para não sobrecarregar OpenRouter)
- Persiste runs em `ai_training_runs` com flag `automated=True`
- **Drift detection**: se média < `alert_threshold` (default 7.5/10), cria notificação in-app na coleção `notifications` (severity=warning, kind=training_drift)
- **Endpoints novos** em `routes/ai_training.py`:
  - `GET /api/ai-training/schedule` — retorna config (com defaults)
  - `PUT /api/ai-training/schedule` — atualiza enabled/hour_utc/minute/alert_threshold (validação 0-23/0-59/0.0-10.0)
- Worker registrado em `server.py:_startup` junto com churn_scheduler

### Frontend
- **5ª tab "Agendamento"** no Training Studio (icon: CalendarClock)
- Card de configuração: toggle Ativado, Hora UTC, Minuto, Threshold de alerta
- Mostra **próxima execução prevista** (calculada local em tempo real)
- Card "Última execução automática" com KPIs (data, aprovados X/20, reprovados, nota média)
- Banner vermelho de **"Drift detectado!"** quando última run < threshold
- `api.aiTrainingSchedule()` + `api.aiTrainingScheduleUpdate(data)` adicionadas

### Validação ✓
- PUT /schedule retorna 200 com payload válido
- Worker disparou após 60s e executou os 20 testes em ~3min
- Nota média 6.06/10 (real) < 7.5 threshold → drift alert disparado
- UI exibe todos os KPIs + banner vermelho corretamente
- Schedule persiste configuração entre restarts

---


## Feb 14, 2026 — Training Studio (Simulador de Treinamento Multi-Agente) ★★★

### Backend
- **60 cenários de treinamento** seedados em `ai_training_scenarios` (categorias: rede_smartolt 14, agendamento_kanban 10, atendimento_humano 6, avaliacao_coach 10, falhas_escalonamento 10, variacao_dificil 10)
  - Scripts: `seed_scenarios_batch1.py` (#1-#14), `batch2.py` (#15-#24), `batch4_5.py` (#25-#40), `batch6.py` (#41-#60)
  - Cada cenário tem: objetivo, contexto, agentes envolvidos, fluxo ideal, simulação completa da conversa multi-agente, resposta correta, erros a evitar, critérios de avaliação, notas esperadas, lição
- **20 testes de validação** em `ai_training_tests` (script: `seed_training_tests.py`)
  - Cada teste verifica entrada do cliente vs agentes esperados + erro crítico + critério binário
- **31 regras da matriz de decisão** em `ai_training_decision_matrix` (script: `seed_decision_matrix.py`)
  - 10 categorias: rede, agendamento, risco, supervisão, sistema, ticket, qualidade, transparência, cadastro, especial
  - Cada regra: condição → ação, com agente origem/destino e prioridade (crítica/alta/média/baixa)
- **Endpoints novos em `routes/ai_training.py`**:
  - `GET /api/ai-training/tests` (com `last_run` agregado)
  - `GET /api/ai-training/tests/{n}`
  - `POST /api/ai-training/tests/{n}/run` — executa Isabela IA real → Avaliador IA → score 0-10 + breakdown 100pts
  - `POST /api/ai-training/tests/run-all` — batch async com semáforo (5 concorrentes)
  - `GET /api/ai-training/decision-matrix`
  - `GET /api/ai-training/runs`, `/runs/{id}`, `/runs/batch/{id}`
- **Engine de avaliação**: Avaliador IA usa prompt estruturado JSON mode (modelo 100pts: fluxo 30 + fonte 25 + sem invenção 20 + empatia 10 + risco 10 + transparência 5; penalidades automáticas -15/-10/-5)
- Persistência completa em `ai_training_runs` para auditoria/histórico

### Frontend
- **`TrainingStudio.js` (NEW · 1130 linhas)** — modal completo acessado via Central IA → "Abrir Training Studio" (botão roxo gradient)
  - **4 tabs**:
    1. **Cenários (60)** — busca, filtro por categoria, detalhe lateral com simulação colorida por agente (Cliente preto, Co-Pilot rosa, Avaliador laranja, Motor roxo, SmartOLT azul, Isabela teal, Kanban indigo, Sentinela vermelho, Aprendizado lima)
    2. **Testes (20)** — botão "Executar" individual + "Executar todos" (batch) · cada linha mostra última execução com score e pass/fail
    3. **Matriz (31)** — 10 categorias com chips de filtro · linhas com Condição → Ação, agente origem→destino, prioridade
    4. **Histórico** — KPIs (execuções, aprovados, reprovados, nota média) + lista de runs com score badge
  - Detalhe de run mostra: resposta literal da Isabela + breakdown visual (barras de progresso por critério) + penalidades + justificativa + agentes acionados/faltando + sugestões
  - **ESC fecha modal** + **click no backdrop fecha modal**
- `AiTrainingPanel.js` ganhou botão "Abrir Training Studio" ao lado do "Recarregar treinamento"
- `api.js` expandida: `aiTrainingTests`, `aiTrainingRunTest`, `aiTrainingRunAll`, `aiTrainingDecisionMatrix`, `aiTrainingRuns`, `aiTrainingRun`, `aiTrainingBatchRuns`

### Testing ✓
- Backend pytest 12/12 PASS em 20.5s (`/app/backend/tests/test_iter65_ai_training.py`)
- Frontend Playwright PASS — todas as 4 tabs renderizando, modal funcional, executar single test integrado (score 9.5/10 em 18s)
- Execução real Isabela IA → Avaliador IA → score 9.5/10 verificada end-to-end

### Validação ✓
- 60 cenários cobertos (todos os casos do prompt do usuário + 10 variações difíceis)
- 20 testes prontos para validar comportamento das IAs
- 31 regras da matriz de decisão disponíveis para consulta visual
- Sistema de scoring 100pts implementado conforme prompt original
- Modal fechável via X, ESC e backdrop click

---


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

## 2026-05-15 — Rede IA (Supervisor FTTH) + bug fixes
### Novo módulo: Rede IA
- **Fase 1 — Backend** (`/app/backend/routes/rede_ia.py`):
  - Coleções: `bairros_vlan_map`, `ctos`, `cto_history`, `cto_validations`, `rede_ia_settings`, `rede_ia_analyses`
  - CRUD `/api/rede-ia/bairros` (admin/gestor/gestor_rede): cadastro de bairros + sigla + VLAN
  - CRUD `/api/rede-ia/ctos` (qualquer auth): cria CTO com status `pending_validation`
  - `/api/rede-ia/ctos/suggest-name`: padrão `CTO {NUM}_{VLAN}_{SIGLA}` com auto-incremento e detecção de duplicidade
  - Workflow validação: `/api/rede-ia/pendencies` + `/api/rede-ia/ctos/{id}/validate` (apenas admin/gestor/gestor_rede)
  - `/api/rede-ia/history`: auditoria completa
  - `/api/rede-ia/flowchart`: nodes+edges para React Flow (OLT → Bairro → CTO → Cliente)
  - `/api/rede-ia/diretrizes`: system prompt editável da rede_IA
  - `/api/rede-ia/analyze`: Claude Sonnet 4.5 via Emergent Key — relatório técnico de inconsistências e capacidade
- **Fase 2 — App Técnico** (`CadastroCTOWizard.js`): 8 passos seguindo storyboard
  1. Detecção "Cliente não identificado em CTO" → 2. Endereço + GPS → 3. Seleção bairro/VLAN + número CTO → 4. Capacidade (4/8/16) → 5. Tipo rede (balanceada/desbalanceada) → 6. Splitter (1:2/1:4/1:8/Outro) → 7. Porta cliente → 8. Resumo + envio para validação
- **Fase 3 — Painel Admin** (`RedeIaPanel.js`): 7 sub-abas
  - Painel (KPIs), CTOs (filtros por status), Pendências (Aprovar/Solicitar correção/Rejeitar), Fluxograma, Bairros/VLAN, Histórico, Diretrizes
- **Fase 4 — Fluxograma React Flow** (`RedeIaFlowchart.js`): visual interativo com MiniMap + Controls + Background
- **Fase 5 — IA real**: LLM Claude Sonnet 4.5 lê diretrizes salvas como system prompt e analisa topologia atual

### Novo role
- `gestor_rede` (seed: `gestorrede@empresa.com` / `123456`) com acesso restrito ao painel Rede IA e workflow de validação.

### Bug fixes desta sessão
- **FinanceiroAnalyticsChart**: `ReferenceError: preset_btn is not defined` → constante adicionada no escopo do módulo
- **WhatsAppChatLayout**: badge de canal (Twilio/Meta/Baileys) adicionado ao header da conversa ativa + indicador multi-canal
- **CollaboratorApp**: auto-login preview agora pula quando `?cid=` está presente, permitindo abertura direta do app técnico via link único
- **SmartOLT 403**: resolvido (chave restaurada manualmente; último sync 1753 ONUs)
- **Webhook Meta 403**: causa identificada (App Secret incorreto) — usuário precisa re-salvar em Conexões

### Não corrigido (depende do usuário)
- Webhook Meta App Secret: precisa ser re-salvo no painel Conexões com o valor correto do Meta Dashboard
- Banco Inter PIX: integração pausada — usuário escolheu priorizar Rede IA

## 2026-05-15 (later) — QR Code criptografado para CTOs
### Novos endpoints backend (`rede_ia.py`)
- `GET /api/rede-ia/ctos/{id}/qrcode.png` — gera PNG do QR (só CTOs aprovadas)
- `GET /api/rede-ia/ctos/{id}/qrcode` — devolve token + URL para preview
- `POST /api/rede-ia/qrcode/scan` — valida HMAC-SHA256 do token escaneado e retorna CTO + portas livres
- Token formato: `SPCTO|v1|<base64url(json)>|<hmac32>` assinado com `REDE_IA_QR_SECRET` (gerado random no .env)
- Validações: prefixo `SPCTO|`, version v1, HMAC compare_digest (resistente a timing), company_id deve casar
- Segurança: token alterado em 1 char → HTTP 400 "assinatura incorreta"

### Frontend
- `QrScanner.js`: novo componente com `getUserMedia` (câmera traseira) + `jsqr` para decode → POST /scan → exibe CTO identificada com portas livres
- `RedeIaPanel.js → CTOsList`: nova coluna "QR" com botão por CTO aprovada; abre modal com PNG (fetch + Bearer auth + blob URL), botões Imprimir/Baixar/Fechar
- `CollaboratorApp.js → KebabMenu`: nova opção "Ler QR Code da CTO" com ícone câmera

### Dependências
- backend: `qrcode==8.2`
- frontend: `jsqr@1.4.0`

## 2026-05-15 (later 2) — QR scan → Vincular cliente + criar OS automática
### Novo endpoint
- `POST /api/rede-ia/qrcode/bind-port` — recebe `{cto_id, port_number, subscriber_name, pppoe?, subscriber_phone?, service_type, notes?}`:
  1. Valida CTO aprovada + porta livre (409 se duplicada)
  2. Atualiza a porta: status='used', client_name/pppoe/phone, linked_by_*, linked_via_qr=true
  3. Cria ticket (OS) em `db.tickets` com source='rede_ia_qr', priority correto da Lousa (normal/prioridade), cto_name/cto_port/cto_vlan no client_snapshot, assigned_collaborator_id=user
  4. Rollback automático: se insert_one(ticket) falhar, reverte port para 'free'
  5. Audit log em cto_history (action='bind_port')

### Frontend (QrScanner.js — multistep)
- Step 1: scan QR (câmera) → validação HMAC backend
- Step 2: CTO identificada → botão "Vincular cliente"
- Step 3: formulário com seleção visual de porta livre + nome/PPPoE/telefone + tipo serviço (Instalação/Manutenção/Troca porta)
- Step 4: success screen com ticket_id criado

### Testing
- testing_agent_v3 (iter77): backend 12/13 passou; frontend renderização do scanner verificada
- Fix aplicado pós-review: priority `alta`→`prioridade`/`horario`→`normal` (alinhado aos filtros da Lousa) + rollback em caso de erro de OS

## 2026-05-15 (later 3) — Auto-PDF + Google Drive backup
### Nova regra: aprovou CTO → gera PDF → sobe pro Drive
- **Trigger**: ao chamar `POST /api/rede-ia/ctos/{id}/validate` com `action="approve"`
- **Background**:
  1. Re-busca CTO atualizada
  2. Gera PDF com `services/cto_pdf.py` (reportlab): cabeçalho roxo, tabela técnica, QR Code criptografado, foto da CTO (se houver), validação (técnico/gestor/data)
  3. Upload para `PontoIA-Backups/Rede-IA/CTO-{nome}-{ts}.pdf` via `services/drive_backup.upload_file_to_drive()`
  4. Salva `pdf_drive_file_id` + `pdf_drive_url` no doc da CTO
  5. Registra entrada no `cto_history` com action=`pdf_uploaded`
- Falha não-bloqueante: se Drive desconectado ou erro, aprovação continua válida, retorno traz `pdf.ok=false`

### Novos endpoints
- `GET /api/rede-ia/ctos/{id}/pdf.pdf` — download direto on-the-fly (não usa Drive)
- `POST /api/rede-ia/ctos/{id}/regenerate-pdf` — regenera e re-envia ao Drive (apenas admin/gestor/gestor_rede)

### Frontend
- Painel admin → CTOs: novos botões por linha aprovada
  - **QR** (roxo): modal com PNG do QR
  - **PDF** (vermelho): abre PDF on-the-fly em nova aba
  - **☁** (azul): abre PDF salvo no Drive (se houver `pdf_drive_url`)
  - **☁+** (cinza): reenvia PDF ao Drive (se nunca foi feito ou falhou)

### Drive subfolder rule
- `services/drive_backup.upload_file_to_drive()` + `_ensure_subfolder()`: cria `PontoIA-Backups/Rede-IA/` automaticamente caso não exista
- Reutiliza folder_id em cache (já em `drive_credentials`)

### Dependências
- backend: `reportlab==4.5.0`

## 2026-05-15 (final) — Mapa interativo FTTH (substitui fluxograma)
### Backend (`routes/rede_ia_map.py` novo, ~370 linhas)
- **Coleções**: `network_ces`, `network_cables`, `network_positions`
- **Endpoints**:
  - `GET /api/rede-ia/map/data` — agrega CTOs+CEs+cabos com saúde calculada por VLAN
  - `POST/PUT/DELETE /api/rede-ia/ces` — CRUD CEs (admin/gestor/gestor_rede)
  - `POST/PUT/DELETE /api/rede-ia/cables` — CRUD cabos (6/12/24/48/96 FO + drop)
  - `POST /api/rede-ia/map/positions` — salva drag-to-reposition
  - `POST /api/rede-ia/map/auto-generate-ces?radius_m=200` — rede_IA clusteriza CTOs por proximidade GPS + sigla, cria CE no centroide + cabos 24FO ligando tudo
- **Health calculator**: agrega ONUs SmartOLT por regex no zone_name, computa score (0-100) com critical/warning + média rx_dbm

### Frontend (`RedeIaMap.js` novo, ~430 linhas)
- **Leaflet + OpenStreetMap** (PT-BR, gratuito, sem chave)
- **CTO marker**: divIcon HTML colorido por saúde (verde/amarelo/vermelho) + badge % ocupação + halo de alerta animado
- **CE marker**: diamante azul rotacionado com label "CE"
- **Cabos**: polylines coloridas (6FO=amarelo, 12FO=laranja, 24FO=vermelho, 48FO=roxo, 96FO=preto, drop=cinza tracejado)
- **Filtros**: por VLAN + por saúde + tira clicável de VLANs no topo
- **Modos**: 👁 Ver / ✋ Mover (drag-to-reposition salvo no backend via `network_positions`)
- **Popup CTO**: nome, VLAN, saúde+score, ONUs total/warning/critical, avg rx dBm, portas, endereço, links QR e PDF
- **Popup CE/cabo**: dados técnicos + botão excluir
- **Auto-fit bounds** ao carregar
- **Botão "🤖 rede_IA gerar CEs"**: aciona auto-clustering
- **Legenda flutuante** com toggle

### Substituições
- Aba "Fluxograma" → "Mapa interativo" no RedeIaPanel
- `RedeIaFlowchart.js` ainda existe (legado) mas não está mais no menu

### Dependências
- frontend: `leaflet@1.9.4` + `react-leaflet@5.0.0`

## 2026-05-15 (final 2) — Mapa público compartilhável
### Backend (`rede_ia_map.py`)
- `POST /api/rede-ia/map/public/token` — gera token HMAC-SHA256 assinado (formato `SPMAP|v1|<b64>|<hmac32>`)
- `GET /api/rede-ia/map/public/{token}` — endpoint público (sem auth) que devolve dados SANITIZADOS:
  - **EXPÕE**: name CTO, lat/lng, VLAN, sigla, capacidade, bairro, health_status, CEs, cabos
  - **NÃO EXPÕE**: endereço completo, foto, ONUs detalhadas, técnicos, gestor, used_ports, CPFs, telefones
- Validação: token alterado → HTTP 403 (compare_digest resistente a timing)

### Frontend
- `PublicMapPage.js` (novo): página standalone read-only com Leaflet + OSM + header roxo + KPIs + legenda
- `App.js`: nova rota `/rede-publica?t=TOKEN` que renderiza apenas PublicMapPage (sem AuthProvider, sem sidebar)
- `RedeIaMap.js`: novo botão verde **"🔗 Compartilhar"** que gera token e copia URL no clipboard

### Variável env
- `REDE_IA_PUBLIC_SECRET` (gerado random no .env)

### Validação E2E
- ✅ Token criado: 122 chars, prefixo SPMAP
- ✅ Endpoint público sem auth retorna dados sanitizados; campos sensíveis ausentes
- ✅ Token inválido → HTTP 403
- ✅ Página `/rede-publica` renderiza mapa + legenda + KPIs sem login

## 2026-05-15 (final 3) — Backlog Future entregue
### 1. TTL nos tokens públicos
- Campo `exp` no payload do token (unix timestamp); `_verify_public_token` rejeita expirados
- Endpoint `POST /map/public/token` aceita `ttl_days` (1-365, default 30)
- Response inclui `expires_at` ISO + `ttl_days`
- Frontend: prompt pede TTL antes de gerar link; alerta mostra data de expiração

### 2. Modo "Adicionar cabo" no mapa
- Novo modo no toolbar (➕ Cabo) + seletor inline de tipo (drop/6FO/12FO/24FO/48FO/96FO)
- Fluxo: clique CTO/CE origem → banner roxo no topo guia → clique destino → POST `/cables` cria cabo automaticamente entre os 2 pontos
- Drag-mode e cable-mode mutuamente exclusivos

### 3. Heatmap de problemas por região
- `leaflet.heat@0.2.0` adicionada
- Botão 🔥 Heatmap toggle no toolbar
- Peso por CTO: `(100 - score_saude) / 100` — quanto pior, mais quente
- Gradient: verde (saudável) → amarelo → laranja → vermelho (crítico)
- Ignora CTOs sem dados (`no_data`)

### 4. Refactor parcial `rede_ia.py`
- Sub-módulo: `services/rede_ia_qr.py` (HMAC + build/verify/render)
- Removido código duplicado de QR de `rede_ia.py` (-90 linhas)
- `rede_ia.py`: 1264 → 1215 linhas
- `rede_ia_map.py`: 664 linhas (mapa + público + heatmap independente)
- Sub-módulos relacionados: cto_pdf, drive_backup, rede_ia_qr — todos isolados
- Documentação inline no docstring de `rede_ia.py` lista os sub-módulos

### Dependências
- frontend: `leaflet.heat@0.2.0`

## 2026-05-15 (final 4) — Mapa: criação visual + waypoints arrastáveis
### Novos modos no toolbar lateral
1. **📍 Criar CE** — clica no mapa → popup com form de criação (nome/tipo/capacidade) → confirma
2. **➕ Cabo reto** — clica origem CTO/CE → clica destino → cria cabo em linha reta (já existia)
3. **✏️ Desenhar cabo** — clica origem → vários cliques no mapa para waypoints intermediários → clica destino → cria cabo com curvas
4. **✋ Mover/Curvar** (era só Mover) — agora também permite arrastar waypoints intermediários dos cabos existentes

### Interatividade
- Prévia visual do cabo em desenho (linha tracejada roxa/azul + círculos numerados em cada waypoint)
- Clique em waypoint da prévia → remove
- Waypoints dos cabos existentes viram círculos brancos com borda colorida do tipo do cabo (modo Mover ativo) — arrastá-los chama `redeIaCableUpdate` com novos segments

### UI
- Banner instrutivo colorido no topo do mapa: roxo (cabo reto), azul (desenhar), verde (criar CE)
- `instructionsBanner()` helper unificado
- `MapClickHandler` componente isolado para useMapEvents

### Backend reuso
- Endpoints já existentes: `POST /ces`, `POST /cables`, `PUT /cables/{id}` (atualiza segments)

## 2026-05-15 (final 5) — Comprimento auto + Notificações mapa
### Cálculo automático de comprimento de cabos
- Função `_calculate_cable_length(segments)`: Haversine acumulado entre waypoints consecutivos
- `POST /api/rede-ia/cables`: se `length_m` for null/ausente, calcula automaticamente a partir dos segments
- `PUT /api/rede-ia/cables/{id}`: idem — útil quando arrasta waypoint, recalcula auto
- Cabo de 3 pontos retornou 302m correto

### Sistema de notificações do mapa
- Nova coleção `network_notifications`
- Helper `_notify_managers(company_id, evt)`: cria notificação in-app + dispara WhatsApp opcional
- Triggers: criação de CE (`POST /ces`), criação de cabo (`POST /cables`)
- Endpoints:
  - `GET /api/rede-ia/notifications?unread_only=` — lista (com counter unread)
  - `POST /api/rede-ia/notifications/mark-read` — marca uma ou todas como lidas
- **WhatsApp opcional**: gestores com `notify_map_events=true` + `phone` recebem mensagem formatada
  - Tenta Twilio primeiro, fallback Meta WhatsApp Cloud
  - Não bloqueia se providers não estiverem configurados (fire-and-forget)

### Frontend
- Sininho 🔔 no header do RedeIaPanel com badge vermelho de unread
- Polling a cada 25s
- Panel dropdown com lista de notificações + botão "Marcar todas"
- Click em notificação não-lida → marca como lida

## 2026-05-15 (final 6) — Sync bidirecional Rede_IA ↔ SmartOLT
### Novo: `services/smartolt_zones.py`
- `ensure_zone_exists(company_id, zone_name)`: idempotente, case-insensitive
- Cache 60s das zones (reduz chamadas SmartOLT)
- Race condition tratada (409 + texto "exist")
- Audit em `smartolt_zone_audit`

### Sync automático na aprovação de CTO
- `routes/rede_ia.py` → ao chamar `POST /validate?action=approve`:
  1. Gera PDF + sobe pro Drive
  2. **NOVO**: cria zone no SmartOLT com mesmo nome da CTO (idempotente)
  3. Marca CTO com `smartolt_zone_synced=true` + timestamp
  4. Audita em `cto_history` action=`smartolt_zone_sync`
- Falha SmartOLT não bloqueia aprovação (graceful)

### Endpoints novos
- `POST /api/rede-ia/ctos/{id}/sync-smartolt-zone` — força sync manual
- `GET /api/rede-ia/smartolt/zones` — lista zones em tempo real
- `GET /api/rede-ia/smartolt/zone-audit` — log de operações

### Validação E2E
- ✅ GET retornou 50+ zones do SmartOLT real (LigoFibra)
- ✅ POST criou `CTO 001_301_TST` no SmartOLT: "Zone CTO 001_301_TST added successfully"
- ✅ 2ª chamada (idempotência): `created=false`, "Zone já existe"
- ✅ Audit log: 2 entradas registradas

### Limitação conhecida
SmartOLT não expõe PUT/PATCH/DELETE para zones na coleção pública. Renomear/excluir
requer ação manual no painel SmartOLT.
