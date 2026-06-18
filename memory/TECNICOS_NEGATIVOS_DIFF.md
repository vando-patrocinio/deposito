# TÉCNICOS COM SALDO NEGATIVO — DRY-RUN DIFF (Onda C P0.2)

> Gerado em: **2026-06-18 15:27 UTC** · Modo: **DRY-RUN** (zero writes)
> Script: `/app/backend/scripts/recompute_tecnicos_dry_run.py`
> Origem: Auditoria Praça x Técnico (Onda C P1).

## Metodologia

```
  Entradas  = SUM(stok_transfer_audit.quantity_transferred)
  Saídas    = SUM(tickets.completion_data por técnico)
              em status terminais (finalizada/encerrada/resolvida_*)
  Calculado = Entradas - Saídas
  Diferença = Atual - Calculado
```

**Interpretação da diferença:**
- ✅ `diff = 0` → saldo bate com histórico rastreável.
- 🔴 `atual < 0 e diff < 0` → técnico consumiu além do rastreado (legado pré-Onda A; tickets antigos sem `completion_data` ou movimentações pré-audit).
- 🟡 `atual < 0 e diff ≥ 0` → negativo veio do histórico rastreado (consumo > transferências).
- 🟠 `diff > 0` → estoque fantasma (técnico tem mais do que histórico justifica).

---

## 👤 DIOGO HENRIQUE (`col-30aafc3c`)

- Empresa: `co-demo`
- Documento stok_stock: presente
- Tickets por status: `{'finalizada': 7, 'pendente': 94}`
- Stok_services por status: `{'orfa_sem_ticket': 15, 'cancelado': 17, 'erro_estoque': 15, 'fechado': 42}`

### Diff por consumível

| Consumível | Atual | Entradas | Saídas | Calculado | Δ Diferença | Classificação |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Cabo de rede | -10 | 0 | -13 | -13 | +3 | 🟡 negativo histórico (rastreável) |
| Conector fast | -2 | 0 | 0 | 0 | -2 | 🔴 déficit não-registrado (legado) |
| Conector de rede | -2 | 0 | 0 | 0 | -2 | 🔴 déficit não-registrado (legado) |
| Drop | 4 | +5 | -6 | -1 | +5 | 🟠 estoque fantasma (mais do que deveria) |
| Esticador | -1 | 0 | -2 | -2 | +1 | 🟡 negativo histórico (rastreável) |

---

## 👤 VANDO PATROCINIO (`col-b4db2145`)

- Empresa: `co-demo`
- Documento stok_stock: presente
- Tickets por status: `{'encerrada': 1, 'finalizada': 2, 'aberta': 1}`
- Stok_services por status: `{'cancelado': 2, 'orfa_sem_ticket': 13, 'fechado': 4}`

### Diff por consumível

| Consumível | Atual | Entradas | Saídas | Calculado | Δ Diferença | Classificação |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Cabo de rede | -10 | 0 | 0 | 0 | -10 | 🔴 déficit não-registrado (legado) |
| Conector fast | -4 | 0 | 0 | 0 | -4 | 🔴 déficit não-registrado (legado) |
| Conector de rede | -2 | 0 | 0 | 0 | -2 | 🔴 déficit não-registrado (legado) |
| Drop | 16 | +40 | -23 | 17 | -1 | 🟡 inconsistente |
| Esticador | -11 | 0 | -10 | -10 | -1 | 🔴 déficit não-registrado (legado) |

---

## 📋 Resumo executivo

| Categoria | Quantidade |
| --- | --- |
| ✅ Consistente (diff=0) | 0 |
| 🔴 Déficit não-registrado (legado pré-Onda A) | 6 |
| 🟡 Negativo rastreável (consumo > entradas) | 3 |
| 🟠 Estoque fantasma (atual > calculado) | 1 |

## 🩹 Recomendações de correção (sem executar)

Para cada linha 🔴 / 🟡 / 🟠:

1. **Não deletar** nenhum stok_services nem stok_stock. Sempre $set/$inc auditável.
2. **Negativos rastreáveis (🟡)** podem ser zerados via reposição admin com tag `recompute_p0_2_20260618` (similar à Onda A reposicao mode).
3. **Déficits legados (🔴)** exigem decisão CEO: aceitar como histórico (zerar com tag `legacy_orphan_consumption`) OU investigar caso-a-caso.
4. **Estoque fantasma (🟠)** exige investigação: pode indicar transferências sem audit ou entradas duplicadas.

> ⚠️ NADA será executado automaticamente. Este documento é apenas evidência para decisão.

