# ESTOQUE OPERACIONAL — FASE 2.5 — CAÇA AOS ESCRITORES DIRETOS

**Tipo:** Auditoria estática READ-ONLY do código-fonte.  
**Data:** 16/Fev/2026  
**Autor:** Auditor automatizado (CTO Mode) sob ordem do CEO.  
**Mandato:** Mapear 100% dos write paths sobre patrimônio (`stok_onts`); identificar caminhos que mudam estoque **fora** do contrato canônico (`inventory_movements.write_movement` / `enforce_os_inventory_movement`).  
**Sem código. Sem migração de dados. Sem alteração de doc no banco.**

---

## §1. SUMÁRIO EXECUTIVO

| Cor | Sites | Significado |
|-----|-------|-------------|
| 🟢 **VERDE** | **1** | Escrita autorizada — passa pelo helper canônico |
| 🟡 **AMARELO** | **12** | Operação legítima sem trilha canônica (criação/balanço/worker) |
| 🔴 **VERMELHO** | **25** | Bypass total do guardrail — risco patrimonial |
| **TOTAL** | **38** | Em 9 arquivos de produção |

> **Risco operacional consolidado:** o motor está pronto, mas existem **25 portas laterais** ainda abertas. Em pior caso, qualquer admin/gestor (e em alguns casos qualquer rota chamada por usuário não-CEO) consegue mover patrimônio sem deixar rastro auditável.

> **Linha do tempo arquitetural:** o helper canônico só foi criado em **16/Fev/2026** (Fase 2). Todo o código abaixo é **legado anterior** que não foi migrado. Não é regressão — é débito acumulado.

---

## §2. MATRIZ COMPLETA DE RISCO

> Convenção: 🔴 = bypass total. 🟡 = legítimo mas sem trilha canônica. 🟢 = passa pelo helper.

### `routes/stok.py` (180 KB · 19 sites de escrita)

| Linha | Op | Função | Natureza | Cor | Justificativa |
|-------|----|--------|---------|-----|---------------|
| 661 | `insert_many` | `create_onts_bulk` | Gênese (criação manual de lote) | 🟡 | Recebimento legítimo, mas sem `inventory_movements` |
| 696 | `update_one` | `edit_ont` | Edição admin (`model`) | 🟡 | Edição cosmética, baixo impacto, mas sem audit |
| 736 | `update_one` | `set_ont_sn` | **Reescreve `scan_sn` + flag** | 🔴 | Pode invalidar trilha D3=a sem audit |
| 779 | `update_one` | `migrate_fill_sn` | Migração admin de SN | 🔴 | Sem registro de quem mudou e por quê |
| 806 | `update_one` | `transfer_ont_to_tech` | **Empresa→Técnico admin** | 🔴 | Movimentação patrimonial direta |
| 928 | `update_many` | `transfer_onts_bulk` | **Bulk Empresa↔Técnico** | 🔴 | Pior caso: movimenta N ONTs sem trilha |
| 957 | `update_one` | `return_ont_to_company` | **Técnico→Empresa admin** | 🔴 | Movimentação patrimonial direta |
| 1117 | `update_one` | `reconcile_onts_with_olt` | Reconciliação manual SmartOLT | 🟡 | Equivalente ao worker — funcional |
| 1493 | `update_one` | `_move_ont_for_install` | **Helper de fluxo legado** | 🔴 | `auto_close_service_from_ticket` (gate-bypassed, mas existe) |
| 1583 | `update_one` | `_move_ont_for_install` | mesma função | 🔴 | mesma origem |
| 1656 | `insert_one` | `_move_ont_for_withdraw` | mesmo | 🔴 | mesma origem |
| 1682 | `update_one` | `_move_ont_for_withdraw` | mesmo | 🔴 | mesma origem |
| 1718 | `update_one` | `_move_ont_for_withdraw` | mesmo | 🔴 | mesma origem |
| 2862 | `update_one` | `manual_withdraw` | **Retirada manual sem OS** | 🔴 | Cria ONT no estoque "do nada" |
| 2884 | `insert_one` | `manual_withdraw` | mesmo | 🔴 | mesma origem |
| 3587 | `delete_many` | `stok_admin_reset` | **DELETA TODO O ESTOQUE** | 🔴 | Destrutivo total |
| 3714 | `delete_many` | `stok_admin_reset_granular` | Deleta por filtro | 🔴 | Destrutivo parcial |
| 3747 | `delete_many` | `stok_admin_reset_granular` | mesmo | 🔴 | mesma origem |
| 4204 | `update_one` | `decide_ai_review` | Aceita/rejeita scan IA | 🔴 | Pode aceitar SN auto-gerado sem audit |

### `routes/stok_transfers.py` (22 KB · 5 sites)

| Linha | Op | Função | Natureza | Cor | Justificativa |
|-------|----|--------|---------|-----|---------------|
| 209 | `update_one` | `confirm_defective_return` | **Defeito recebido** | 🔴 | Fluxo de defeito paralelo |
| 238 | `update_one` | `scrap_defective_ont` | **Descarte** | 🔴 | Descarta sem trilha — único momento patrimonial irreversível |
| 265 | `update_one` | `revert_defective_ont` | Reverte status defeito | 🔴 | Mexe sem auditoria |
| 412 | `update_one` | `approve_pending` | Pendência aprovada | 🔴 | Resolve transferência sem trilha |
| 446 | `update_one` | `reject_pending` | Pendência rejeitada | 🔴 | mesmo |

### `routes/lousa.py` (3 sites — fora do chokepoint)

| Linha | Op | Função | Natureza | Cor | Justificativa |
|-------|----|--------|---------|-----|---------------|
| 2980 | `update_one` | `_revert_ticket_side_effects` | **Reabertura: reverte estoque** | 🔴 | Reverte sem criar movimento reverso na trilha |
| 3036 | `update_one` | `_revert_ticket_side_effects` | mesmo | 🔴 | mesma origem |
| 4119 | `insert_one` | `public_finalize_ticket` | **Rota pública de finalização** | 🔴 | Caminho paralelo ao chokepoint — precisa investigação |

### `routes/purchases.py` (4 sites)

| Linha | Op | Função | Natureza | Cor | Justificativa |
|-------|----|--------|---------|-----|---------------|
| 901 | `insert_many` | `confirm_purchase` | Gênese (recebimento de compra) | 🟡 | Legítimo. Mas sem trilha canônica de origem |
| 1122 | `insert_many` | `reprocess_from_image` | OCR de nota fiscal | 🟡 | Legítimo. Pode duplicar — risco médio |
| 1249 | `insert_many` | `reprocess_purchase_sns` | mesmo | 🟡 | mesmo |
| 1381 | `delete_many` | `_revert_purchase_stock_impact` | **Reverte recebimento** | 🔴 | Apaga ONTs sem trilha auditável |

### `routes/ont_scan.py` (2 sites)

| Linha | Op | Função | Natureza | Cor | Justificativa |
|-------|----|--------|---------|-----|---------------|
| 247 | `update_one` | `scan_batch_commit` | Confirma batch OCR | 🟡 | Gênese/atualização via scan. Sem audit canônico |
| 269 | `insert_one` | `scan_batch_commit` | mesmo | 🟡 | mesmo |

### `routes/balanco.py` (2 sites)

| Linha | Op | Função | Natureza | Cor | Justificativa |
|-------|----|--------|---------|-----|---------------|
| 358 | `update_one` | `approve_balanco` | **Ajuste de inventário físico** | 🟡 | Cenário legítimo (ajuste por contagem) — único momento que pode atualizar sem OS |
| 369 | `update_one` | `approve_balanco` | mesmo | 🟡 | mesmo |

### `routes/field_ops.py` (2 sites)

| Linha | Op | Função | Natureza | Cor | Justificativa |
|-------|----|--------|---------|-----|---------------|
| 1091 | `update_one` | `field_equipment_return` | **Devolução de campo** | 🔴 | Caminho paralelo ao guardrail |
| 1110 | `insert_one` | `field_equipment_return` | mesmo | 🔴 | mesmo |

### `services/sn_photo_worker.py` (2 sites)

| Linha | Op | Função | Natureza | Cor | Justificativa |
|-------|----|--------|---------|-----|---------------|
| 208 | `update_one` | `_process_one` | **Worker: atualiza SN via foto** | 🟡 | Worker de IA sobe SN do auto-gerado para SN real. Operação legítima, mas precisa audit |
| 247 | `update_one` | `_process_one` | mesmo | 🟡 | mesmo |

### `services/os_inventory_guardrail.py` (1 site — autorizado)

| Linha | Op | Função | Natureza | Cor | Justificativa |
|-------|----|--------|---------|-----|---------------|
| 237 | `update_one` | `_move_equipment` | Mutação canônica | 🟢 | **Único site VERDE.** Chamado apenas por `enforce_os_inventory_movement` |

### `server.py` (não é write — só `create_index`)
Não conta. Operação de DDL, não DML.

---

## §3. CLASSIFICAÇÃO POR IMPACTO OPERACIONAL

### 🔴 Risco PATRIMONIAL CRÍTICO — destrutivo / movimento sem trilha

| Função | Quem aciona | Impacto se mal usado | Sites |
|--------|-------------|----------------------|-------|
| `stok_admin_reset` / `*_granular` | Admin/auditor | **Apaga estoque inteiro sem audit** | 3 |
| `manual_withdraw` | Admin/gestor | Cria ONT do nada, pode fraudar inventário | 2 |
| `transfer_ont_to_tech` / `transfer_onts_bulk` / `return_ont_to_company` | Admin/gestor | Movimentação direta sem assinatura | 3 |
| `scrap_defective_ont` | Admin | **Descarte sem trilha — patrimônio sumiu** | 1 |
| `confirm_defective_return` / `revert_defective_ont` | Admin | Mexe ciclo de defeito | 2 |
| `_revert_purchase_stock_impact` | Admin | Apaga recebimento sem audit | 1 |

**Subtotal: 12 sites · Aciona-se a partir de UI admin / gestor.**

### 🔴 Risco PATRIMONIAL ALTO — fluxo paralelo de OS

| Função | Quem aciona | Impacto | Sites |
|--------|-------------|---------|-------|
| `_move_ont_for_install` + `_move_ont_for_withdraw` (stok.py legacy) | `auto_close_service_from_ticket` (gate-bypassed) | Movimento por OS sem usar guardrail. Hoje gate=false, mas o código existe | 5 |
| `_revert_ticket_side_effects` (lousa.py) | Reabertura de ticket | Reverte estoque sem movimento reverso na trilha | 2 |
| `public_finalize_ticket` (lousa.py) | Rota pública | Pode ser caminho paralelo ao chokepoint corrigido na Fase 2 | 1 |
| `field_equipment_return` | Técnico via app | Devolução de campo sem audit | 2 |
| `approve_pending` / `reject_pending` (transfers) | Admin | Resolve transferência sem trilha | 2 |
| `decide_ai_review` (stok.py) | Admin revisor | Aceita SN auto-gerado sem trilha | 1 |

**Subtotal: 13 sites · Aciona-se via fluxo de OS ou pendência.**

### 🟡 Risco MÉDIO — operação legítima sem trilha canônica

| Função | Por quê é AMARELO | Sites |
|--------|-------------------|-------|
| `create_onts_bulk`, `confirm_purchase`, `reprocess_*` (purchases + stok) | Gênese do patrimônio (recebimento). Não é "movimento operacional" mas precisa registro de origem auditável | 4 |
| `scan_batch_commit` (ont_scan) | Entrada via OCR | 2 |
| `edit_ont` (stok) | Edição cosmética (model) — risco baixo | 1 |
| `reconcile_onts_with_olt` (stok) | Reconciliação manual com SmartOLT | 1 |
| `approve_balanco` (balanco) | Ajuste de inventário físico após contagem | 2 |
| `sn_photo_worker._process_one` | Atualização via foto de SN | 2 |

**Subtotal: 12 sites · Não são bypass intencional, mas precisam ser canalizados.**

### 🟢 AUTORIZADO

| Função | Site |
|--------|------|
| `_move_equipment` (guardrail) | 1 |

**Subtotal: 1 site.**

---

## §4. IMPACTO OPERACIONAL ESTIMADO

| Cenário hipotético | Probabilidade | Severidade | Risco |
|-------------------|---------------|------------|-------|
| Admin clica "Reset Estoque" no painel | Baixa | **CATASTRÓFICA** (perde 28 ONTs visíveis) | 🔴 ALTO |
| Gestor transfere bulk via `transfer_onts_bulk` sem motivo | Média | Alta (movimento sem assinatura) | 🔴 ALTO |
| Reabertura de ticket reverte estoque silenciosamente | Alta (toda reabertura) | Média (perde trilha do movimento original) | 🔴 ALTO |
| Worker `sn_photo_worker` aceita foto borrada e grava SN ruim | Média | Média (cria AUTOSN persistente sem flag) | 🟡 MÉDIO |
| Rota `public_finalize_ticket` é chamada por mobile legacy | Desconhecida | Alta (chokepoint pode estar bypassed) | 🔴 ALTO** |
| `field_equipment_return` chamado paralelo ao guardrail | Média (técnico via app) | Alta (devolução sem audit) | 🔴 ALTO |
| `scrap_defective_ont` apaga ONT com defeito | Baixa | **Irreversível** (patrimônio descartado sem registro) | 🔴 ALTO |
| `auto_close_service_from_ticket` reativado por engano | Baixa (hoje gate-bypassed) | Crítica (volta fluxo legado completo) | 🟡 MÉDIO |

**\*\*** Vermelho prioritário: `public_finalize_ticket` é a única rota cuja função efetiva precisa ser confirmada em runtime (pode ser dead-code ou pode ser usada pelo PWA técnico antigo).

---

## §5. RECOMENDAÇÃO DE FECHAMENTO (sem código nesta fase)

### Onda 1 — Bloqueio de destrutivos (1ª semana após aprovação)
1. `stok_admin_reset` + `stok_admin_reset_granular` → exigir motivo (≥20 chars) + role `super_admin` + gravação obrigatória em `inventory_movements` com `movement_type="disposal"` ou novo `"admin_reset"`.
2. `scrap_defective_ont` → mesma política.
3. `_revert_purchase_stock_impact` → mesma política.

### Onda 2 — Canalizar movimento direto via wrapper (2ª semana)
4. `transfer_ont_to_tech`, `transfer_onts_bulk`, `return_ont_to_company`, `manual_withdraw`, `confirm_defective_return`, `revert_defective_ont`, `approve_pending`, `reject_pending`, `field_equipment_return`, `_revert_ticket_side_effects` → cada um vira um pequeno chamador de `inventory_movements.write_movement()` com `movement_type` adequado (`manual_transfer_*`, `defect_returned_to_empresa`, etc., já no whitelist).

### Onda 3 — Investigar e decidir
5. `public_finalize_ticket` → mapear quem chama em runtime. Se PWA legado, sunset. Se órfã, deletar.
6. `_move_ont_for_install` / `_move_ont_for_withdraw` (stok.py legacy) → confirmar gate-bypass ativo + planejar remoção física do código.
7. `decide_ai_review` → exigir trilha mesmo na aceitação.

### Onda 4 — Trilha de gênese (Fase 3+)
8. `create_onts_bulk`, `confirm_purchase`, `reprocess_*`, `scan_batch_commit`, `edit_ont`, `reconcile_onts_with_olt`, `approve_balanco`, `sn_photo_worker._process_one` → criar `movement_type="genesis_purchase"`, `genesis_scan_ocr`, `balanco_adjustment`, `sn_photo_upgrade` no whitelist; gravar em `inventory_movements` mesmo sem ser movimento operacional clássico.

### Política definitiva
9. Lint/CI rule: **proibir `db.stok_onts.{insert,update,delete}` fora de `services/inventory_movements.py` ou `services/os_inventory_guardrail.py`**. Qualquer novo arquivo de produção que tente write direto falha em pre-commit.
10. Test de regressão estática: grep do regex no CI, falha se aparecer em arquivo não-whitelisted.

---

## §6. KPI DE PROGRESSO (zerar vermelhos)

| Métrica | Hoje | Meta após Onda 1 | Após Onda 2 | Após Onda 3 | Após Onda 4 |
|---------|------|-------------------|--------------|---------------|---------------|
| 🔴 sites | 25 | 19 | 6 | 3 | 0 |
| 🟡 sites | 12 | 12 | 12 | 12 | 0 |
| 🟢 sites | 1 | 7 | 20 | 23 | 38 |
| Cobertura canônica | 2,6% | 18,4% | 52,6% | 60,5% | **100%** |

---

## §7. CRITÉRIO DE ACEITE PARA INICIAR FASE 3

A Fase 3 (Responsabilidade Única) só faz sentido quando:

- 🔴 **= 0** sites bypass
- 🟡 ≤ 4 sites (apenas gênese de patrimônio, com trilha mínima)
- 🟢 ≥ 34 sites usando o helper

Antes disso, mudar schema é cosmético — o motor canônico continuaria sendo evitado por 25 portas laterais.

---

## §8. CONCLUSÃO

✅ **Mandato cumprido. Read-only. Zero código alterado. Zero migração de dados.**

- **38 sites de escrita inventariados** em 9 arquivos de produção.
- **25 RED** (bypass), **12 YELLOW** (legítimo s/ trilha), **1 GREEN** (autorizado).
- **Cobertura canônica atual: 2,6%.** O motor Fase 2 protege apenas o caminho do chokepoint de OS via `outcome=sucesso`.
- **Plano de fechamento em 4 ondas** prevê chegar a 100% de cobertura sem migrar nenhum dado histórico.
- **Maior risco isolado**: `stok_admin_reset` (deleção em massa sem trilha). Recomendação Onda 1.

**Próximo doc previsto** (se aprovado pelo CEO):  
- Onda 1 patch plan: `/app/memory/ESTOQUE_OPERACIONAL_ONDA1_PLAN.md` (lista de wrappers exigidos por função, sem código).

**Decisões necessárias do CEO:**
- A) Aprovar plano em 4 ondas e iniciar Onda 1.
- B) Reagrupar ondas (ex.: pular destrutivos primeiro).
- C) Adicionar/remover funções da matriz.
- D) Outra prioridade.
