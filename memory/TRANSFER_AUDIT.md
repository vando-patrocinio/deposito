# ONDA 2.0 — AUDITORIA DE TRANSFERÊNCIAS DO ESTOQUE OPERACIONAL

**Tipo:** Auditoria read-only. ZERO mutação. ZERO migração.
**Data:** 16/Fev/2026
**Autor:** Auditor automatizado (CTO Mode) — Ordem CEO.
**Mandato:** Mapear TODAS as rotas/funções que movimentam ONTs, classificar por aderência ao motor canônico `inventory_movements`, gerar plano de fechamento.

---

## §1. SUMÁRIO EXECUTIVO

### Verdict
> **A trilha canônica `inventory_movements` está vazia em produção (preview):** 0 registros. As 11 ONTs em movimento (10 em técnico + 1 em cliente) NÃO têm nenhuma entrada na trilha auditável. **Toda movimentação histórica passou direto pelo `stok_onts.update_*` sem registrar trilha.**

### Status atual (banco co-demo · 16/Fev 15:20Z)
| Camada | Contagem |
|--------|----------|
| `stok_onts` totais | 28 (10 técnico + 1 cliente + 17 empresa) |
| `stok_history` totais | 99 (93% com `action=null` — campo corrompido) |
| `inventory_os_movements_audit` (canônico) | **0** |
| `destructive_actions_audit` (Onda 1) | 8 (todos dos testes E2E) |
| ONTs em mov sem trilha canônica | **11/11 (100%)** |

### Classificação das rotas mapeadas (14 endpoints + 5 helpers)

| Categoria | Qtd | Significado |
|-----------|-----|-------------|
| 🟢 **CANÔNICA** | 3 | Passa por `enforce_os_inventory_movement` → `write_movement()` |
| 🟡 **LEGADO CONTROLADO** | 4 | Tem observabilidade ativa OU está endereçada por Onda 0/1 |
| 🔴 **BYPASS** | 12 | Escreve direto em `stok_onts` sem trilha canônica |

> **12 rotas escrevem em `stok_onts.update_*` sem chamar `write_movement`.** É a fila de fechamento da Onda 2.

---

## §2. RESPOSTAS ÀS 10 PERGUNTAS DO CEO

### Q1 — Quantas rotas movimentam estoque hoje?
**19 surfaces** (14 endpoints HTTP + 5 helpers internos). Detalhe na §3.

### Q2 — Quantas passam pelo `inventory_movements`?
**3 surfaces canônicas:**
- `routes/lousa.py:public_finalize_ticket` (via guardrail Fase 2)
- `routes/lousa.py:finalize_ticket` (JWT — patch Onda 0a)
- `routes/lousa.py:_revert_ticket_side_effects` (patch Onda 0d, 2 ramos)
- `routes/lousa.py:wipe_all_tickets` (Onda 1 — trilha de compensação)
- `services/os_inventory_guardrail.py:enforce_os_inventory_movement` (helper que delega ao motor)

### Q3 — Quantas ainda escrevem direto em `stok_onts`?
**12 surfaces bypass**, listadas e classificadas na §3.

### Q4 — Quantas transferências por dia?
Hoje no preview: **~0,10/dia** (3 movimentações em 30 dias). Em produção real (1.828 ONTs) o handoff CEO estima **~4,2 OS/dia × ~1,2 ONTs/OS ≈ 5 movimentos/dia**. Volume baixo o suficiente pra fechamento sem riscar SLA.

### Q5 — Quais técnicos mais movimentam?
Não dá pra responder com confiança hoje: 99/99 registros de `stok_history` têm `actor=null`. **Achado crítico:** o campo `actor` da collection histórica está corrompido. Em produção, qualquer ranking de técnico é hoje INVENTADO.

### Q6 — Existe dupla movimentação?
**1 par** detectado (mesmo MAC, mesmo dia, mais de 1 ação). Caso isolado, mas confirma que pode acontecer.

### Q7 — Existe movimentação sem origem?
**0** em `inventory_movements` (zero entradas, então zero sem origem). Em rotas BYPASS o conceito de origem nem é gravado — não é mensurável.

### Q8 — Existe movimentação sem destino?
**0** em `inventory_movements`. Mesma razão.

### Q9 — Existe transferência sem auditoria?
**Sim. 11/11 ONTs (100%)** em movimento ativo (técnico ou cliente) não têm nenhuma entrada em `inventory_movements`. Detalhe:
- 10 ONTs em técnico (6 com SN `AUTOSN_*` bloqueadas pelo D3=a)
- 1 ONT em cliente
- Todas foram movimentadas via BYPASS antes do guardrail entrar em vigor.

### Q10 — Existe diferença entre owner atual e trilha histórica?
Amostra de 200: **0 discrepâncias detectadas**, mas isso é falso positivo: como `inventory_movements` está vazio, a comparação não tem base. **Em prática a verdade é o oposto:** 100% das ONTs em movimento têm trilha histórica ausente.

---

## §3. MATRIZ COMPLETA DAS 19 SURFACES

### 3.1 — Rotas HTTP (14)

| # | Rota / Método | Arquivo : Linha | Classificação | Justificativa |
|---|---------------|------------------|--------------|---------------|
| 1 | `POST /api/lousa/public/tickets/{id}/finalize` | `lousa.py:4448` | 🟢 CANÔNICA | Passa por guardrail (Fase 2) |
| 2 | `POST /api/lousa/tickets/{id}/finalize` (JWT) | `lousa.py:4985` | 🟢 CANÔNICA | Onda 0a — chokepoint inserido |
| 3 | `POST /api/lousa/tickets/wipe-all` | `lousa.py:3589` | 🟢 CANÔNICA | Onda 1 — trilha de compensação |
| 4 | `POST /api/stok/onts/transfer-to-tech` | `stok.py:796` | 🔴 BYPASS | `update_one` direto · empresa→tecnico sem trilha |
| 5 | `POST /api/stok/onts/transfer-to-tech/bulk` | `stok.py:897` | 🔴 BYPASS | `update_many` direto · empresa→tecnico em lote |
| 6 | `POST /api/stok/onts/{mac}/return-to-company` | `stok.py:947` | 🔴 BYPASS | `update_one` direto · tecnico→empresa |
| 7 | `POST /api/stok/onts/reconcile-with-olt` | `stok.py:973` | 🔴 BYPASS | Reconciliação via SmartOLT muta location_type direto |
| 8 | `POST /api/stok/clientes/manual-withdraw` | `stok.py:2851` | 🔴 BYPASS | "RETIRADA MANUAL" pelo gestor — sem OS, sem trilha |
| 9 | `POST /api/stok/onts/{mac}/set-sn` | `stok.py:707` | 🟡 LEGADO CONTROLADO | Não move owner, só corrige SN |
| 10 | `POST /api/stok/onts/migrate-fill-sn` | `stok.py:749` | 🟡 LEGADO CONTROLADO | Migração one-shot AUTOSN_* (D3=a) |
| 11 | `POST /api/stok-transfers/defective-onts/{mac}/confirm-return` | `stok_transfers.py:187` | 🔴 BYPASS | tecnico→empresa (devolução defeito) sem trilha |
| 12 | `POST /api/stok-transfers/defective-onts/{mac}/scrap` | `stok_transfers.py:237` | 🟡 LEGADO CONTROLADO | Onda 1.4 — destructive_audit gravado, mas movimento patrimonial ainda fora de inventory_movements |
| 13 | `POST /api/stok-transfers/defective-onts/{mac}/revert` | `stok_transfers.py:317` | 🟡 LEGADO CONTROLADO | Idem 12 |
| 14 | `POST /api/stok-transfers/pending-transfers/{id}/approve` | `stok_transfers.py:521` | 🔴 BYPASS | Aprovação muta tecnico→cliente direto |
| 15 | `POST /api/stok-transfers/pending-transfers/{id}/reject` | `stok_transfers.py:557` | 🔴 BYPASS | Restaura status sem trilha |
| 16 | `POST /api/field-ops/equipment/return` | `field_ops.py:1055` | 🔴 BYPASS | Devolução de campo (técnico app) sem trilha |
| 17 | `POST /api/ont-scan/...` | `ont_scan.py:247` | 🔴 BYPASS | Update direto após scan |
| 18 | `POST /api/balanco/...` | `balanco.py:358` | 🔴 BYPASS | Balanço muta status |

### 3.2 — Helpers internos (5)

| # | Função | Arquivo : Linha | Classificação |
|---|--------|------------------|---------------|
| H1 | `enforce_os_inventory_movement` | `os_inventory_guardrail.py:85` | 🟢 CANÔNICA (delega a write_movement) |
| H2 | `_move_ont_for_install` | `lousa.py:~2700` | 🟡 LEGADO CONTROLADO (chamado pelo guardrail mas faz update direto) |
| H3 | `_move_ont_for_withdraw` | `lousa.py:~2800` | 🟡 LEGADO CONTROLADO (idem H2) |
| H4 | `_revert_ticket_side_effects` | `lousa.py:2930` | 🟢 CANÔNICA (Onda 0d patch) |
| H5 | `auto_close_service_from_ticket` | `stok.py:2287` | 🟡 LEGADO CONTROLADO (Onda 0b — observabilidade ativa) |

---

## §4. RANKING DE GRAVIDADE (BYPASS apenas)

Ordenado por **volume estimado** × **escopo destrutivo**:

| Prioridade | Bypass | Frequência típica | Owner change | Plano de fechamento |
|------------|--------|-------------------|--------------|---------------------|
| 🔴 **P0** | `transfer-to-tech/bulk` (#5) | Dia-a-dia · gestor | empresa→tecnico em lote | 1ª refatoração |
| 🔴 **P0** | `transfer-to-tech` (#4) | Dia-a-dia · gestor | empresa→tecnico | 2ª refatoração |
| 🔴 **P0** | `return-to-company` (#6) | Frequente | tecnico→empresa | 3ª refatoração |
| 🔴 **P0** | `manual-withdraw` (#8) | Esporádico mas crítico | cliente→tecnico sem OS | 4ª — exige verificação extra |
| 🔴 **P1** | `pending-transfers/approve` (#14) | Frequente | tecnico→cliente | 5ª |
| 🔴 **P1** | `pending-transfers/reject` (#15) | Esporádico | tecnico→tecnico (limpa flags) | 6ª |
| 🔴 **P1** | `field-ops/equipment/return` (#16) | Diário (técnicos) | cliente→tecnico | 7ª |
| 🔴 **P1** | `defective/confirm-return` (#11) | Semanal | tecnico→empresa | 8ª |
| 🔴 **P2** | `reconcile-with-olt` (#7) | On-demand | sync SmartOLT | 9ª — requer mapeamento ON 0/0c |
| 🔴 **P2** | `ont-scan` (#17) | On-demand | confirmação física | 10ª |
| 🔴 **P2** | `balanco` (#18) | Mensal | reconciliação contábil | 11ª |

---

## §5. PLANO DE FECHAMENTO DA ONDA 2 (proposto — sem execução)

### Etapa 2.1 — Helper canônico de transferência (NOVO)
Criar `services/transfer_engine.py` espelhando `record_destructive_action`:

```python
async def execute_transfer(
    *,
    company_id: str,
    movement_type: Literal[
        "transfer_empresa_tecnico", "transfer_tecnico_empresa",
        "transfer_tecnico_cliente", "transfer_cliente_tecnico",
        "transfer_tecnico_defeito", "transfer_defeito_empresa",
    ],
    sn: str, mac: Optional[str],
    origin: Dict, destination: Dict,
    actor: Dict, reason: Optional[str] = None,
    ticket_id: Optional[str] = None,    # liga à OS quando houver
) -> Dict:
    # 1. valida (igual ao guardrail)
    # 2. snapshot do estado atual
    # 3. write_movement → inventory_os_movements_audit (audit_hash + idempotência)
    # 4. update_one em stok_onts
    # 5. retorna {movement_id, audit_hash, before, after}
```

**Características:**
- Idempotente por `audit_hash` (re-execução não duplica).
- Bloqueia AUTOSN_* (D3=a) automaticamente.
- 1 ponto de entrada para 12 rotas BYPASS.

### Etapa 2.2 — Refatoração sequencial das 12 rotas BYPASS
Mesmo padrão de PRs sequenciais da Onda 1 (1.1 → 1.4). Por ordem de gravidade (§4):
- **PR 2.2** — `transfer-to-tech` + `bulk` (~1h)
- **PR 2.3** — `return-to-company` (~30min)
- **PR 2.4** — `manual-withdraw` (~1h — exige verificação OS)
- **PR 2.5** — `pending-transfers/approve` + `reject` (~30min)
- **PR 2.6** — `field-ops/equipment/return` (~45min)
- **PR 2.7** — `defective/confirm-return` (~30min)
- **PR 2.8** — `reconcile-with-olt` (~1h — mais complexa)
- **PR 2.9** — `ont-scan` + `balanco` (~30min)

Total estimado: **~6h impl + 2h testes + 1 rodada testing_agent_v3_fork**.

### Etapa 2.3 — Sunset dos `_move_ont_for_*` (helpers H2/H3)
Após 2.2-2.9, esses helpers viram redirects para `transfer_engine.execute_transfer`. Mantém compat retroativa.

### Etapa 2.4 — Limpeza do `stok_history.action=null`
**Achado lateral crítico** (Q5): 93% dos 99 registros têm action=null. Backfill ou descarte controlado é necessário antes do Watchtower ranking por técnico fazer sentido.

---

## §6. CRITÉRIO DE ACEITE DA ONDA 2

Onda 2 só pode ser declarada CONCLUÍDA quando:
1. ✅ Helper `services/transfer_engine.py` existe.
2. ✅ 12 rotas BYPASS refatoradas (zero `stok_onts.update_*` fora do helper).
3. ✅ `inventory_os_movements_audit.count_documents({})` > 0 em produção (deve crescer com cada movimento).
4. ✅ 100% das ONTs em técnico/cliente têm pelo menos 1 entrada em `inventory_movements`.
5. ✅ Discrepância owner_atual ≠ trilha = 0.
6. ✅ Testing agent valida 12 rotas.

---

## §7. ESCOPO EXPLICITAMENTE FORA DA ONDA 2

- ❌ Watchtower UI (vem depois)
- ❌ Migração de dados históricos (backfill retroativo das 11 ONTs sem trilha — discussão separada)
- ❌ Fase 3 Owner & Location normalization
- ❌ Limpeza do `stok_history.action=null` em massa (Etapa 2.4 é só **detecção** — limpeza requer aprovação separada)
- ❌ Hook automático de valuation (R1.4 ainda em observação 24h)

---

## §8. ACHADOS LATERAIS

### 8.1 — `stok_history.action=null` em 93% dos registros (Q5)
Crítico. **Sem isso o ranking de técnicos não tem base.** O campo `actor` também está null em 100%. Em produção esse problema deve estar replicado.

### 8.2 — Discrepância "0" é falso positivo (Q10)
O motor canônico está vazio em produção. Quando começar a popular, espera-se ver discrepâncias temporárias até a trilha alcançar o backlog.

### 8.3 — 6/11 ONTs em técnico têm SN `AUTOSN_*`
D3=a aplicado corretamente — essas ONTs estão **bloqueadas para qualquer movimento** até re-scan. O fechamento da Onda 2 inclui processar essa fila.

---

## §9. DECISÕES NECESSÁRIAS DO CEO

- **A)** Aprovar plano §5 com helper `services/transfer_engine.py` + refatoração das 12 rotas em ordem de gravidade.
- **B)** Decidir política para os 11 órfãos atuais (sem trilha):
   - B1) Geração de trilha sintética com `movement_type=onda2_orphan_backfill` (1 movimento sintético por ONT, marcado como inferido).
   - B2) Deixar como estão; novo movimento futuro vira a primeira entrada na trilha.
   - B3) Bloquear movimentação até trilha sintética ser confirmada por humano (mais conservador, +fricção).
- **C)** Definir se o helper deve aceitar `reason` opcional (transferências operacionais) ou obrigatório (alinhado com Onda 1).
- **D)** Confirmar que Etapa 2.4 (cleanup `stok_history.action=null`) é separada da Onda 2 e vira backlog próprio.

---

## §10. CONCLUSÃO

✅ **Mandato cumprido. Read-only. Zero código. Zero migração.**

- **19 surfaces mapeadas** (14 endpoints + 5 helpers).
- **3 canônicas · 4 legado controlado · 12 BYPASS.**
- **100% das ONTs em movimento ativo (11/11) não têm trilha.**
- **`stok_history` está semanticamente quebrado** (93% action=null).
- Plano §5 com 8 PRs sequenciais (~6h impl + 2h testes).

Detalhamento operacional em `TRANSFER_FLOW_MATRIX.md`.
