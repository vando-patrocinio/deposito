# 🔄 SWAP PENDING — ROOT CAUSE

**Data:** 19/06/2026  
**Ordem CEO:** Auditar 13 swaps pendentes + classificar  
**Modo:** Read-only forensic

---

## 1. ACHADO PRINCIPAL — Os 13 swaps pending são 100 % sintéticos

```
═══════════════════════════════════════════════════════════
TOTAL PENDENTE:                          13
  ├─ status=sent_to_technician:           9
  └─ status=pending_confirmation:         4

CLASSIFICAÇÃO POR ORIGEM:
  ├─ TEST/E2E:                           13  ← 100 %
  └─ PRODUÇÃO REAL:                       0
═══════════════════════════════════════════════════════════
```

---

## 2. DETALHAMENTO DOS 13 ITENS

| # | swap_id | ticket_id | subscriber | collaborator_id | status |
|---:|---|---|---|---|---|
| 1 | `swp-c6f1372bbe9648` | `tkt-onda3-real-3` | Vando Patrocinio (teste curado) | `col-real-3` ❌ não existe | sent_to_technician |
| 2 | `swp-9df1b39b8b8e4d` | `tkt-e2e-e2e-64559ab13e2e` | E2E Teste | `col-e2e-tech` ❌ não existe | sent_to_technician |
| 3 | `swp-4a0f4796fa5d44` | `tkt-e2e-...-rep` | E2E | `col-e2e-tech` ❌ | sent_to_technician |
| 4 | `swp-87c5754d71b64d` | `tkt-e2e-...-troca` | E2E | `col-e2e-tech` ❌ | sent_to_technician |
| 5 | `swp-cc0f0d0dfb0c4b` | `tkt-e2e-...-ret` | E2E | `col-e2e-tech` ❌ | sent_to_technician |
| 6-9 | E2E run 2 (`cfde2185fd6e`) | 4 cenários | E2E | `col-e2e-tech` ❌ | sent_to_technician |
| 10-13 | E2E run 3 (`7886dc024495`) | 4 cenários | E2E | `col-e2e-tech` ❌ | pending_confirmation |

**Padrão identificado**: cada execução da Phase B (`simulate-technician-journey`) cria **4 swap events** sintéticos. Foram executadas 3 vezes hoje → 12 swaps E2E + 1 do teste curado da Onda 3 (Vando Patrocinio) = **13**.

---

## 3. CLASSIFICAÇÃO POR DEPENDÊNCIA

| Classe | Definição | Quantidade |
|---|---|---:|
| RESOLVÍVEL | técnico cadastrado, cliente com telefone, swap real | **0** |
| DEPENDENTE_CLIENTE | sem telefone do subscriber | **0** |
| DEPENDENTE_TECNICO | `collaborator_id` inexistente na coleção `collaborators` | **13** |

**Insight**: TODOS os 13 são "dependente técnico", mas a dependência é **DADO sintético**, não falha operacional. Os IDs `col-real-3` e `col-e2e-tech` foram criados pelos scripts de teste e nunca cadastrados como colaborador real.

---

## 4. SITUAÇÃO POR FLUXO

### 4.1 Sent_to_technician (9)
Foram criados pela Phase C.1 (hoje, ação operacional) — esperavam que o gestor enviasse WhatsApp real. Como são E2E sintéticos, **nenhum WhatsApp deve ser enviado**.

### 4.2 Pending_confirmation (4)
Vieram da última execução do E2E validator (após Phase C.1 já ter limpado os anteriores).  
Cada `simulate-technician-journey` cria swap events em estado pendente.

---

## 5. CAUSA RAIZ

```
═══════════════════════════════════════════════════════════
A CAUSA RAIZ DOS "13 SWAPS PENDING" É O VALIDADOR E2E.

A cada execução do endpoint:
  POST /api/sprint5/audit-flow/simulate-technician-journey

São criados 4 swap_events sintéticos que ficam em estado
pendente. Hoje, com 3 execuções na auditoria, restaram 12.
+ 1 do teste curado da Onda 3 = 13.
═══════════════════════════════════════════════════════════
```

**Por que não impactam estoque**: o validador E2E usa subscribers/CTOs/ONTs **marcados como sintéticos** (`_e2e_synthetic=true` aplicado pela Phase C.3). O patrimônio real não é tocado.

---

## 6. AÇÃO RECOMENDADA (sem código, sem migração)

```
═══════════════════════════════════════════════════════════
OPÇÃO 1 (recomendada): marcar via gestor
   Tagear os 13 com:
     confirmation_status = "confirmed_via_synthetic_test"
     confirmed_by        = "phase_d_audit_19_06"
     reason              = "Swap criado pelo validador E2E ou
                            teste curado da Onda 3; sem
                            impacto operacional."
   
   Resultado:
     - pending = 0
     - audit trail preservado (não-delete)
     - KPI "swap pending ≤ 5" atingido

OPÇÃO 2: não tocar
   - Aceitar que swaps E2E ficam pending até serem
     consumidos por testes futuros
   - Atualizar a fórmula da Phase A para excluir swaps
     com `created_by LIKE 'e2e:%' OR 'auto_close_lousa:col-real-%'`
   - (NÃO RECOMENDADA — viola política "sem ajuste de fórmula")
═══════════════════════════════════════════════════════════
```

---

## 7. CRITÉRIO DE SUCESSO

✅ Confirmado: os 13 pending são **100 % sintéticos** (E2E + teste curado).  
✅ Confirmado: zero swaps reais pendentes na operação.  
✅ Recomendação: marcar como `confirmed_via_synthetic_test` para zerar o KPI mantendo audit trail.

**Critério "Swap pending ≤ 5"**: atingível imediatamente via Opção 1.

---

**Arquivo de dados:** `/tmp/swap_triage.json` (13 registros detalhados)
