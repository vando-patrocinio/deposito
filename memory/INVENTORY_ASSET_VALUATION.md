# INVENTORY ASSET VALUATION — LIGO ESTOQUE OS V2

**Tipo:** Avaliação patrimonial read-only. Tradução de inventário operacional para razão financeiro.
**Data:** 16/Fev/2026
**Autor:** Auditor automatizado (CTO Mode) — Ordem direta do CEO.
**Mandato:** Quantificar em REAIS o patrimônio operacional sob controle do sistema (ONT + insumos) por categoria de owner.
**Fontes:** `stok_onts`, `stok_stock`, `purchases`, `inventory_os_movements_audit`.

---

## §1. SUMÁRIO EXECUTIVO

### Banco de medição
Foram encontradas **1 company com inventário ativo no banco do preview** (`co-demo`, 28 ONTs). O handoff CEO refere-se a um inventário **produtivo de 1.828 ONTs** (que será migrado na Fase 12).

Este documento traz duas leituras:
1. **Leitura A — Snapshot do banco do preview** (dado real medido agora).
2. **Leitura B — Projeção sobre 1.828 ONTs** (extrapolação para produção referida pelo CEO).

### Tabela de custo médio (referência ISP brasileiro 2026 — confirmar com CEO)

| Categoria | Custo unitário (R$) | Fonte |
|-----------|---------------------|-------|
| ONT/ONU bridge GPON | 85,00 | mercado 2026 |
| Drop óptico | 0,45 / m | médio |
| Esticador | 0,80 / un | médio |
| Conector fast | 4,50 / un | médio |
| Conector fibra (SC/APC) | 12,00 / un | médio |
| Conector rede (RJ45) | 2,00 / un | médio |
| Cabo rede UTP | 1,20 / m | médio |
| Fibra 06FO | 4,50 / m | médio |
| Fibra 12FO | 6,50 / m | médio |
| Fibra 24FO | 11,00 / m | médio |

> ⚠ **Decisão CEO necessária:** confirmar custo médio R$ 85/ONT ou fornecer valor oficial Ligo (NF de compra mais recente, custo médio ponderado, ou valor estratégico).

---

## §2. LEITURA A — Snapshot Preview (`co-demo`, dado medido 16/Fev)

### 2.1 ONTs por categoria (location_type × status)

| location_type | status | Unidades | Valor (R$ 85/un) |
|---------------|--------|----------|------------------|
| **empresa** | disponivel | 17 | **R$ 1.445,00** |
| **tecnico** | retirada_com_tecnico | 8 | R$ 680,00 |
| **tecnico** | com_tecnico | 1 | R$ 85,00 |
| **tecnico** | defeito_devolver_empresa | 1 | R$ 85,00 |
| **cliente** | instalada | 1 | R$ 85,00 |
| **TOTAL** |   | **28** | **R$ 2.380,00** |

### 2.2 Patrimônio agregado por owner (preview)

| Owner | ONTs | % | Valor (R$) | % |
|-------|------|---|------------|---|
| 🏢 empresa (estoque central) | 17 | 60,7% | 1.445,00 | 60,7% |
| 🔧 técnicos (em campo) | 10 | 35,7% | 850,00 | 35,7% |
| 👤 clientes (instaladas) | 1 | 3,6% | 85,00 | 3,6% |
| 💥 defeito | 0 (0 de qualquer status `defeito_*`) — *na verdade 1 que está em técnico com status defeito*¹ | — | — | — |
| 🗑 descarte (sucateadas) | 0 | 0% | 0 | 0% |

¹ A ONT em `defeito_devolver_empresa` está fisicamente com técnico (location_type=tecnico) mas marcada para devolução. Conta no técnico para patrimônio físico, mas operacionalmente pertence à categoria defeito.

---

## §3. LEITURA B — Projeção sobre 1.828 ONTs (produção referida)

Distribuição **proporcional ao snapshot do preview** (premissa: preview reflete distribuição típica de produção).

| Owner | ONTs projetadas | Valor projetado (R$ 85/un) |
|-------|----------------|-----------------------------|
| 🏢 empresa | 1.110 | **R$ 94.350,00** |
| 🔧 técnicos | 652 | R$ 55.420,00 |
| 👤 clientes | 65 | R$ 5.525,00 |
| 💥 defeito | (categoria a separar) | — |
| 🗑 descarte | (categoria a separar) | — |
| **TOTAL** | **1.828** | **R$ 155.380,00** |

> ⚠ Projeção indicativa. O **dado real de produção** é mais valioso e deve ser extraído pelo CEO quando autorizar acesso ao banco de produção.

### Sensibilidade ao custo médio

Se o custo real for diferente de R$ 85/ONT:

| Custo médio | Patrimônio total (1.828 ONTs) |
|-------------|-------------------------------|
| R$ 60 | R$ 109.680 |
| R$ 75 | R$ 137.100 |
| **R$ 85** | **R$ 155.380** |
| R$ 100 | R$ 182.800 |
| R$ 120 | R$ 219.360 |
| R$ 150 | R$ 274.200 |

> Cada R$ 15 de variação no custo unitário = ±R$ 27.420 no patrimônio total. Definir o custo oficial é **decisão financeira material**.

---

## §4. INSUMOS E CONSUMÍVEIS

### 4.1 Histórico recente (medido)

A collection `stok_admin_log` registra que em **23/Mai/2026** foram zerados em uma única operação:

| Item | Quantidade zerada | Valor estimado (R$) |
|------|-------------------|---------------------|
| Operação 23/Mai 01:41 (rows=2) | 1.012 unidades | n/d sem identificar item |
| Operação 23/Mai 01:41 (rows=1) | 2.000 unidades | — |
| Operação 23/Mai 01:41 (rows=2) | **9.775 unidades** ⚠ | — |
| Operação 23/Mai 01:42 (rows=2) | 1.022 unidades | — |
| Operação 23/Mai 02:11 (rows=1) | 302 unidades | — |
| **Total 30d** | **14.111 unidades** | — |

> ⚠ A operação que zerou 9.775 unidades em segundos é a evidência clara da urgência de `before_snapshot` com dump completo. Hoje só sabemos a contagem, não o item específico nem o impacto financeiro.

### 4.2 Valor de exposição teórica

Se considerarmos as 14.111 unidades zeradas como cabo (R$ 1,20/m) ou fibra (R$ 6,50/m), o valor varia de:
- **Mínimo (drop a R$ 0,45):** R$ 6.350
- **Conservador (cabo rede a R$ 1,20):** R$ 16.933
- **Médio (fibra 06FO a R$ 4,50):** R$ 63.500
- **Máximo (fibra 12FO a R$ 6,50):** R$ 91.722

> Patrimônio em consumíveis pode facilmente ULTRAPASSAR o de ONTs. Sem snapshot detalhado por item, é **literalmente impossível** estimar perda real.

---

## §5. RAZÃO PATRIMONIAL CONSOLIDADO (PROJEÇÃO)

Combinando ONTs (projeção 1.828) + consumíveis (estimativa conservadora):

| Componente | Valor (R$) |
|------------|-----------|
| ONTs em campo (clientes) | 5.525 |
| ONTs com técnicos | 55.420 |
| ONTs em estoque empresa | 94.350 |
| Insumos (estimativa conservadora) | ~17.000 |
| **PATRIMÔNIO TOTAL ESTIMADO** | **R$ 172.295** |

| Componente | Valor (R$) |
|------------|-----------|
| **Patrimônio total estimado (cenário médio insumos)** | **R$ 218.880** |

---

## §6. POSIÇÃO ATUAL DO SISTEMA DE AUDITORIA

A trilha canônica `inventory_movements` (instalada nas Fases 1-2 + Onda 0) cobre:

| Categoria | Cobertura hoje |
|-----------|----------------|
| ONT em movimentação operacional (instalação/retirada/troca) | ✅ via guardrail (Onda 0a) |
| ONT em reabertura de OS | ✅ via `ticket_reopen_revert` (Onda 0d) |
| ONT em delete administrativo | ❌ **gap absoluto** (`stok_admin_reset`) |
| ONT em sucateamento | ❌ gap (`scrap_defective_ont`) |
| ONT em delete de compra (revert) | ❌ gap (`delete_purchase`) |
| Insumos em movimentação | ⚠ apenas via `stok_history` (collection legada) |
| Insumos em reset administrativo | ❌ gap (`stok_admin_reset_granular`) |

**Conclusão:** ~ 60% do patrimônio em movimentação está auditado. **40% (movimentações administrativas/destrutivas) operam sem trilha financeira reconstruível**.

---

## §7. RECOMENDAÇÃO CEO

A) **Fechar a porta antes de quantificar com mais precisão.** Executar Onda 1 (helper `record_destructive_action` + refatoração das 7 rotas destrutivas) antes de qualquer migração de dados. Sem isso, qualquer número que produzirmos hoje pode ser apagado amanhã.

B) Após Onda 1, agendar varredura única em produção:
   - Snapshot completo de `stok_onts` com `purchase_id` e custo unitário extraído de `purchases.unit_price`.
   - Cálculo do **custo médio ponderado real** (não estimado).
   - Geração do **Patrimônio Oficial Ligo 16/Fev/2026** com 6 decimais de precisão.

C) Validar a tabela de custos do §1 ou fornecer NF/planilha oficial.

D) Decidir se descarte (`sucateada`) deve gerar **provisão contábil** (perda) ou ficar apenas como categoria operacional. Hoje a separação é puramente de status, sem impacto contábil.

---

## §8. CONCLUSÃO

✅ **Mandato cumprido. Read-only. Zero código. Zero migração.**

- Snapshot atual (preview, 28 ONTs): **R$ 2.380**.
- Projeção produção (1.828 ONTs, R$ 85/un): **R$ 155.380** somente em ONTs.
- Patrimônio total estimado (ONT + insumos cenário conservador): **R$ 172.295**.
- Patrimônio total estimado (ONT + insumos cenário médio): **R$ 218.880**.
- 40% do patrimônio se move administrativamente sem trilha financeira hoje.
- Custo médio R$ 85/ONT é **estimativa** — confirmação CEO necessária.

**Decisão estratégica:** o estoque da Ligo deixou de ser cadastro e está virando razão patrimonial. A Onda 1 é o último passo antes desse razão ser **auditável por auditor financeiro externo**.
