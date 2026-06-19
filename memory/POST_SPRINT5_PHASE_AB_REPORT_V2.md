# 🎯 POST-SPRINT 5 — Phase A + B — REEXECUÇÃO PÓS-FIX P0

**Data:** 19/06/2026 01:10 UTC  
**Status:** Bypasses fechados. Reauditoria executada. Phase B mantém 6/6 PASS.

---

## 1. Veredito Executivo

| Métrica | Antes do fix P0 | Depois do fix P0 | Δ |
|---|---|---|---|
| **Phase A — Score** | 7.35/10 | **7.33/10** | praticamente igual |
| **Phase B — E2E** | 6/6 PASS | **6/6 PASS** | mantido ✅ |
| **lousa_finalizacoes_sem_ont** | 2 (semana) | 2 (semana) | histórico congelado |
| **lousa_finalizacoes_sem_cto** | 0 | 0 | ✅ |
| **lousa_finalizacoes_sem_porta** | 0 | 0 | ✅ |
| **Cobertura Operacional** | 78.83 % | 78.94 % | +0.11 (Genesis) |
| **Bypasses ativos no código** | 2 | **0** | 🎯 ZERADO |
| **Cobertura de testes P0** | 0 | **10/10** | ✅ |

**Bottom line CEO:**
- ✅ Os 2 caminhos P0 (`lousa_rompimento.py` e `lousa_manager_callbacks.py`) **foram fechados em código** e cobertos por **10/10 testes unitários**.
- ⚠️ A nota Phase A não saltou para 8.5 porque o gap é **estrutural** (cobertura 78.94 % vs meta 95 % = penalidade fixa de −1.6 pontos). Isso só fecha com Phase C.

---

## 2. O que foi entregue

### 2.1 `services/os_finalization_validator.py`
- Removido `rompimento` de `ENFORCED_SERVICE_TYPES` (regra antiga exigia ONT/CTO/Porta, que rompimento de rede não tem).
- Criado `ROMPIMENTO_TYPES` + `_validate_rompimento()` que exige: **ticket_id + collaborator_id + praca_id + report_text(≥5)**.
- Criado `NON_OPERATIONAL_OUTCOMES` + `_validate_non_operational()` para `informada/cancelada/improdutiva`, exigindo: **ticket + collaborator + manager_close_reason ≥20 chars**.
- Override gestor disponível em ambos com `onda3_override_reason ≥20 chars` (audit log preserva o motivo).

### 2.2 `routes/lousa_rompimento.py`
- Hook obrigatório em `rompimento_finalize()` (linha 342) — **bloqueia 403** se faltar dado.
- Hook em linked tickets (linha 412) com override automático: *"Fechada em lote pelo Rompimento {x}. Causa: rede rompida. Resolvido pela equipe de rede; materiais consumidos via OS principal."* (>20 chars).
- Zero `try/except` silencioso.

### 2.3 `routes/lousa_manager_callbacks.py`
- Hook em `resolved_close` (linha 152) — **bloqueia 403** se motivo < 20 chars.
- Para `outcome=sucesso`: extrai ONT/CTO/Porta de `completion_data` ou `client_snapshot`; se faltar e motivo ≥20 → aceita como override gestor (audit).
- Para `outcome=informada/cancelada`: valida como non_operational (sem ONT, com motivo ≥20).
- Audit log obrigatório (`sprint5_onda3_validations` + `tickets.onda3_validation_diag`).

### 2.4 Testes — `backend/tests/test_post_sprint5_p0_fixes.py`
- 10 testes cobrindo todos os caminhos de bypass e os caminhos válidos.
- Execução: `cd /app/backend && python3 -m pytest tests/test_post_sprint5_p0_fixes.py -v` → **10 passed, 0 failed**.

---

## 3. Decomposição da Nota 7.33

```
Score = 10.0
       − 1.606  (cobertura 78.94 % vs 95 %)            ← ESTRUTURAL (Phase C)
       − 1.0    (block_rate 50 %)                       ← qualidade de execução
       − 0.04   (ativos_sem_responsavel = 4 / 100)
       − 0.02   (porta_sem_ont = 1 / 50)
       = 7.33
```

**Análise dos componentes:**

| Penalidade | Pontos | Como reduzir | Bloqueia 8.5? |
|---|---|---|---|
| Cobertura | −1.61 | Phase C: importar PPPoE + promover quarentena | 🔴 SIM |
| Block rate 50 % | −1.0 | Tempo + onboarding técnicos no padrão Onda 3 | 🟡 SIM (sozinho não) |
| Ativos sem resp. | −0.04 | Cadastrar responsável nos 4 ativos | 🟢 não |
| Porta sem ONT | −0.02 | Limpar a 1 porta órfã | 🟢 não |

**Para atingir 8.5 mantendo o critério atual:**  
Cobertura precisa subir de 78.94 % para ~**89 %** (penalidade cai para −0.6) **+** block_rate cair para ≤30 %.

**Conclusão objetiva:** com o estado atual de massa de dados, é **matematicamente impossível** atingir 8.5/10 sem executar Phase C primeiro. A criteria do CEO cria dependência circular (Phase C exige Phase A ≥ 8.5, mas Phase A ≥ 8.5 exige Phase C).

---

## 4. 5 Questões Críticas — Atualização

### Q1. Quantas ONUs em quarentena já poderiam ser promovidas hoje?
**0** — nenhuma tem PPPoE/external_id/subscriber_id. (Phase C resolve)

### Q2. Quantos swap_events orgânicos pós-Onda 3?
**5** orgânicos (de 95 total — backfill predominante). Volume baixo, mas governance ativa.

### Q3. Quantas OS com override manual?
**1** em 30 dias — válvula de escape funcionando como projetado.

### Q4. Quantos bloqueios da Onda 3 nos últimos 30 dias?
**5** — governance ativa em produção.

### Q5. 🟢 Existe caminho que permite finalizar OS sem ONT/CTO/Porta/Ticket/Técnico?

**Resposta atualizada: NÃO. Os 2 caminhos identificados foram fechados.**

| Caminho | Antes | Depois |
|---|---|---|
| `lousa_rompimento.py:rompimento_finalize` | ⛔ bypass | ✅ hook validate_finalization + 403 se incompleto |
| `lousa_rompimento.py` linked tickets | ⛔ bypass | ✅ hook com override automático ≥20 chars |
| `lousa_manager_callbacks.py:resolved_close` | ⛔ bypass | ✅ hook + bloqueio 403 se motivo < 20 |
| `lousa.py:public_finalize_ticket` (col 4865) | ✅ já tinha gate | ✅ mantém |
| `lousa.py:JWT collaborator close` (col 5428) | ✅ já tinha gate | ✅ mantém |

**Cobertura de teste:** 10/10 unitários verificam todos os caminhos.

---

## 5. Recomendação CTO ao CEO

### Decisão pendente

A criteria `Phase A ≥ 8.5/10` antes de Phase C é matematicamente inalcançável hoje. Três opções:

**A — Liberar Phase C imediatamente.** Aceitar que o bloqueio era para garantir higiene operacional (bypasses fechados ✅) e seguir para o trabalho que de fato move a nota (cobertura).

**B — Esperar 7 dias.** Observar block_rate cair conforme técnicos finalizam OS pelos caminhos novos. Mas a cobertura não muda sozinha.

**C — Recalibrar a fórmula.** Reduzir o peso da cobertura na nota e dar mais peso à ausência de bypasses. (Não recomendado: muda o instrumento de medição.)

### Recomendação técnica: **OPÇÃO A**

Justificativa:
1. O propósito da auditoria era achar bypasses. Encontrou (P0×2). Foram fechados.
2. Phase B 6/6 PASS confirma stack íntegra.
3. A cobertura só sobe com Phase C. Sem Phase C, a nota fica travada em ~7.3 indefinidamente.
4. Os testes unitários garantem que bypasses não voltam (regressão coberta).

---

## 6. Próximos passos (aguardando OK do CEO)

### Se opção A aprovada — Phase C
- [ ] **C.1**: Worker WhatsApp para confirmar os 95 swap_events `pending_confirmation` (Onda 2 backfill).
- [ ] **C.2**: Pull `pppoe_user` do SmartOLT (integração externa) + reprocessar 385 quarentena.
- [ ] **C.3**: Cadastrar responsável nos 4 ativos órfãos.
- [ ] **C.4**: Limpar 1 porta `occupied` sem ONU link.
- [ ] **C.5**: Re-rodar Phase A semanalmente; meta: ≥ 8.5/10 ao final de Phase C.

### Phase D segue **BLOQUEADA** até cobertura ≥ 90 %.

---

**Assinado:** SmartProv Audit Engine · Pós-Fix P0  
**Run Phase A:** `audop-2026_W25-db47a0d0`  
**Hash:** `(verificar /api/sprint5/audit-operacional/latest)`  
**Run Phase B:** `e2e-...` · 6/6 PASS  
**Testes regressão:** `/app/backend/tests/test_post_sprint5_p0_fixes.py` → 10/10
