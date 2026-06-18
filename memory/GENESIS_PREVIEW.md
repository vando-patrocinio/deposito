# SPRINT 5 · ONDA 5 — GENESIS PREVIEW (Fase 5.1)

**Empresa**: `co-demo` · **Gerado**: 2026-02-19 23:23 UTC
**Modo**: SIMULATION · zero writes

## RESUMO

| Métrica | Valor |
|---------|------:|
| Universo SmartOLT | 1.833 |
| **Seriam importadas** | **1.819** |
| Bloqueadas (sem SN nem MAC) | 1 |
| Bloqueadas (SN duplicado) | 1 |
| Skipped (já em stok_onts) | 12 |
| **Success rate** | **99.24%** |
| Meta CEO ≥95% | ✅ **ATINGIDO** |

## DISTRIBUIÇÃO PROJETADA POR `data_confidence`

| Confidence | Quantidade | % do total importado |
|-----------:|-----------:|---------------------:|
| 1.00 (pppoe→SAP→sub) | 0 | 0% |
| 0.90 (name fuzzy match) | 1.445 | 78.83% |
| 0.70 (sem cliente) | 387 | 21.11% |
| 0.50 (sem dados) | 1 | 0.05% |
| **Total ≥0.9** | **1.445** | **78.83%** |

## GATE CHECK (preview)

- ✅ Import Success ≥95% → 99.24%
- ❌ Data confidence ≥0.9 ≥ 90% → 78.83%

## DECISÃO REQUERIDA

Genesis está APTA tecnicamente. Gate `data_confidence ≥0.9 ≥90%` ficará
em 78.83% — ABAIXO da meta CEO para iniciar Onda 6.

Ver `/app/memory/GENESIS_AUDIT.md` seção 9 para opções A/B/C.

**Aguardando autorização CEO para Fase 5.2 (Import).**
