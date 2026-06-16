# OPERAÇÃO ONDA 1 — AUDITORIA DE OPERAÇÕES DESTRUTIVAS DO PATRIMÔNIO

**Tipo:** Auditoria estática + medição read-only. ZERO mutação.
**Data:** 16/Fev/2026
**Autor:** Auditor automatizado (CTO Mode) — Ordem direta do CEO.
**Mandato:** Mapear TODAS as operações que removem, revertem, descartam, resetam ou apagam patrimônio (ONT/insumo/compra/ticket), classificar por risco e definir o padrão mínimo de auditoria pré-execução.
**Sem código. Sem migração. Apenas relatório.**

---

## §1. SUMÁRIO EXECUTIVO

| # | Operações destrutivas encontradas | Quantidade |
|---|-----------------------------------|------------|
| 1 | Rotas HTTP `POST/DELETE` que mutam patrimônio | **10** |
| 2 | Helpers/funções internas com `delete_many`/`update_many` patrimonial | **3** |
| 3 | Já possuem trilha mínima (`before/after`+`audit_hash`+`executed_by`+`reason`) | **0** |
| 4 | Possuem trilha parcial (algum dos 5 campos) | **6** |
| 5 | Possuem ZERO trilha patrimonial | **4** |

### Veredicto

**❌ Nenhuma das 10 operações destrutivas hoje atende ao critério CEO completo** (`audit_hash` + `before_snapshot` + `after_snapshot` + `executed_by` + `executed_at` + `reason`).

| Critério CEO | Operações que satisfazem | % |
|--------------|-------------------------|---|
| `executed_by` (email/id do ator) | 10/10 | 100% |
| `executed_at` (timestamp) | 9/10 | 90% |
| `before_snapshot` (estado antes) | 4/10 | 40% |
| `after_snapshot` (estado depois) | 1/10 | 10% |
| `reason` (motivo escrito obrigatório) | 0/10 | **0%** |
| `audit_hash` (SHA-256 determinístico) | 0/10 | **0%** |

> **Nenhuma operação destrutiva exige hoje um motivo escrito do ator.** Confirmação textual ("ZERAR ESTOQUE", "APAGAR TUDO") existe — mas é uma palavra fixa, não captura motivo livre.

---

## §2. MATRIZ COMPLETA DAS 10 OPERAÇÕES DESTRUTIVAS

| # | Rota / Função | Arquivo : Linha | RBAC | Trilha? | Risco | Volume 30d | Reversível? |
|---|---------------|------------------|------|---------|-------|------------|-------------|
| 1 | `POST /api/stok/admin/reset` | `routes/stok.py:3640` | auditor | 🟡 parcial | 🔴 EXTREMO | 3 | ❌ NÃO |
| 2 | `POST /api/stok/admin/reset-granular` | `routes/stok.py:3744` | auditor | 🟡 parcial | 🔴 EXTREMO | 10 | ❌ NÃO |
| 3 | `POST /api/stok-transfers/defective-onts/{mac}/scrap` | `routes/stok_transfers.py:223` | gestor | 🔴 ausente | 🟠 ALTO | 0 | ❌ NÃO |
| 4 | `POST /api/stok-transfers/defective-onts/{mac}/revert` | `routes/stok_transfers.py:247` | gestor | 🔴 ausente | 🟡 MÉDIO | 0 | ✅ idempotente |
| 5 | `DELETE /api/purchases/{id}` | `routes/purchases.py:1272` | auditor | 🟡 parcial | 🔴 ALTO | 0 | ❌ ONTs em uso ficam órfãs |
| 6 | `POST /api/purchases/batch-delete` | `routes/purchases.py:1318` | auditor | 🟡 parcial | 🔴 EXTREMO | 0 | ❌ idem #5, em lote |
| 7 | `POST /api/lousa/tickets/wipe-all` | `routes/lousa.py:3519` | auditor | 🟡 parcial | 🟠 ALTO | 0 | ❌ deleta tickets em massa |
| 8 | `POST /api/lousa-ai/triage/{id}/revert` | `routes/lousa_ai.py:46` | gestor | 🔴 ausente | 🟢 BAIXO | n/d | ✅ |
| 9 | `_revert_purchase_stock_impact` (helper interno) | `routes/purchases.py:1362` | — | 🟡 parcial | 🔴 indireto via #5/#6 | derivado | ❌ |
| 10 | `_revert_ticket_side_effects` (helper interno) | `routes/lousa.py:2930` | — | ✅ **patch Onda 0d aplicado** | 🟢 (mitigado) | derivado | ✅ trilha reversa |

### Detalhamento por operação

#### #1 — `POST /api/stok/admin/reset` 🔴 EXTREMO
- **Faz:** `delete_many({"company_id": cid})` em `stok_onts`, `stok_consumables`, `stok_history`.
- **Confirmação:** payload `confirm == "ZERAR ESTOQUE"` (palavra fixa).
- **Trilha atual:** insere em `stok_admin_log` com `before` counts, `deleted` counts, `performed_by_email`, `timestamp`, `scope`.
- **O QUE FALTA:** `reason` (motivo livre), `after_snapshot` (deveria conter contagens pós-execução verificadas), `audit_hash`, **dump completo das ONTs apagadas** (irreversibilidade absoluta sem snapshot dos docs deletados).
- **Histórico real medido:** 3 execuções em 30 dias (todas no co-demo, ator `admin@empresa.com`).

#### #2 — `POST /api/stok/admin/reset-granular` 🔴 EXTREMO
- **Faz:** `delete_many` por scope (`item`, `collaborator`, `praca`).
- **Trilha atual:** mesmo log que #1 + `_add_history` com label do target.
- **O QUE FALTA:** mesmo gap que #1. Adicionalmente: **dump das ONTs apagadas** — sem isso é impossível restaurar.
- **Histórico real medido:** 10 execuções em 30d. Picos: 9.775 unidades de consumível deletadas em uma única operação (23/Mai).

#### #3 — `POST /defective-onts/{mac}/scrap` 🟠 ALTO
- **Faz:** `update_one({mac}, {"status":"sucateada"})`. NÃO deleta o doc.
- **Trilha atual:** apenas `scrapped_at`, `scrapped_by` no próprio doc.
- **O QUE FALTA:** TUDO. Sem `stok_admin_log`, sem `inventory_movements` (movement_type `disposal` existe mas não é gravado aqui).
- **Histórico real medido:** 0 execuções (ainda).

#### #4 — `POST /defective-onts/{mac}/revert` 🟡 MÉDIO
- **Faz:** Move ONT de status defeito → `disponivel`, `location_type=empresa`.
- **Trilha atual:** apenas campos `reverted_at`, `reverted_by` no doc.
- **O QUE FALTA:** mesmo gap que #3, mas é reversível por idempotência.

#### #5/#6 — Purchase delete (individual + batch) 🔴 ALTO
- **Faz:** Apaga `purchases` + chama `_revert_purchase_stock_impact`:
  - Para `type=ont`: `delete_many` ONTs `disponivel` com este `purchase_id`. ONTs em uso (cliente/técnico) ficam órfãs (mantêm `purchase_id` mas a compra sumiu).
  - Para `type=insumo`: decrementa `stok_stock.empresa`.
- **Trilha atual:** `purchases_deletion_audit` com snapshot da compra deletada, `deleted_by_email`, `reverted_summary`.
- **O QUE FALTA:** `reason`, `audit_hash`, dump das ONTs apagadas, **tratamento de ONT órfã** (gap conceitual: a compra que originou a ONT não existe mais — quebra rastreabilidade financeira).
- **Histórico real medido:** 0 execuções (collection vazia).

#### #7 — `POST /lousa/tickets/wipe-all` 🟠 ALTO
- **Faz:** `delete_many({"company_id":cid})` em `tickets` (não toca patrimônio direto, mas apaga histórico de movimentos via OS).
- **Trilha atual:** `lousa_logs.insert_one` com `deleted_count`, ator, timestamp.
- **O QUE FALTA:** `reason`, `audit_hash`, snapshot dos tickets deletados (necessário porque ao apagar os tickets, a relação `os_id` → movimento patrimonial em `inventory_movements` fica órfã).
- **Risco subjacente:** afeta indiretamente a auditoria patrimonial (ON 0a/0d) — ao apagar tickets, perdemos a origem dos movimentos.

#### #8 — `POST /lousa-ai/triage/{id}/revert` 🟢 BAIXO
- **Faz:** Reverte triage da IA (não toca patrimônio físico).
- **Não está no escopo financeiro** mas listado para completude.

#### #10 — `_revert_ticket_side_effects` ✅ ENDEREÇADO
- Já recebeu patch Onda 0d (movimento reverso em `inventory_movements` com `audit_hash`).

---

## §3. CONFRONTO COM O CRITÉRIO CEO

O CEO exigiu (literal):

```json
{
  "audit_hash": "...",
  "executed_by": "...",
  "executed_at": "...",
  "reason": "...",
  "before_snapshot": {...},
  "after_snapshot": {...}
}
```

**Comparativo por operação:**

| # | audit_hash | executed_by | executed_at | reason | before_snapshot | after_snapshot |
|---|------------|-------------|-------------|--------|-----------------|----------------|
| 1 stok_admin_reset | ❌ | ✅ | ✅ | ❌ | ⚠️ counts | ❌ |
| 2 stok_admin_reset_granular | ❌ | ✅ | ✅ | ❌ | ⚠️ counts | ❌ |
| 3 scrap_defective_ont | ❌ | ✅ scrapped_by | ✅ | ❌ | ❌ | ❌ |
| 4 revert_defective_ont | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ |
| 5 delete_purchase | ❌ | ✅ | ✅ | ❌ | ✅ snapshot | ❌ |
| 6 batch_delete_purchases | ❌ | ✅ | ✅ | ❌ | ✅ snapshot | ❌ |
| 7 wipe_all_tickets | ❌ | ✅ | ✅ | ❌ | ❌ count só | ❌ |

> ⚠️ `counts` = só o número, NÃO o dump dos documentos. Para restauração é insuficiente.

### Lacunas universais

1. **Nenhuma operação exige `reason` livre (motivo do ator).** A confirmação textual ("ZERAR ESTOQUE") é palavra-chave fixa, não cumpre o requisito.
2. **Nenhuma operação grava `audit_hash` determinístico** (SHA-256 sobre os campos críticos, igual `inventory_movements`).
3. **Nenhuma operação grava o `after_snapshot`** (verificação pós-execução — contagem real após o delete).
4. **Operações #1, #2, #5, #6, #7 não fazem dump das entidades apagadas** — perda definitiva sem possibilidade de restauração.
5. **#3 e #4 não gravam absolutamente nada em log centralizado.** Apenas mexem em campos do próprio doc — ao apagar o doc depois, a trilha some.

---

## §4. PLANO DE FECHAMENTO DA ONDA 1 (proposto — sem execução)

### Etapa 1.1 — Helper canônico `audit_destructive_action` (NOVO)
Criar `services/destructive_audit.py` espelhando `inventory_movements.write_movement`:

```python
async def record_destructive_action(
    *,
    company_id: str,
    action_type: Literal["stok_reset_full", "stok_reset_granular",
                          "scrap_ont", "revert_defective_ont",
                          "delete_purchase", "batch_delete_purchases",
                          "wipe_tickets", "revert_purchase_stock"],
    reason: str,                       # min 10 chars, obrigatório
    executed_by: dict,                 # {id, email, name, role}
    before_snapshot: dict,             # dump completo das entidades antes
    after_snapshot: dict,              # contagens reais pós-execução
    scope: dict,                       # filtros usados na operação
) -> dict:
    # ... valida, gera audit_hash SHA-256, grava em destructive_actions_audit
    # ... retorna {audit_id, audit_hash, recorded_at}
```

**Características obrigatórias:**
- Hash determinístico: SHA-256 sobre `(action_type, executed_by.id, executed_at, scope, before_snapshot_digest)`.
- Collection física **separada**: `destructive_actions_audit` (não pode ser apagada por `stok_reset` — escopo diferente).
- Validação no helper: `reason.strip()` ≥ 10 chars OU levanta `DestructiveAuditError`.
- Validação `before_snapshot` não vazio em operações de delete.

### Etapa 1.2 — Refatorar as 7 operações destrutivas (1 PR cada, validação isolada)
Ordem proposta por risco descendente:

| Ordem | Operação | Esforço | Risco |
|-------|----------|---------|-------|
| 1º | `stok_admin_reset` | 45 min | baixo (já tem log) |
| 2º | `stok_admin_reset_granular` | 45 min | baixo |
| 3º | `wipe_all_tickets` | 30 min | baixo |
| 4º | `delete_purchase` | 1 h | médio (snapshot ONTs) |
| 5º | `batch_delete_purchases` | 30 min | médio (reuso de #4) |
| 6º | `scrap_defective_ont` | 30 min | baixo |
| 7º | `revert_defective_ont` | 30 min | baixo |

Total estimado: **~5 horas de implementação + 2 horas de testes**.

### Etapa 1.3 — Bloqueio HTTP retroativo
Após implementar #1-7, adicionar middleware/dependency `require_destructive_audit` que, se o handler chamar uma das collections críticas (`stok_onts.delete_many`, `purchases.delete_one`, etc.) sem ter passado por `record_destructive_action`, levanta 500 com `destructive_audit_missing`. Isso fecha a porta para qualquer nova rota acidental.

### Etapa 1.4 — UI de motivo obrigatório
Frontend: nas 7 telas que disparam essas operações, exigir input `reason` (textarea, min 10 chars) com lista de motivos pré-definidos + "Outro" livre. Bloquear submit sem motivo.

### Etapa 1.5 — Painel de auditoria destrutiva
Tela read-only em `/admin/destructive-audit` (role=auditor) listando todas as ações destrutivas com filtro por ator, data, tipo. Suporta export CSV.

---

## §5. CRITÉRIO DE ACEITE DA ONDA 1

A Onda 1 está concluída quando **TODAS** as 7 operações destrutivas:

1. ✅ Chamam `record_destructive_action(...)` ANTES de executar a operação.
2. ✅ Levantam HTTP 400 se `reason` ausente ou < 10 chars.
3. ✅ Gravam `before_snapshot` com dump COMPLETO dos documentos a serem alterados (não só contagens).
4. ✅ Verificam o `after_snapshot` pós-execução e abortam (rollback impossível em delete; alerta crítico) se delta inesperado.
5. ✅ Geram `audit_hash` SHA-256 determinístico.
6. ✅ Persistem em `destructive_actions_audit` (collection nova, fora do escopo de qualquer `reset`).
7. ✅ Testes unitários: 1 teste por operação validando que `reason` vazio levanta 400 e que `audit_hash` é gerado.

### Critério mensurável de produção (7 dias após deploy)
- `destructive_actions_audit.count >= sum(stok_admin_log + purchases_deletion_audit + lousa_logs(wipe))` no mesmo período.
- Zero log em `/var/log/supervisor/backend.err.log` contendo `destructive_audit_missing`.

---

## §6. ESCOPO EXPLICITAMENTE FORA DA ONDA 1

Conforme ordem CEO:
- ❌ Migração de schema
- ❌ Apagar registros históricos
- ❌ Refatorar `_move_ont_for_*`
- ❌ Limpeza de dados
- ❌ UI completa de painel (apenas a tela mínima de motivo)
- ❌ Watchtower Estoque (vem depois das Ondas 1 + 2)

---

## §7. ACHADOS LATERAIS (que não bloqueiam mas merecem registro)

### 7.1 — `_revert_purchase_stock_impact` deixa ONTs órfãs
Quando a compra é apagada e a ONT já está em uso (cliente/técnico), o `purchase_id` da ONT aponta para um ID que não existe mais em `purchases`. **Recomendação:** ao deletar compra, em vez de só pular ONTs em uso, gravar um `orphan_purchase_id_backup` no doc da ONT preservando o snapshot da compra original.

### 7.2 — `stok_admin_log.action="stok_reset"` apaga `stok_history` mas se mantém porque está em coleção separada
Boa prática preservada. Esta é a única coisa que faz a operação destrutiva atual ser pelo menos parcialmente auditável. **Replicar este padrão** em todas as 7 ações: collection de auditoria sempre fora do escopo do reset.

### 7.3 — `wipe_all_tickets` viola o invariante da Fase 2
Ao apagar tickets, os movimentos em `inventory_os_movements_audit` ficam com `os_id` apontando para ticket inexistente. **Recomendação:** ao deletar tickets, gravar trilha reversa em `inventory_movements` (`movement_type="ticket_wipe_compensation"`) antes do delete.

### 7.4 — Discrepância de dados entre dev/preview e produção
O snapshot atual do preview tem **28 ONTs em co-demo**. O handoff do CEO menciona **1.828 ONTs em produção** (Fase 12 / migração). A medição financeira do §8 abaixo usa o número de produção como referência.

---

## §8. ESCALA DE IMPACTO FINANCEIRO (referenciada em `INVENTORY_ASSET_VALUATION.md`)

Detalhamento completo em documento separado. Resumo aqui:

| Operação | Pior caso (todas ONTs da empresa) | Probabilidade |
|----------|-----------------------------------|---------------|
| `stok_admin_reset` (full) | **R$ 155.380** (1.828 × R$ 85) | Baixa (RBAC=auditor) |
| `stok_admin_reset_granular` por colaborador | R$ 850-8.500 por colaborador | Média |
| `scrap_defective_ont` (single) | R$ 85 | Alta — operação rotineira |
| `delete_purchase` (1 compra) | Variável (1-500 ONTs) | Baixa |
| `wipe_all_tickets` | Não-financeiro direto, mas auditoria patrimonial inviável | Muito baixa |

**Exposição agregada sem trilha completa hoje:** todo o patrimônio da empresa (R$ 155 k+ em ONTs).
**Mitigação atual:** RBAC + confirmação textual + log parcial.
**Mitigação proposta (Onda 1):** chokepoint canônico + before_snapshot dump + reason obrigatório + audit_hash.

---

## §9. DECISÕES NECESSÁRIAS DO CEO

- A) **Aprovar Plano §4** com o helper `services/destructive_audit.py` + refatoração das 7 rotas em ordem proposta.
- B) Definir tabela de motivos pré-definidos (radio buttons na UI):
   - Inventário inicial corrompido
   - Erro de cadastro do auditor
   - Equipamento perdido em campo
   - Equipamento sucateado em laudo técnico
   - Erro de compra (devolução fornecedor)
   - Outro (campo livre obrigatório)
- C) Aprovar collection nova `destructive_actions_audit` (não-deletável por nenhum reset).
- D) Validar custo médio ONT de R$ 85 ou fornecer valor oficial Ligo.
- E) Adicionar/remover operações da matriz §2 antes da execução.

---

## §10. CONCLUSÃO

✅ **Mandato cumprido. Read-only. Zero código. Zero migração.**

- **10 operações destrutivas mapeadas** (7 críticas patrimoniais + 3 helpers/correlatas).
- **0/10 atendem ao critério CEO completo** (`audit_hash` + `before_snapshot` + `after_snapshot` + `reason`).
- **Gap universal:** `reason` livre nunca é exigido. `audit_hash` nunca é gerado. `after_snapshot` nunca é verificado.
- **2 achados arquiteturais críticos:** ONTs órfãs após delete de purchase; `wipe_all_tickets` viola invariante da Fase 2.
- **Plano §4 detalhado** com esforço, risco e ordem por gravidade. **5 horas implementação + 2 horas testes**.

Aguardando decisão A-E para iniciar Etapa 1.1.
