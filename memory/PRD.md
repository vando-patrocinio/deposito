# PRD — Sistema Mesclado SmartProv + Selfie Attendance + Stok + Atlaz V2 + SmartOLT + IA Center + Pertences/Romaneio

## Visão Geral
Plataforma operacional completa para provedor FTTH (foco: Ligo Fibra). Reúne:
- **Ponto facial** offline-first (selfie + cerca virtual + sync)
- **Lousa Kanban** (drag-and-drop) com sync Atlaz V2 em tempo real
- **Estoque** (Stok) por colaborador com baixa automática ao finalizar bolha
- **SmartOLT** integrado (sinal vivo nas bolhas + validação MAC)
- **IA Preventiva** (sugere bolhas para sinais ruins, técnico ocioso)
- **IA Center** (8 sub-abas: KPIs, gastos por técnico, mapa de defeitos Leaflet, equipamentos defeituosos, reclamações, reincidência, **pertences/perdas**, insights LLM Gemini)
- **Pertences/EPIs** com Romaneio PDF assinado digitalmente, branding personalizado, dashboard de perdas pendentes

## Stack
- Backend: FastAPI + Motor (MongoDB) + reportlab (PDFs) + emergentintegrations (Gemini Flash)
- Frontend: React (CRA + craco) + react-leaflet + html5-qrcode + axios
- Auth: JWT com bcrypt
- ESLint 9 flat config + ruff

## Histórico Recente (esta sessão)
1. ✅ **IA Center backend + frontend**: 8 sub-abas com KPIs, mapa heatmap, insights LLM
2. ✅ **Code Quality fixes**: removido syntax error AIPreventivePanel, eliminado componente em render (LousaMobile.ConsumableField), substituído `__import__('fastapi')` por imports estáticos, removida variável morta
3. ✅ **ESLint guardrails**: eslint.config.js flat com `react-hooks/exhaustive-deps: error` strict pra arquivos novos + LEGACY_FILES whitelist pra não bloquear CI nos 108 violations existentes. Scripts `yarn lint` / `yarn lint:strict`
4. ✅ **Bug fix SLA**: bolhas em `pendente`/`aguardando` com `scheduled_time` agora computam SLA via modo `schedule` (deadline = agendado + sla_min). Bolhas sem horário usam modo `queue` (created_at + grace 60min). Pisca uniforme em todas as bolhas atrasadas
5. ✅ **Sistema Pertences/EPIs completo**:
   - Backend: `routes/branding.py` (logo + dados empresa) + `routes/collaborator_assets.py` (CRUD + assinatura digital + PDF reportlab)
   - Frontend: `BrandingCard.js`, `AssetsSection.js`, `MyAssetsModal.js`, aba 🎒 Pertences no IA Center
   - Romaneio PDF (~3KB) com logo, dados empresa, tabela itens, linha assinatura
6. ✅ **Perdas Pendentes**: hook em `update_collaborator` quando active=true→false → cria notification + grava deactivated_at. Dashboard mostra prejuízo estimado em BRL
7. ✅ **Valores customizáveis por categoria**: BrandingCard com 6 inputs (uniforme/epi/ferramenta/veículo/eletrônico/outro) — persistido em `default_asset_values_brl` no branding
8. ✅ **Valor unitário visível**: tabela AssetsSection (gestor) e cards MyAssetsModal (mobile) mostram R$ por item × qty
9. ✅ **Hardening do /public/sign**: valida colaborador existe (404) e retorna 404 quando asset_ids não pertencem ao colaborador. Usa `modified_count` real

## Validação E2E desta sessão
- Iteration 26: backend 24/25 (96%), frontend 4/4 (100%). retest_needed=False
- Curl tests confirmam: PDF magic %PDF, branding persistido, pending_losses calculado corretamente (R$ 1.160,00 testado), notification automática criada

## Próximas tasks (P1/P2)
- 🟡 Botão "Marcar todos como devolvidos" para resolver perdas pendentes em lote
- 🟡 Refactor `routes/lousa.py` (>2300 linhas) em sub-módulos
- 🟡 Migrar tokens localStorage → httpOnly cookies + CSRF (security item do code review)
- 🟡 Object storage para logos/avatares (substitui base64 do Mongo)
- 🟡 WhatsApp Business API (precisa Meta access token do usuário)
- 🟢 Limpar gradualmente os 34 ESLint warnings dos arquivos legacy
- 🟢 Cache curto (5min) por dashboard pra reduzir custo LLM em insights repetidos
- 🟢 Hook husky pre-commit pra bloquear push com `yarn lint:strict` falhando

## Arquitetura
```
/app/
├── backend/
│   ├── routes/
│   │   ├── clock.py (gerenciamento colaboradores + ponto)
│   │   ├── lousa.py (Kanban + SLA + Atlaz sync) — [P2 refactor]
│   │   ├── stok.py + smartolt.py + atlaz.py
│   │   ├── ai_preventive.py (worker)
│   │   ├── ai_dashboard.py (8 endpoints + assets-overview + pending_losses)
│   │   ├── branding.py (NEW — logo + default_asset_values_brl)
│   │   ├── collaborator_assets.py (NEW — CRUD + PDF reportlab + sign)
│   │   └── notifications.py
│   └── tests/test_iteration*.py (extensa cobertura pytest)
├── frontend/
│   ├── eslint.config.js (NEW — flat config strict)
│   └── src/
│       ├── App.js (rotas)
│       ├── AICenterPanel.js (8 sub-abas)
│       ├── BrandingCard.js (NEW)
│       ├── AssetsSection.js (NEW — gestor)
│       ├── MyAssetsModal.js (NEW — mobile + canvas signature pad)
│       ├── CollaboratorApp.js (kebab com Meus pertences)
│       └── CadastroPanel.js (botão 🎒 Pertences por colaborador)
└── memory/
    ├── PRD.md (este)
    └── test_credentials.md
```

## Endpoints novos desta sessão
```
GET/PUT /api/branding/settings
GET     /api/branding/public

GET     /api/collab-assets/by-collaborator/{cid}
POST    /api/collab-assets
PATCH   /api/collab-assets/{aid}
DELETE  /api/collab-assets/{aid}
GET     /api/collab-assets/romaneio/{cid}            (PDF)
GET     /api/collab-assets/public/by-collaborator/{cid}
POST    /api/collab-assets/public/sign
GET     /api/collab-assets/public/romaneio/{cid}     (PDF público)

GET     /api/ai/dashboard/assets-overview            (KPIs + pending_losses)
```

## Coleções MongoDB novas
- `company_branding` (1 doc por company_id)
- `collaborator_assets` (assets com events[])
- `notifications` (já existia, novo type: `assets_pending_return`)
