# PontoIA — Changelog

## Feb 10, 2026 — Vehicle Checklist FULL: Damage marks (5 silhouettes) + Photo upload + Recurrent defects insight

### Backend novo
- `/app/backend/routes/vehicle_silhouettes.py` — 5 silhuetas via ReportLab primitives (Frente, Traseira, Lateral esq/dir, Vista superior). ViewBox 200×110 com flip-Y para alinhar com SVG do frontend (coordenadas 1:1 entre clique do usuário e PDF)
- `vehicle_checklist.py` ganhou:
  - Modelos `DamageMark` (view, x∈[0,200], y∈[0,110], code D|S|R|F|V|P, ord, notes) e `Attachment` (kind, label, data_url)
  - POST `/api/vehicle-checklist/{id}/attachment` — adiciona anexo individual (≤8MB)
  - DELETE `/api/vehicle-checklist/{id}/attachment/{idx}` — remove anexo por índice
  - GET `/api/vehicle-checklist/insights/recurrent-defects?days=30&min_count=3` — agrega defeitos por (placa, item) e retorna alertas para o gestor
  - `_build_damage_pages()` — adiciona página extra ao PDF com:
    - Grade 2×3 com as 5 silhuetas + marcas numeradas/coloridas (D=vermelho amassado, S=âmbar risco, R=marrom oxidação, F=vermelho-escuro quebrado, V=azul vidro, P=cinza pintura)
    - Legenda no 6º slot (cód. + tipo)
    - Tabela detalhada das avarias
    - Anexos renderizados inline (validados via `PIL.Image.verify()` — PDF resilient a bytes corrompidos)

### Frontend novo
- `/app/frontend/src/VehicleSilhouettes.js` — componente `VehicleSilhouette` + 5 sub-SVGs (corpo, janelas tintadas, rodas, faróis amarelos, lanternas vermelhas, grade preta, retrovisores). `viewBox` 200×110 sincronizado com backend
- `VehicleChecklistModal.js` ganhou:
  - Seção "Diagrama de avarias" — 5 silhuetas clicáveis (cursor crosshair); clique abre `vchk-mark-editor` para escolher código + descrição; marcas exibidas como círculos coloridos numerados; tabela editável com remover por linha
  - Seção "Anexos" — botão `vchk-attach-btn` abre file picker (image/* até 8MB, lê como base64 via FileReader); grid de miniaturas 110px com botão remover por anexo
  - Submit envia `damage_marks` e `attachments` ao backend

### IA Center
- Nova sub-aba **"Frota"** (`tab-fleet`) com `FleetDefectsSection`: tabela de placas+itens com defeito ≥2× nos últimos 30 dias, mostrando ocorrências, última data e último motorista. Empty state quando 0

### api.js
- `vehicleChecklistAttach`, `vehicleChecklistAttachRemove`, `vehicleChecklistRecurrent`

### Validação
- ESLint: 0 errors
- Pytest: 11/11 (iter30) — incluindo teste de PDF resilient a anexo corrompido
- Playwright iter30: 100% (silhuetas renderizadas com todas as proporções, marcas criáveis em todas as 5 vistas, upload + miniatura, PDF multi-página gerando)
- Smoke: PDF do TST-MK99 = 30KB com 5 marcas + 1 anexo JPEG válido + legenda

---

## Feb 10, 2026 — Checklist Veicular CONTRAN + Rename "Pertences" → "Checklist"
- 30 itens em 8 categorias (Documentação, Pneus, Iluminação, Freios, Fluidos, Segurança, Externo/Interno, Motorista)
- PDF profissional com cabeçalho da empresa, tabela colorida por status, termo CONTRAN, área de assinatura
- Rename Pertences → Checklist em 6 arquivos do frontend
- testing_agent_v3_fork iter29: 100% (9/9 backend + Playwright 0 console errors)

## Feb 10, 2026 — Mapa de Defeitos sincronizado com Lousa + UI Redesign Major
- Geocoding sob-demanda para tickets sem lat/lng (Nominatim/OSM, ≤4 paralelos)
- Cache persistente: lat/lng salvos em Mongo; 10 → 31 pontos no mapa após 2 chamadas
- Design system Slate+Teal · Manrope/JetBrains Mono · Sidebar lateral fixa categorizada
- Login split layout · Lousa polida · Emojis removidos do desktop
- testing_agent_v3_fork iter27 + iter28: 100% pass

## Feb 9, 2026 — Lousa fixed slot heights + Wipe-all + Asset deactivation auto-popup

## Feb 8, 2026 — IA Center, EPIs, Tab Permissions, Hardware Detection
