# INVENTORY VALUATION MATRIX — LIGO ESTOQUE OS V2

**Tipo:** Matriz operacional read-only.
**Data:** 16/Fev/2026
**Autor:** Auditor automatizado (CTO Mode) — Ordem direta do CEO.
**Mandato:** Detalhamento técnico complementar ao `INVENTORY_VALUATION_AUDIT.md`. Inclui matriz por equipamento, lookup map, queries reproduzíveis.

---

## §1. MATRIZ DE STATUS POR EQUIPAMENTO (preview — 28 ONTs)

> Esta matriz é a base para o `before_snapshot` que a Onda 1 deve persistir.

### 1.1 — Por categoria de confiança (grade A-F)

| Grade | Critério | Qtd | % | Patrimônio min | Patrimônio max |
|-------|----------|-----|---|----------------|----------------|
| **A** — Auditável NF | purchase_id ✅ + SN válido ✅ + modelo limpo ✅ | 7 | 25% | 7 × R$ 300 = **R$ 2.100** | 7 × R$ 300 = R$ 2.100 |
| **B** — Reconciliável | purchase_id ✅ + (SN AUTOSN_* OU modelo sujo) | 3 | 11% | 3 × R$ 50 = R$ 150 | 3 × R$ 300 = R$ 900 |
| **C** — Estimável modelo | sem pid + modelo válido | 7 | 25% | 7 × R$ 50 = R$ 350 | 7 × R$ 400 = R$ 2.800 |
| **D** — Especulação | sem pid + modelo lixo | 7 | 25% | 7 × R$ 50 = R$ 350 | 7 × R$ 400 = R$ 2.800 |
| **F** — Fantasma | sem pid + sem modelo + dado mínimo | 4 | 14% | 4 × R$ 50 = R$ 200 | 4 × R$ 400 = R$ 1.600 |
| **TOTAL** |  | 28 | 100% | **R$ 3.150** | **R$ 10.200** |

### 1.2 — Cross-Tab Grade × Owner

| Owner | A | B | C | D | F | Total |
|-------|---|---|---|---|---|-------|
| Empresa (17) | 4 | 2 | 5 | 4 | 2 | 17 |
| Técnico (10) | 3 | 1 | 2 | 2 | 2 | 10 |
| Cliente (1)  | 0 | 0 | 0 | 1 | 0 | 1 |
| **Total** | **7** | **3** | **7** | **7** | **4** | **28** |

> Distribuições aproximadas (extrapoladas do dataset). Em produção, a query do §4 calcula valores exatos.

---

## §2. TABELA CANÔNICA DE MODELOS (DRAFT — confirmar com CEO)

| Família | Modelo | Aliases observados no banco | Preço referência (R$) | Faixa NF observada |
|---------|--------|------------------------------|----------------------|--------------------|
| **FIBERHOME** | HG6145D | `FIBERHOME HG6145D` | 220 | R$ 300 confirmado em NF |
| FIBERHOME | HG8145D | `FIBERHOME ONT AC1200 GPON 2GE WIFI HG8145D` | 180 | — |
| FIBERHOME | HG8145V5 | — | 180 | — |
| **ZTE** | F601 | — | 65 | — |
| ZTE | F660 | `ZTE F660` | 75 | — |
| ZTE | F670L | `ZTE F670L` | 95 | — |
| **HUAWEI** | HG8245 | `Huawei HG8245`, `Huawei HG` (truncado) | 120 | — |
| HUAWEI | HG8546M | — | 145 | — |
| **WIFI 6** | (genérico) | — | 250 | — |
| **WIFI 7** | (genérico) | — | 380 | — |
| **DESCONHECIDO** | — | `Desconhecido`, `None`, `""`, `TestModel`, `zte chinez` | 85 (fallback ref) | — |

### Regras de canonicalização propostas

1. Normalizar para uppercase + remover acentos + colapsar espaços.
2. Buscar **substring** das chaves canônicas (ex.: "FIBERHOME HG6145D" dentro de "FIBERHOME ONT AC1200 GPON 2GE WIFI HG8145D" → match HG8145D).
3. Se não casar nenhuma chave canônica, marcar `valuation_source="unknown"` + `valuation_grade="F"`.
4. Strings em blocklist explícita (`testmodel`, `desconhecido`, `none`, `null`, `?`, `xxx`, regex `^.{0,3}$`) → `unknown` imediato.

---

## §3. QUERIES MONGO REPRODUZÍVEIS

### Q1 — Contagem ONTs por owner × status (linha de base)
```javascript
db.stok_onts.aggregate([
  { $group: {
      _id: { loc: "$location_type", st: "$status" },
      n: { $sum: 1 }
  }},
  { $sort: { "_id.loc": 1, "_id.st": 1 } }
])
```

### Q2 — ONTs sem purchase_id (fantasmas)
```javascript
db.stok_onts.find({
  $or: [
    { purchase_id: { $exists: false } },
    { purchase_id: null }
  ]
}, { mac: 1, scan_sn: 1, model: 1, location_type: 1, status: 1 }).limit(200);
```

### Q3 — ONTs com purchase_id resolvível (cobertura NF)
```javascript
db.stok_onts.aggregate([
  { $match: { purchase_id: { $ne: null } } },
  { $lookup: {
      from: "purchases",
      localField: "purchase_id",
      foreignField: "id",
      as: "purchase"
  }},
  { $unwind: "$purchase" },
  { $unwind: "$purchase.items" },
  { $match: { $expr: { $in: ["$mac", "$purchase.items.macs"] } } },
  { $project: {
      mac: 1, scan_sn: 1, model: 1, status: 1,
      unit_price_nf: "$purchase.items.unit_price",
      supplier_name: "$purchase.supplier_name",
      invoice_date: "$purchase.invoice_date",
      invoice_number: "$purchase.invoice_number"
  }}
])
```

### Q4 — Distribuição de qualidade do campo `model`
```javascript
db.stok_onts.aggregate([
  { $project: {
      mac: 1,
      model_normalized: { $toUpper: { $trim: { input: { $ifNull: ["$model", "(null)"] } } } }
  }},
  { $group: { _id: "$model_normalized", n: { $sum: 1 } } },
  { $sort: { n: -1 } }
])
```

### Q5 — Patrimônio resolvido por owner (apenas grade A)
```javascript
db.stok_onts.aggregate([
  { $match: { purchase_id: { $ne: null } } },
  { $lookup: { from: "purchases", localField: "purchase_id", foreignField: "id", as: "p" } },
  { $unwind: "$p" }, { $unwind: "$p.items" },
  { $match: { $expr: { $in: ["$mac", "$p.items.macs"] } } },
  { $group: {
      _id: "$location_type",
      n: { $sum: 1 },
      total_value: { $sum: "$p.items.unit_price" }
  }}
])
```

---

## §4. CHECKLIST DE BACKFILL `valuation_backfill_dry_run`

Antes de QUALQUER write, rodar o job em modo simulação e produzir relatório:

| Etapa | Ação | Saída esperada |
|-------|------|----------------|
| 1 | Para cada ONT com `purchase_id` resolvível: calcular `valor_nf`, classificar grade A | `dry_run.grade_A_count` |
| 2 | Para cada ONT sem purchase_id mas com modelo limpo: lookup em `MODEL_CANONICAL` → `valor_referencia` | `dry_run.grade_C_count` |
| 3 | Para cada ONT sem modelo / modelo lixo: marcar `valuation_grade=F` | `dry_run.grade_F_count` |
| 4 | Calcular **valor médio ponderado** da empresa: Σ `valor_nf × qty` / Σ qty (apenas ONTs grade A) | `dry_run.valor_medio_ponderado` |
| 5 | Aplicar `valor_medio_ponderado` aos grade B (purchase_id existe mas SN/modelo sujo) | `dry_run.grade_B_imputado` |
| 6 | Computar patrimônio total + range erro | `dry_run.patrimony_total`, `dry_run.patrimony_min`, `dry_run.patrimony_max` |
| 7 | NÃO escrever em banco. Imprimir relatório. | `dry_run.report.json` |

### Estrutura do relatório de saída
```json
{
  "scanned_at": "2026-02-16T12:00:00Z",
  "totals": {
    "ont_total": 1828,
    "grade_A": 460,
    "grade_B": 130,
    "grade_C": 465,
    "grade_D": 465,
    "grade_F": 308
  },
  "patrimony": {
    "auditable_min": 273675,
    "auditable_max": 351675,
    "with_speculation_min": 91400,
    "with_speculation_max": 731200,
    "weighted_avg_resolved": 273675,
    "confidence_pct": 35.7
  },
  "needs_human_review": {
    "model_garbage_count": 718,
    "no_purchase_id_count": 1175,
    "autosn_locked_count": 392
  },
  "would_write": 0,
  "dry_run": true
}
```

---

## §5. RANKING DOS 11 MODELOS "LIXO" (foco da limpeza R2)

| Rank | String observada | Qtd | Ação proposta |
|------|------------------|-----|----------------|
| 1 | `Desconhecido` | 3 | Manual review → Excel pra CEO classificar |
| 2 | `TestModel` | 4 | Soft-delete: provavelmente dados de QA |
| 3 | `None` (string literal) | 3 | Mesma ação que "Desconhecido" |
| 4 | `zte chinez` | 1 | Renomear → `ZTE` (gênero) → fallback ref R$ 75 |
| 5 | `Huawei HG` (truncado) | 1 | Manual: pedir foto do equipamento p/ confirmar |
| 6 | (sem campo `model`) | 3 | Marcar `valuation_grade=F`, esperar re-scan |

**Total a limpar:** 15 docs de 28 (54%). Em produção (1.828 ONTs com mesma proporção): **~987 docs** precisariam de revisão humana.

---

## §6. DELTA ENTRE PRODUÇÃO E PREVIEW

> ⚠ O preview tem 28 ONTs (`co-demo`). O CEO menciona 1.828 ONTs em produção. As proporções aqui são extrapolações **proporcionais ao preview**. Quando o CEO autorizar rodar a auditoria no banco de produção, os números reais podem divergir significativamente — especialmente:

| Métrica | Preview | Produção (extrapolada) | Erro provável |
|---------|---------|------------------------|----------------|
| % grade A (NF auditável) | 25% | ? | ±15pp |
| % grade F (fantasma) | 14% | ? | ±20pp |
| % modelo lixo | 39% | ? | ±25pp |
| Variedade de modelos | 8 | 20-50 | — |

**Recomendação:** rodar o **mesmo script `valuation_audit.py`** no banco de produção e comparar.

---

## §7. CONCLUSÃO OPERACIONAL

- **Matriz Grade A-F documentada.** Pronta para uso na Onda 1 (snapshot dump).
- **Tabela `MODEL_CANONICAL` em DRAFT.** CEO precisa validar / fornecer a lista oficial Ligo.
- **5 queries mongo prontas** para extrair os números reais de produção.
- **Checklist `valuation_backfill_dry_run` definido.** Garante zero escrita até CEO aprovar relatório.
- **15 docs de 28 (54%) precisariam de limpeza humana** mesmo após backfill automatizado.
