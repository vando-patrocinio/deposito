# PontoIA — Changelog

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
