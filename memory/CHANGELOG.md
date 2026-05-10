# PontoIA — Changelog

## Feb 10, 2026 — Major UI/UX Redesign (clean, sober, professional B2B)
**Trigger**: User pediu pesquisa das melhores práticas de sistemas de provedor de internet e redesign profissional, clean, sóbrio, limpo.

### Foundation
- `index.css` reescrito: design tokens Slate+Teal, Manrope (Google Fonts), JetBrains Mono, classes utilitárias `.btn`, `.surface`, `.stat-card`, `.pill`, `.input`, `.app-sidebar`, `.app-topbar`, `.page-header`.
- `tailwind.config.js`: fontFamily Manrope/JetBrains Mono.
- `ui.js` reescrito: `Icon` agora usa Lucide-react (eliminou emojis), `Button` usa classes `.btn-*`, `Card` ganhou subtitle, `Metric` usa `.stat-card`, `StatusBadge` usa `.pill--variant`.

### App Shell
- `App.js` reescrito (~564 linhas): tab navigation top → **Sidebar lateral fixa 248px** (slate dark), categorizada em 5 grupos (Operação · Inteligência · Pessoas · Compliance · Sistema).
- Novo `TopBar` com breadcrumb dinâmico (Grupo › Aba › Empresa), select de drill-down (super admin), modo celular, IA, notificações, relógio, user chip, logout.
- `ImpersonationBanner` agora é amber sóbrio (não roxo gradiente).

### Login
- `LoginPage.js` redesign split: form light esquerda + brand pillar dark right com 3 pillars (Lousa Kanban / Estoque / IA com geofence) e textura grid teal sutil.

### Lousa
- Header usa `.page-header`; emojis removidos.
- `PRIORITY_COLORS` sem gradientes (cores planas + borda lateral).
- Avatar técnico em teal (`#0d9488 → #0f766e`); pills de teste/nota em slate/teal sóbrias.
- Botão de Avaliação IA mudou de roxo (`#a855f7`) para teal (`#0d9488`).

### Polish global
- Emojis removidos de h1/h2/h3/h4 e atributos `title=`/`label=` em 15 painéis (Dashboard, AICenter, Estoque, Settings, Cadastro, Praças, AI Ranking, AI Preventiva, Branding, Atlaz, SmartOLT, Users, Platform, etc.).
- Substituição global de hex purple/violet (#7c3aed, #a855f7, #5b21b6, #8b5cf6, #6d28d9, #ede9fe, #ddd6fe, #d8b4fe, #f3e8ff, #faf5ff) por equivalentes teal/slate em 11 arquivos.
- `NotificationsBell.js`: emoji `🔔` → Lucide `Bell` icon, integrado ao botão `.btn-ghost`.

### Mobile (preservado)
- `LousaMobile.js`, `CollaboratorApp.js`, `AssetsSection.js` mantidos com emojis intencionais (UX mobile).

### Validação
- ESLint: 0 errors, 34 warnings (todas pré-existentes, não-bloqueantes).
- testing_agent_v3_fork iter27: 100% (11/11 tabs funcionam, login OK, sidebar OK).
- testing_agent_v3_fork iter28: 95% → 5 emojis residuais limpos no follow-up; sem regressões; Atlaz V2 sync confirmado funcionando (19 cols × 68 tickets na Lousa).

### Files modificados
Frontend (24): App.js, ui.js, index.css, tailwind.config.js, LoginPage.js, LousaAdminPanel.js, AICenterPanel.js, AIPreventivePanel.js, AiRankingPanel.js, DashboardPanel.js, EstoquePanel.js, StokPanel.js, SettingsPanel.js, BrandingCard.js, AtlazIntegrationCard.js, SmartoltIntegrationCard.js, CadastroPanel.js, PracasPanel.js, UsersPanel.js, PlatformAdminPanel.js, LogsPanel.js, MyAssetsModal.js, QRScannerModal.js, NotificationsBell.js, LandingPage.js, AssetsSection.js.

---

## (anterior) Feb 9, 2026 — Lousa fixed slot heights + Wipe-all + Asset deactivation auto-popup
- SlotRow refatorado com altura fixa 64px por hora; bolhas empilham/sobrepõem visualmente.
- Endpoint `POST /api/lousa/tickets/wipe-all` exclusivo de auditor.
- Modal popup de pendências ao desativar colaborador, com PDF.

## (anterior) Feb 8, 2026 — IA Center, EPIs, Tab Permissions, Hardware Detection
- IA Center heatmap OSM PT-BR com bounds IQR P15-P85.
- CRUD `collaborator_assets` + valores padrão + romaneio PDF (mesmo vazio).
- `TabPermissionsCard` para configurar visibilidade de abas por role.
- `manufacturers.py` detecta fabricante OLT via SN prefixes (Huawei/ZTE/Nokia + Gemini fallback).
