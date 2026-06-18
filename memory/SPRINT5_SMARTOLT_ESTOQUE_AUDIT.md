# SPRINT 5 · SMARTOLT × ESTOQUE — AUDITORIA DE COBERTURA

**Empresa**: `co-demo` · **Gerado**: 2026-06-18 19:17 UTC
**Modo**: READ-ONLY · zero writes
**Relatório original**: `/app/memory/SMARTOLT_RECONCILIATION_2026-06-18.md`
**RCA já confirmada**: `/app/memory/RCA_DELTA_98_SMARTOLT_VS_ESTOQUE.md`

## 1. SNAPSHOT

- SmartOLT vivas (docs): **1.833**
- SmartOLT arquivadas: **213**
- Universo SmartOLT total: **2.046**
- stok_onts (docs): **32**
- Interseção (mac/sn): **12**
- SmartOLT sem estoque: **2.689**
- Estoque sem SmartOLT: **48**

## 2. COBERTURA PATRIMONIAL: **0.65%**

**Tier**: 🔴 CRÍTICO (Sprint 5 Fundacional)

## 3. ONTs por LOCATION (estoque)

| Location_type | Qtd |
|---------------|----:|
| empresa | 19 |
| tecnico | 12 |
| cliente | 1 |

## 4. ONTs por STATUS (estoque)

| Status | Qtd |
|--------|----:|
| disponivel | 19 |
| retirada_com_tecnico | 10 |
| com_tecnico | 1 |
| instalada | 1 |
| defeito_devolver_empresa | 1 |

## 5. GATE SPRINT 5

- ❌ Cobertura < 95%
- ✅ Diagnóstico fechado (Cenário A — nunca existiu integração)
- ⏳ Aguardando plano `SPRINT_5_FASE_0_PLAN.md` ser executado
