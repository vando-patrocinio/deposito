# FIBRA 12FO RCA — Forensic Analysis
**Anomalia**: `stok_stock.empresa.fibra_12fo = -366.356` (≈366 km negativos)
**Anomalia secundária**: `stok_stock.empresa.fibra_48fo = -200`
**Investigador**: CTO (Onda C P0.1) · **Data**: 18/06/2026 · **Modo**: READ-ONLY

---

## ✅ Veredito final

**Não é bug do sistema. É contaminação de dados de teste em produção.**

O fluxo de débito de fibra ao criar cabos de rede funcionou EXATAMENTE como projetado. O que aconteceu é que **4 cabos com `cable_serial` e `invoice_number` claramente de teste** foram criados pelo usuário `Administrador` em 02/06/2026 entre 14:01 e 14:23 (≈22 minutos de sessão de teste), e o sistema corretamente debitou a fibra do estoque empresa.

Total de fibra "consumida" por cabos de teste:
- **12FO**: 364.356 + 1.500 + 500 = **366.356 metros** ← bate exatamente com o saldo negativo atual.
- **48FO**: **200 metros** ← bate exatamente com o saldo negativo atual.

---

## 🕒 Linha do tempo completa (Fibra 12FO)

| # | Data/Hora UTC | Tipo | Operação | Saldo após | User | Evidência |
|---|--------------|------|----------|-----------:|------|-----------|
| 1 | 2026-05-23 01:41:46 | `admin_reset_granular` | Auditor **zerou** Fibra 12FO (eram 9.775 unid em 2 rows) | **0** | Administrador | `stok_history` |
| 2 | 2026-06-02 14:01:14 | `rede_lancamento` | Baixa automática **−9.113m** (cabo `cab-8e7340dad3`) | -9.113 | Administrador | `stok_history` |
| 3 | 2026-06-02 14:01:52 | `rede_lancamento` | Devolução automática **+9.113m** (mesmo cabo) | **0** | Administrador | `stok_history` (cabo desfeito) |
| 4 | **2026-06-02 14:16:14** | `rede_lancamento` | **Baixa automática −364.356m** (cabo `cab-4f21e3e0f7`) | **-364.356** | **Administrador** | 🚨 ESTOPIM |
| 5 | 2026-06-02 14:16:39 | `rede_lancamento` | Baixa automática **−1.500m** (cabo `cab-a530c12c0e`) | -365.856 | Administrador | — |
| 6 | 2026-06-02 14:23:38 | `rede_lancamento` | Baixa automática **−500m** (cabo `cab-3f16ef51fa`) | **-366.356** | Administrador | saldo atual |

**Soma matemática**: −364.356 − 1.500 − 500 = **−366.356** ✅ confere com `stok_stock`.

---

## 🚨 Cabos contaminados (4)

| ID do cabo | Tipo | length_m | cable_serial | invoice_number | Status | Diagnóstico |
|-----------|------|---------:|--------------|----------------|--------|-------------|
| `cab-4f21e3e0f7` | 12fo | **364.356** | **ABCD-TEST-001** | **12345** | `cabo_solto` | TESTE (5778 segmentos OSRM gigante) |
| `cab-a530c12c0e` | 12fo | 1.500 | **FB-TEST-001** | **NF-9999** | `cabo_solto` | TESTE (serial óbvio) |
| `cab-3f16ef51fa` | 12fo | 500 | **TST-DEBIT-12fo** | **NF-DEBIT** | `cabo_solto` | TESTE (literal: serial diz "DEBIT") |
| `cab-afacf584d9` | **48fo** | 200 | **TST-DEBIT-48fo** | **NF-DEBIT** | `cabo_solto` | TESTE (mesmo padrão para 48FO) |

**Critério de identificação de teste**:
- `cable_serial` contém: `TEST`, `TST`, `ABCD`, `FB-TEST` (4/4 batem)
- `invoice_number` contém: `TEST` ou está em {`12345`, `NF-9999`, `NF-DEBIT`} (4/4 batem)
- `purchase_id`: NoneType (4/4)
- Todos criados no **mesmo dia (02/06)**, mesmo usuário (`Administrador`), janela de 22 minutos.

Cabos reais (não-teste) na coleção (controle): apenas 2, do tipo `drop` (`cab-19dfdab1cd`=1.511,8m, `cab-f12bee435d`=89,9m), sem serial, sem invoice — consistentes com operação real de drop.

---

## 🧪 Respostas às perguntas do CEO

| Pergunta | Resposta |
|----------|----------|
| Quando surgiu o saldo negativo? | **02/06/2026 às 14:16:14 UTC** (operação #4 da timeline). |
| Qual operação gerou? | Criação do cabo `cab-4f21e3e0f7` via `POST /api/rede/cabos` (rede_lancamento). |
| Qual usuário/processo? | **Administrador** (user=`Administrador` em todos os 4 lançamentos). |
| Unidade utilizada? | **metros** (consistente em todas as operações — `length_m` em float). Confirmado por haversine sobre `segments`: 364.355,7m bate com 364.356m. |
| Bug de conversão? | **Não.** Sistema fez a conversão correta lat/lng→metros via 5778 segmentos OSRM. Comprimento foi calculado corretamente. |
| Lançamento duplicado? | **Não.** Cada cabo aparece 1x. Houve uma devolução automática em 14:01:52 (cabo `cab-8e7340dad3` voltou ao saldo). |
| Consumo sem entrada? | **Sim**, mas por design: o admin reset zerou em 23/05 e nenhuma compra subsequente foi lançada antes dos testes. O Admin testou a baixa sem ter "entrada" para sustentá-la. |
| Migração antiga? | **Não.** Todos os 4 lançamentos são de 02/06/2026 — pós-Sprint 1. Sistema não tem migração legada para fibra. |

---

## 🎯 Por que isso aconteceu

1. **23/05**: Auditor zerou o estoque de fibra para preparar um teste limpo.
2. **02/06**: Admin abriu o módulo de Rede e desenhou 4 cabos de teste no mapa (1 grandioso de 364km + 3 menores), provavelmente para validar:
   - Cálculo de comprimento OSRM (cab-4f21e3e0f7 com 5778 pontos).
   - Débito automático (`stok_debit` no documento).
   - Suporte a 12FO e 48FO.
3. O sistema **executou corretamente** o débito conforme designed.
4. Os cabos **nunca foram apagados nem marcados como teste**, e o estoque negativo persistiu.
5. Onda A (Reposição mode) **não** trata esse caso — ela corrige distribuição/uso por OS, não cabos de rede.

---

## 🩹 Plano de correção (proposto · NÃO executado)

> Regra de ouro: zero deletes. Toda correção via lançamento auditável de estorno.

### Opção A — Anular cabos de teste (recomendada)
1. Marcar cada um dos 4 cabos com:
   ```json
   { "status": "anulado_admin_test_rca_20260618",
     "anulado_at": "2026-06-18T...",
     "anulado_by": "rca_20260618",
     "anulado_reason": "Cabo de teste contaminando produção — RCA Fibra 12FO" }
   ```
2. Criar 4 documentos em `stok_history` com `type=rede_estorno`, `tag=rca_fibra_20260618` e valores positivos +364.356, +1.500, +500, +200.
3. Incrementar `stok_stock.empresa.fibra_12fo += 366.356` e `fibra_48fo += 200` numa única operação atômica.
4. Resultado esperado: `fibra_12fo = 0`, `fibra_48fo = 0` (consistente com o "auditor zerou em 23/05").
5. Tudo registrado em `stok_admin_log` com `action=fibra_rca_estorno` e referência à este documento.

### Opção B — Apenas zerar o saldo
- Mais simples, mas perde rastreabilidade da existência dos cabos de teste. **Não recomendado**.

### Opção C — Forward fix (não tocar histórico)
- Lançar uma compra de 366.356m de fibra como "ajuste contábil de teste admin". **Pior opção** — vira mentira contábil.

---

## ⚠️ Recomendação operacional

1. **Aprovar Opção A** com ata assinada pelo CEO (correção patrimonial documentada).
2. **Adicionar guardrail no módulo de Rede**:
   - Validação: `cable_serial` não pode conter `TEST/TST/ABCD` em produção.
   - Validação: `length_m > 50km` exige confirmação explícita (modal "Tem certeza?").
   - Validação: `purchase_id` obrigatório para cabos com débito real.
3. **Documentar**: criar `/app/memory/CABOS_REDE_LANCAMENTO_REGRAS.md` para impedir recorrência.

---

## 📎 Evidências (paths no DB)

- Collection: `network_cables` (4 docs contaminados listados acima)
- Collection: `stok_history` (6 lançamentos da timeline)
- Collection: `stok_stock` (1 doc com `location=empresa` e saldos negativos)
- Script de validação: `python3 /app/backend/scripts/audit_praca_tecnico.py` (read-only)

---

## ✅ Critério de saída P0.1 atendido

- [x] Quando surgiu: **02/06/2026 14:16:14 UTC**
- [x] Qual operação: **`POST /api/rede/cabos` (rede_lancamento)**
- [x] Qual usuário: **Administrador**
- [x] Unidade: **metros** (correta)
- [x] Bug de conversão: **não**
- [x] Lançamento duplicado: **não**
- [x] Consumo sem entrada: **sim, por teste do admin**
- [x] Migração antiga: **não, dados de 02/06/2026**

**Próximo passo**: aprovação CEO para executar Opção A (estorno auditável).
