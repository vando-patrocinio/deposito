# PontoIA — Changelog

## Feb 10, 2026 — Inferência por similaridade (batch LLM com contexto)

### Backend
- `manufacturers.py`: nova função `identify_by_similarity_batch(unknown_sns, max_per_batch=30)` — agrupa prefixos desconhecidos em batches de 30 e envia ao Gemini Flash com **contexto rico**: catálogo completo de prefixos já cadastrados (KNOWN_PREFIXES + cache positivo agrupado por fabricante) como exemplos de aprendizado in-context. A IA infere fabricante usando similaridade estrutural, padrões de prefixo e contexto FTTH brasileiro
- Resposta JSON pura validada via regex; resultados (positivos e negativos) persistidos em `manufacturer_cache` com `source='llm-similarity'`
- `routes/stok.py`: endpoint `POST /api/stok/clientes/identify-all` ganhou parâmetro `use_similarity=true` (padrão). Modo legacy (`use_similarity=false`) ainda disponível para fallback

### Resultado real (1.749 ONUs co-demo)
- 1ª chamada (prefix lookup + cache): **81.1%** identificados
- 2ª chamada (similarity batch LLM): **89.0%** identificados (+8 pontos)
- Distribuição final: ZTE 316, Huawei 310, Nokia 297, Fiberhome 290, Dasan 141, TP-Link 61, V-SOL 56, Intelbras 51, D-Link 35, Desconhecido 192
- Novos fabricantes descobertos por similaridade: variações de prefixo de Dasan (subiu de 21→141), D-Link (16→35)

---

## Feb 10, 2026 — Botão "Forçar descoberta IA" + otimização por prefixo
- Endpoint `POST /api/stok/clientes/identify-all` (1ª versão sem similarity)
- Refatoração `_detect_many_manufacturers` → `_detect_by_prefix` (1 lookup por prefixo único, não por SN)
- Botão "Forçar descoberta IA" no ClientesSection
- Performance: 5 (0.3%) → 1.418 (81.1%) identificadas

## Feb 10, 2026 — Estoque > Clientes (SmartOLT) com identificação de fabricante via IA

## Feb 10, 2026 — Vehicle Checklist FULL: 5 silhuetas + photo upload + IA recurrent defects

## Feb 10, 2026 — Checklist Veicular CONTRAN + Rename "Pertences" → "Checklist"

## Feb 10, 2026 — Mapa de Defeitos sincronizado com Lousa + UI Redesign Major

## Feb 9, 2026 — Lousa fixed slot heights + Wipe-all + Asset deactivation auto-popup

## Feb 8, 2026 — IA Center, EPIs, Tab Permissions, Hardware Detection
