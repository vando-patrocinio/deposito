# SPRINT 5 · ONDA 5 — GENESIS AUDIT (READ-ONLY)

**Empresa**: `co-demo` · **Executado**: 2026-02-19 23:23 UTC
**Mandato**: ORDEM EXECUTIVA CEO 19/02/2026 · Fase 5.0 obrigatória
**Modo**: **READ-ONLY** · zero writes

## 1. UNIVERSO

| Fonte | Total |
|-------|------:|
| `smartolt_onus` | **1.833** |
| `stok_onts` (existentes) | 33 |

## 2. QUALIDADE DOS IDENTIFICADORES (smartolt_onus)

| Campo | Populados | % |
|-------|----------:|--:|
| `sn` | 1.832 | 99.95% |
| `unique_external_id` | 1.833 | 100% |
| `mac` | 870 | 47.46% |
| `pppoe_user` | **1** | **0.05%** ⚠️ |
| `subscriber_external_id` | **0** | **0%** ⚠️ |
| sem SN nem MAC (bloqueado) | 1 | 0.05% |

### Achado-crítico 1
SmartOLT NÃO foi populado com `pppoe_user` nem `subscriber_external_id`.
A sincronização externa não escreveu esses campos. Vínculo cliente
direto = **impossível** pelos canais convencionais.

## 3. DUPLICATAS

| Tipo | Quantidade |
|------|-----------:|
| SN duplicado | 1 |
| MAC duplicado | 0 |

## 4. CROSS-MATCH COM ESTOQUE EXISTENTE

| Métrica | Valor |
|---------|------:|
| SNs já em `stok_onts` (skip import) | 12 |
| MACs já em `stok_onts` | 0 |
| ONUs novas estimadas | **1.821** |

## 5. PROJEÇÃO DE CONFIANÇA (`data_confidence`)

| Confiança | Critério | Quantidade | % |
|----------:|----------|-----------:|--:|
| **1.00** | pppoe → SAP → subscriber (perfeito) | 0 | 0% |
| **0.90** | name fuzzy match com `subscribers.name` | **1.445** | **78.83%** |
| **0.70** | tem SN/MAC mas sem cliente identificado | 387 | 21.11% |
| **0.50** | sem dados (precisa revisão humana) | 1 | 0.05% |

### Achado-crítico 2 (POSITIVO)
A heurística de **fuzzy match no `name`** (tokens com 5+ chars como
nomes próprios) recuperou **1.445 vínculos** (78.83%). Sem ela, a
Genesis teria começado com **0% data_confidence ≥0.9**.

Exemplos de `name` no SmartOLT que casam com clientes:
- "B22B Ap202 Alexandre" → cliente "Alexandre ..."
- "GnCarvalho964_Adalberto" → cliente "Adalberto ..."
- "B13B_Ap401_Rogerio" → cliente "Rogerio ..."

## 6. STATUS OPERACIONAL DAS ONUs

| Status | Qtd | % |
|--------|----:|--:|
| Online | 1.559 | 85.05% |
| LOS | 155 | 8.46% |
| Power fail | 108 | 5.89% |
| Offline | 10 | 0.55% |
| (vazio) | 1 | 0.05% |

## 7. CANONICAL LINK ATUAL

ONUs já vinculadas em `network_access_canonical`: **0**
(reflexo do estado pré-Genesis — 263 portas materializadas, mas
nenhuma com mac/sn ainda)

## 8. AVALIAÇÃO POR GATE DA ONDA 6

| Gate Onda 6 | Meta | Projeção pós-Genesis |
|-------------|-----:|---------------------:|
| Cobertura ONUs | ≥95% | 1819/1833 = 99.24% ✅ |
| Cliente vinculado | ≥95% | **78.83%** ❌ |
| CTO vinculado | ≥95% | 0% (depende de Lousa/Onda 3) ❌ |
| Porta vinculada | ≥95% | 0% ❌ |
| Origem conhecida | ≥95% | 100% ✅ (origin=smartolt_genesis) |
| `data_confidence ≥0.9` | ≥90% | **78.83%** ❌ |

## 9. DECISÃO TÉCNICA (subject ao CEO)

A Genesis pode importar com sucesso **99.24%** das ONUs
(`import_success_pct`). MAS **3 gates da Onda 6 não serão atingidos
automaticamente** com os dados atuais:

1. Cliente vinculado = 78.83% (falta 16.17 p.p.)
2. CTO/Porta vinculados = 0% (depende dos técnicos finalizando OS
   via Lousa pós-Onda 3 — naturalmente forward-only)
3. data_confidence ≥0.9 = 78.83% (mesmo cenário do gate 1)

### Cenários para CEO

**Opção A — Genesis full + revisão posterior**
- Importar 1819 agora.
- Onda 6 fica bloqueada até revisão manual dos 387 órfãos (0.70).
- 387 ONUs vão pra fila "needs_human_review".

**Opção B — Forçar sync SmartOLT com pppoe**
- Pedir ao time de infra para popular `pppoe_user` no SmartOLT.
- Re-sincronizar e re-auditar.
- Gate 1 sobe para ~95%+ (estimativa baseada em SAP com 2872 pppoes).
- Genesis ocorre depois.

**Opção C — Genesis com inferência name expandida**
- Importar 1819 com fuzzy match atual.
- Worker pós-Genesis tenta vínculo adicional (cross com endereço,
  pppoe_user da SAP).
- 387 órfãos vão pra fila de revisão.
- Gate 1 sobe gradualmente.

## 10. RECOMENDAÇÃO

**Opção C** — combina pragmatismo (Genesis acontece, patrimônio
deixa de ser 32 e vira ~1832) com qualidade auditável
(`data_confidence` explícito em cada doc, revisão humana visível).

A Onda 6 (Auto Balanço) tem 2 fases:
- **6.1** — Balanço sobre os 1445 ONUs com confidence ≥0.9 (apto a publicar).
- **6.2** — Balanço completo após revisão dos 387 (semanas/meses, processo
  contínuo).

## 11. AGUARDANDO DECISÃO DO CEO

Antes da Fase 5.2 (write/Import), CEO precisa autorizar:
- (a) Aprova Opção C e libera POST /api/sprint5/onda5/import?confirm=true
- (b) Solicita Opção B (sync pppoe primeiro)
- (c) Outro caminho

---
**Audit emitido por** `GET /api/sprint5/onda5/audit`
em 2026-02-19 23:23 UTC.
