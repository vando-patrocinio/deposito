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
✅ Pytest backend + ESLint frontend ativos
✅ Roadmap pronto em `/app/memory/ROADMAP.md`
