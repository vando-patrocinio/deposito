# PontoIA — Changelog

## Feb 10, 2026 — Estoque > Clientes (SmartOLT) com identificação de fabricante via IA

### Backend
- `routes/stok.py`: novo endpoint `GET /api/stok/clientes` que lê `db.smartolt_onus`, retorna por cliente `{client_name, sn, mac, manufacturer, model, olt_name, board, port, signal_text, authorization_date}`. Identificação de fabricante via `manufacturers.identify_manufacturer(sn)` (prefixo IEEE/CCM hex/ascii + fallback Gemini Flash, cache permanente em `manufacturer_cache`). Limite `identify_manufacturer_max=200` por chamada; semáforo concorrência 6
- Filtro `only_authorized=true` ignora ONUs sem `authorization_date`

### Frontend
- `EstoquePanel.js` SUB_TABS reorganizado:
  - "Serviços" → renomeado para **"Ordens de serviço"**  
  - Nova aba **"Clientes (SmartOLT)"** entre Insumos e Ordens de serviço
- `ClientesSection` (~165 LOC): 5 stat cards (Clientes, Identificados/total, Top-3 fabricantes), tabela 7 colunas (Cliente, SN, MAC, Marca/Fabricante, OLT/Slot/PON, Sinal, Autorização), busca em tempo real, filtro por fabricante, paginação visual a 500 linhas com aviso "Mostrando 500 de N"
- Pills: `.pill--accent` (teal) quando manufacturer identificado, `.pill--neutral` quando "Desconhecido"
- `api.js`: nova função `stokClientes(identify_manufacturer_max=200)`

### Validação
- Pytest backend: já 100% (iter31)
- Playwright frontend: **100% (iter32)** — 13 checks, 1.749 ONUs reais, 194 fabricantes identificados via IA (Nokia/Alcatel-Lucent 189, Intelbras 5), filtros funcionando, sem console errors

---

## Feb 10, 2026 — Vehicle Checklist FULL: Damage marks (5 silhouettes) + Photo upload + Recurrent defects insight
- `vehicle_silhouettes.py` — 5 silhuetas via ReportLab primitives (Frente/Traseira/Laterais/Topo)
- DamageMark + Attachment models
- POST/DELETE `/{id}/attachment`, GET `/insights/recurrent-defects`
- PDF multi-página com grade 2×3 silhuetas + marcas + legenda + tabela detalhada + anexos validados via `PIL.verify()`
- IA Center sub-aba "Frota" com FleetDefectsSection
- testing_agent_v3_fork iter30: 100% (11/11 backend + Playwright 0 erros)

## Feb 10, 2026 — Checklist Veicular CONTRAN + Rename "Pertences" → "Checklist"
- 30 itens em 8 categorias seguindo Resolução CONTRAN 14/98
- PDF profissional com termo CONTRAN
- testing_agent_v3_fork iter29: 100%

## Feb 10, 2026 — Mapa de Defeitos sincronizado com Lousa + UI Redesign Major
- Geocoding sob-demanda Nominatim (10 → 31 pontos no mapa)
- Design system Slate+Teal · Manrope/JetBrains Mono · Sidebar lateral fixa
- testing_agent_v3_fork iter27 + iter28: 100% pass

## Feb 9, 2026 — Lousa fixed slot heights + Wipe-all + Asset deactivation auto-popup

## Feb 8, 2026 — IA Center, EPIs, Tab Permissions, Hardware Detection
