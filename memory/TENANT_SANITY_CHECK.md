# 🧹 TENANT_SANITY_CHECK — Inventário e Classificação de Tenants

> **Operação:** Mapa da Base — Fase P0.1
> **Data:** 2026-06-14 17:40 UTC
> **Autor:** CTO Mode / Auditoria Read-Only
> **Banco:** `test_database` (MongoDB local 27017)
> **Princípio:** Antes de mapear a base real, precisamos saber quem **NÃO** é base real.

---
## 🎯 OBJETIVO

Listar todo `company_id` (tenant) presente no banco, classificar como **REAL / DEMO / QA / SINTÉTICO / ÓRFÃO**, com evidência objetiva. Tudo o que **não for REAL/DEMO** deve ser **explicitamente excluído** de qualquer query de KPI, dashboard, relatório executivo, IA, NPS, churn, receita, ou seleção de cliente.

---

## 📊 EVIDÊNCIA — TENANTS EM `subscribers`

| company_id | docs em `subscribers` | Padrão de Nome (amostra) | Telefone | Documento |
|---|---:|---|---|---|
| `co-fantasma-v4` | **10.000** | "Cliente co-fantasma-v4 NNNNN" | mock distribuído | ausente |
| `co-colosso` | **10.000** | "Cliente NNNNNN" (zeros) | **NULL em 100%** | ausente |
| `co-demo` | **2.816** | Nomes reais (LUAN MIGUEL ALVES SIQUEIRA, etc.) | populado | **99,3% preenchido** |
| `co-fantasma-v3` | **2.000** | "Cliente co-fantasma-v3 NNNNN" | mock | ausente |
| `co-fantasma-test` | **2.000** | "Cliente Fantasma NNNN" | mock | ausente |
| `co-attribution-test` | **32** | "Cliente OK", "INC 0..11" | ausente | ausente |
| `co-id-auto` | **3** | "Pamela Souza", "João Silva", "Maria Silva" (fixtures) | duplicado | ausente |

**Total na collection `subscribers`:** 26.851
**Real (`co-demo`):** 2.816 = **10,49%**
**Sintético:** 24.035 = **89,51%**

---

## 📋 EVIDÊNCIA EXPANDIDA — TENANTS EM OUTRAS COLLECTIONS

Scanning de **todas as 380+ collections** do banco identificou **80+ tenants distintos** circulando — quase todos sintéticos ou de QA/CI:

### Tenants com volume significativo (≥1k documentos cross-collections):
- `co-demo` — **1.247.559 docs** (REAL — único tenant produtivo)
- `co-fantasma-v4` — 84.916 docs (SINTÉTICO load test v4)
- `co-colosso` — 43.671 docs (SINTÉTICO carga 10k)
- `co-fantasma-v3` — 23.678 docs (SINTÉTICO load test v3)
- `co-fantasma-test` — 13.512 docs (SINTÉTICO seed)
- `co-homolog-v8` — 1.093 docs (HOMOLOGAÇÃO/STAGING — não-prod)
- `_orphan` — 924 docs (ÓRFÃOS sem company_id válido)

### Tenants de baixíssimo volume (CI/QA fixtures — todos a excluir):
`co-attribution-test`, `co-id-auto`, `co-pilot-1`, `demo-cto-audit`, `co-test-p1`, `test-adj-b6d1fa`, `tst-d8`, `co-mem-test`, `benchmark`, `test-v62`, `co-tesoureira-test`, `test-pred-6c5a87`, `tst-audit-co`, `co-test-a0bae9`, **`co-prod`** (4 docs — confuso, parece fixture), `test-e2e-*` (vários), `test-dq-a-*` / `test-dq-b-*` (8 variantes), `perf-bench`, `pilot-sim-72h`, `co-schema-test`, e ~50 tenants gerados automaticamente com hash hexadecimal (`co-4aa339b147`, `co-5f6a32c956`, `co-cba5ce9f40`, `co-fa0c9828a2`, etc.), além de hashes brutos (`69fe80ceb00ef65b4dcdc080`).

### Tenants com nomes claramente diagnósticos:
- `co-nonexistent-xyz` (teste de fallback)
- `*` (wildcard de teste)
- `co-451e80881f`, `co-4aa339b147`, etc. (gerados via UUID truncado em rotina de provisioning)

---

## 🏷️ CLASSIFICAÇÃO OFICIAL

| Categoria | Tenants | Decisão |
|---|---|---|
| **REAL PROD** | `co-demo` | ✅ ÚNICA fonte de verdade |
| **HOMOLOG/STAGING** | `co-homolog-v8` | ⚠️ Excluir de KPIs prod |
| **SINTÉTICO LOAD** | `co-colosso`, `co-fantasma-v4`, `co-fantasma-v3`, `co-fantasma-test` | ❌ EXCLUIR sempre |
| **QA/CI FIXTURES** | `co-attribution-test`, `co-id-auto`, `co-pilot-1`, `co-mem-test`, `co-tesoureira-test`, `co-schema-test`, `co-test-*`, `demo-cto-audit`, `tst-*`, `test-*`, `pilot-sim-72h`, `perf-bench`, `benchmark` | ❌ EXCLUIR sempre |
| **AUTO-GENERATED HASH** | `co-XXXXXXX` (32 variantes), `69fe80...`, `6a2864...` | ❌ EXCLUIR sempre |
| **ÓRFÃOS** | `_orphan`, `*` | ❌ EXCLUIR + investigar origem |

---

## ⚠️ ALERTAS CRÍTICOS

1. **`co-demo` NÃO é "demo"** — apesar do nome, é o tenant produtivo único da Ligo. Hoje contém 2.746 clientes ativos reais (base verdadeira) + 24k registros históricos importados do sistema externo Atlaz/Hubsoft (`loyalty_imported_db`).
2. **`co-colosso` tem 10.000 docs sem telefone, sem email, sem documento** — claramente carga sintética. Nome insinua "teste de colossal escala".
3. **`co-fantasma-*` é literalmente nomeado "fantasma"** — pasta de carga sintética. Não há ambiguidade.
4. **Coleções massivas contaminadas** (top com mistura):
   - `tickets` (4.157) → 84% sintético
   - `motor_ia_events` (423.381) → 89%+ sintético
   - `isabella_queue_metrics` (199.311) → 89%+ sintético
   - `subscriber_invoices` (10.346) → mistura
   - `whatsapp_system_events` (10.607) → mistura
5. **Nenhum dashboard, KPI, score IA, NPS, alerta, churn, ranking, receita, ou ranqueamento produzido até hoje exclui esses tenants nominalmente.** Toda métrica gerencial precisa ser refeita com filtro.

---

## ✅ FILTRO MONGO RECOMENDADO (REGRA DE OURO)

```javascript
// Aplicar em TODA agregação de métrica produtiva, dashboard, IA, NPS, receita:
{ "company_id": "co-demo" }
```

**Lista negra explícita ($nin):**
```python
SYNTHETIC_TENANTS = [
    "co-colosso", "co-fantasma-v4", "co-fantasma-v3", "co-fantasma-test",
    "co-attribution-test", "co-id-auto", "co-pilot-1", "co-mem-test",
    "co-tesoureira-test", "co-schema-test", "co-homolog-v8", "co-nonexistent-xyz",
    "demo-cto-audit", "benchmark", "perf-bench", "pilot-sim-72h",
    "_orphan", "*",
    # + qualquer tenant que comece com: test-, tst-, co-test-, test-dq-, test-e2e-
    # + qualquer tenant que seja UUID hex (regex ^[0-9a-f]{10,}$ ou ^co-[0-9a-f]{8,}$)
]
```

---

## 🔬 CONFIANÇA DOS DADOS

| Dimensão | Confiança | Justificativa |
|---|---|---|
| Lista de tenants sintéticos vs. real | 🟢 **ALTA** | Nomes auto-incriminatórios (`fantasma`, `colosso`, `test`), padrões claros de nome/telefone/documento, volumes em múltiplos de 1.000/2.000/10.000 (típicos de seed scripts). |
| Definição de `co-demo` como único REAL | 🟢 **ALTA** | 99% dos registros têm nome real, documento (CPF/CNPJ) com estrutura válida, telefones brasileiros únicos, e cruza com `atlaz_clients_cache` (96% interseção). |
| Definição de `co-homolog-v8` como staging | 🟡 **MÉDIA** | Inferência pelo nome ("homolog") e baixo volume — confirmar com infra antes de excluir cegamente. |
| Tenants hash (`co-XXXXXXXX`) | 🟢 **ALTA** | Padrão UUID truncado em rotinas de provisioning automático — todos com 1-2 docs. |
| Cobertura total dos tenants no banco | 🟡 **MÉDIA** | Scaneados 380+ collections mas pode haver tenants em campos não-padrão (`tenant`, `org`, `clientId`). Recomenda-se segundo passe se necessário. |

---

## 🎯 AÇÃO RECOMENDADA (NÃO EXECUTAR — REQUER AUTORIZAÇÃO)

1. **P0** — Aplicar `SYNTHETIC_TENANTS $nin` em **todos** endpoints de métrica gerencial (Dashboard, KPI, Presidente IA, Isabella stats, Alvaro reports).
2. **P0** — Auditar `co-homolog-v8` com infra para decidir purga ou retenção como espelho.
3. **P1** — Investigar origem dos `_orphan` (924 docs) e tenants hash auto-gerados — provavelmente bug em rotina de criação anônima.
4. **P1** — Adicionar `TENANT_ALLOWLIST = ["co-demo"]` em variável de ambiente, ler na inicialização do backend, e logar warning quando query escrever em outro tenant em prod.
5. **P2** — Backfill: criar índice `{company_id: 1}` em todas as collections que não têm (acelerará o filtro $in).

---

## 🚫 O QUE NÃO FAZER

- **NÃO deletar** documentos sintéticos sem decisão CTO (servem como base de teste de IA).
- **NÃO renomear** `co-demo` para `co-ligo` neste momento — quebraria milhões de referências.
- **NÃO confiar** em nenhum dashboard, NPS, churn, receita, score IA, ou ranking gerado antes desta data **sem reaplicar o filtro**.
