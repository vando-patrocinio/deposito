# PontoIA — Changelog

## Feb 10, 2026 — Botão "Forçar descoberta IA" + otimização por prefixo

### Backend
- `routes/stok.py`:
  - Novo endpoint `POST /api/stok/clientes/identify-all?force=false` — roda IA Gemini em todos os prefixos de SN ainda desconhecidos (sample 1 SN por prefixo). Logado em histórico
  - Refatoração de `_detect_many_manufacturers` → `_detect_by_prefix`: agrupa SNs por prefixo (4 chars), resolve UMA vez por prefixo único, aplica a todos os SNs do mesmo grupo
  - Performance: 1.749 ONUs com 81% de identificação após uma única chamada (antes: ≤200 SNs/call por causa do limite). Cache permanente em `manufacturer_cache` torna chamadas seguintes instantâneas

### Frontend  
- `EstoquePanel.js > ClientesSection`:
  - Novo botão "Forçar descoberta IA" (`data-testid=clientes-identify-all`) ao lado de "Atualizar"
  - Confirmação prévia, alerta com resultado (X novos fabricantes, Y prefixos testados, Z desconhecidos antes), recarrega tabela após
- `api.js`: nova função `stokClientesIdentifyAll(force=false)`

### Resultado real (1.749 ONUs co-demo)
- Antes: 5 identificadas (0.3%)
- Após otimização por prefixo: **1.418 identificadas (81.1%)**
- Distribuição: ZTE 316, Huawei 310, Nokia/Alcatel-Lucent 297, Fiberhome 290, TP-Link 61, V-SOL 56, Intelbras 51, Dasan 21, D-Link 16, Desconhecido 331

---

## Feb 10, 2026 — Estoque > Clientes (SmartOLT) com identificação de fabricante via IA
- Endpoint `GET /api/stok/clientes` lê db.smartolt_onus
- Aba "Clientes (SmartOLT)" com 5 stat cards + tabela (Cliente, SN, MAC, Marca/Fabricante, OLT/Slot/PON, Sinal, Autorização)
- testing_agent_v3_fork iter31+iter32: 100% backend + 100% frontend

## Feb 10, 2026 — Vehicle Checklist FULL: 5 silhuetas + photo upload + IA recurrent defects

## Feb 10, 2026 — Checklist Veicular CONTRAN + Rename "Pertences" → "Checklist"

## Feb 10, 2026 — Mapa de Defeitos sincronizado com Lousa + UI Redesign Major

## Feb 9, 2026 — Lousa fixed slot heights + Wipe-all + Asset deactivation auto-popup

## Feb 8, 2026 — IA Center, EPIs, Tab Permissions, Hardware Detection
