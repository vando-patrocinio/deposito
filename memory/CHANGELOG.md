# PontoIA — Changelog

## Feb 10, 2026 — Checklist Veicular CONTRAN + Rename "Pertences" → "Checklist"
**Trigger**: User pediu para 1) trocar "Pertences" por "Checklist", 2) criar romaneio dos itens em custódia (já existia, só renomeado), 3) criar Checklist Veicular novo (pesquisado online), 4) tudo dentro do Cadastro do Colaborador, 5) layout profissional.

### Backend novo
- `/app/backend/routes/vehicle_checklist.py` — módulo completo:
  - Template padrão com **30 itens em 8 categorias** (Documentação, Pneus, Iluminação, Freios, Fluidos, Segurança, Externo/Interno, Motorista) seguindo Resolução CONTRAN 14/98 + ALISAT/Cobli/TOTVS 2026
  - Status por item: `ok | defeito | na`
  - Cálculo automático de **% conformidade** (NA excluído do denominador)
  - CRUD completo: POST/GET/list/PATCH/DELETE
  - **PDF profissional** via ReportLab: cabeçalho da empresa, bloco de identificação (motorista, placa, KM, rota), conformidade em destaque com cor por threshold (verde/âmbar/vermelho), tabela de itens agrupados por categoria com células coloridas por status, termo de responsabilidade CONTRAN, área de assinatura digital ou manual
  - Hierarquia de roles: create=colaborador+, list/PDF=gestor+, delete=auditor+
  - Endpoint registrado em `server.py`

### Backend modificado
- `collaborator_assets.py`: título do PDF mudou para **"CHECKLIST DE CUSTÓDIA — TERMO DE RESPONSABILIDADE"** (era "ROMANEIO DE ENTREGA…"). Subtítulo teal "Equipamentos · Uniforme · EPIs · Ferramental"

### Frontend novo
- `/app/frontend/src/VehicleChecklistModal.js` — modal full com 2 abas:
  - **Novo checklist**: form de identificação (placa obrigatória, marca, modelo, ano, km, rota), conformidade prevista com cor dinâmica, 30 itens agrupados em pills de categoria (teal), 3 botões selecionáveis por item (OK/Defeito/N/A), input de notas obrigatório se defeito, observações gerais, botão "Salvar e gerar PDF" abre o PDF em nova aba
  - **Histórico**: tabela com data, placa, veículo, KM, conformidade colorida, botões PDF + remover

### Frontend modificado
- `CadastroPanel.js`: import VehicleChecklistModal, state `vehicleChecklistFor`, novo botão **"Veicular"** (azul claro, ícone Car) ao lado do botão **"Checklist"** (teal, ícone Clipboard) — ambos por colaborador
- `api.js`: novas funções `vehicleChecklistTemplate/List/Get/Create/Update/Delete/PdfUrl`
- Rename global "Pertences" → "Checklist" em: AICenterPanel.js, AssetsSection.js, CadastroPanel.js, CollaboratorApp.js, DeactivationAssetsModal.js, MyAssetsModal.js
- Variável "pertences" (substantivo) → "itens em custódia" para clareza

### Validação
- ESLint: 0 errors
- testing_agent_v3_fork iter29: **100% pass** (backend 9/9 pytest, frontend Playwright 0 console errors)
- Manual smoke test: PDF veicular = 21KB, conformidade 93.3%, 2 defeitos detectados, romaneio EPI = 18KB

---

## Feb 10, 2026 — Mapa de Defeitos sincronizado com Lousa + UI redesign
- Endpoint `/api/ai/dashboard/repair-map` agora geocodifica endereços de tickets sem lat/lng on-demand (até 60 por chamada, semáforo concorrência 4)
- Cache persistente: lat/lng salvos de volta no documento Mongo
- Frontend mostra pills "+N geolocalizadas" e "N pendentes — geolocalizando…", auto-refetch a cada 1.5s
- Resultado: 10 → 31 pontos no mapa após 2 chamadas

## Feb 10, 2026 — Major UI/UX Redesign (clean, sober, professional B2B)
- Design system Slate+Teal · Manrope/JetBrains Mono · Sidebar lateral fixa categorizada (5 grupos)
- LoginPage split layout (form light + brand pillar dark teal)
- Lousa Kanban polida (sem gradientes, AI button teal)
- Emojis removidos de h1/h2/h3/h4 e atributos title/label em 15 painéis desktop
- Mobile preservado (LousaMobile, CollaboratorApp, AssetsSection)
- testing_agent_v3_fork iter27 + iter28: 100% pass

## Feb 9, 2026 — Lousa fixed slot heights + Wipe-all + Asset deactivation auto-popup

## Feb 8, 2026 — IA Center, EPIs, Tab Permissions, Hardware Detection
