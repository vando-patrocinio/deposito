# 🎯 POST-SPRINT 5 — Phase A + Phase B Report

**Data:** 19/06/2026  
**Diretiva CEO:** Estabelecer KPI "Cobertura Operacional" via Auditoria Semanal (Phase A) + Simulação E2E Técnico (Phase B). Critério desbloqueio Phase C: Auditoria ≥ 8.5/10 E E2E ≥ 5/6.  
**Critério desbloqueio Phase D (Gauge Watchtower):** Cobertura Operacional ≥ 90 %.

---

## 1. Resumo Executivo

| KPI | Valor | Status |
|---|---|---|
| **Auditoria Operacional Semanal** | **7.35 / 10** | 🟡 COM RESSALVAS |
| **Simulação E2E Técnico** | **6 / 6 PASS (100 %)** | 🟢 APROVADA |
| **Cobertura Operacional** | **78.83 %** | 🔴 < 90 % (Gauge bloqueado) |
| **Compliance Patrimonial** | **78.85 %** | 🟡 < 95 % |
| **Swap Events orgânicos pós-Onda 3** | **5** | 🟡 baixo |
| **Bloqueios Onda 3 (30 d)** | **5** | 🟢 governance ativa |
| **OS com override manual (30 d)** | **1** | 🟢 controlado |
| **Caminho operacional bypass** | **2 encontrados** | 🔴 **P0** |

**Veredito CEO:** Phase C **NÃO LIBERADA** (auditoria abaixo de 8.5). Phase D **NÃO LIBERADA** (cobertura < 90 %).

---

## 2. Phase A — Auditoria Operacional Semanal (semana 2026-W25)

`POST /api/sprint5/audit-operacional/run-weekly` · `audop-2026_W25-92a7fec5` · hash `b4c289cf32caf057a639562136c47ca64f70a51aa47024e512231c13cc573324`.

### Respostas (13 perguntas + 2 percentuais)

**Lousa (6 perguntas):**
- OS bloqueadas semana: **5**
- Overrides realizados: **1**
- Finalizações sem ONT: **2**
- Finalizações sem CTO: **0**
- Finalizações sem Porta: **0**
- Swaps pendentes confirmação: **87** (87 do backfill Onda 2 + nenhum WhatsApp enviado)

**Patrimônio (5 perguntas):**
- Promoções quarentena → oficial (semana): **0**
- Ativos sem localização: **0**
- Ativos sem responsável: **0**
- Cobertura Operacional: **78.72 %** (1445 oficial / 1833 SmartOLT)
- Compliance Patrimonial (oficial / oficial+quarentena): **78.85 %**

**Rede (2 perguntas):**
- Portas ocupadas sem ONU vinculada: **1**
- ONUs SmartOLT sem registro em estoque: **389**

### Cálculo da Nota

- Base 10.0
- Penalidade cobertura (95−78.72)/10 = **−1.63**
- Penalidade compliance < 75 % = **0** (estamos em 78.85 %)
- Penalidade ativos sem responsável = 0
- Penalidade port_sem_ont (1/50) = **−0.02**
- Penalidade rate bloqueios (5/6 = 83 % > 30 %) = **−1.0**
- **Final: 7.35 → COM RESSALVAS**

---

## 3. Phase B — Simulação E2E Técnico

`POST /api/sprint5/audit-flow/simulate-technician-journey?confirm=true` · run_id `e2e-64559ab13e2e`.

Cliente sintético `sub-e2e-750bf6359a` percorre 6 cenários. 8 checks por cenário (Cliente, CTO, Porta, ONU, Técnico, Ticket, Estoque, SmartOLT).

| Cenário | Resultado |
|---|---|
| 1. Instalação | 8/8 (100 %) ✅ |
| 2. Reparo | 8/8 (100 %) ✅ |
| 3. Troca ONU | 8/8 (100 %) ✅ |
| 4. Mudança Porta | 8/8 (100 %) ✅ |
| 5. Mudança CTO | 8/8 (100 %) ✅ |
| 6. Retirada | 8/8 (100 %) ✅ |
| **TOTAL** | **6/6 PASS** ✅ |

**Conclusão:** Stack `network_access_canonical` + `swap_event_writer` + `stok_history_writer` está íntegra. Quando o caminho da Lousa REAL é usado, traceabilidade end-to-end funciona em 100 % dos casos sintéticos.

---

## 4. Atenção Especial — 5 Questões Críticas CEO

### Q1. Quantas das 387 ONUs em quarentena já poderiam ser promovidas hoje?

**Resposta: 0.**

Todas as 387 estão em quarentena justamente porque **não têm PPPoE, external_id nem subscriber_id** que permitiriam validação automática. Têm SN apenas. Promoção exige:
- Match SN-SN com SmartOLT (parcial — algumas têm match)
- E vinculação a `subscriber_id` ativo (zero hoje)

Caminho para liberar quarentena: integração SmartOLT precisa popular `pppoe_user` durante o sync ou processo manual de verificação técnica.

### Q2. Quantos swap_events reais foram gerados após a Onda 3?

**Resposta: 5 orgânicos (de 92 total).**

Breakdown:
- 87 vieram do backfill da Onda 2 (`created_by` contém "backfill")
- **5 orgânicos** criados via finalização real de OS pós-Onda 3

⚠️ Volume baixo. Indica que poucas OS estão chegando ao caminho oficial. Ou:
- Operação fechou tickets sem trocar ONU
- Operação usou caminho bypass (ver §5)
- Volume real de operação é baixo

### Q3. Quantas OS continuam usando override manual?

**Resposta: 1 nos últimos 30 dias.**

Override usado em `tkt-test-onda3-6` (OS-TEST6) — instalação onde "CTO ainda em mapeamento, autorizado pelo gestor". Esse caminho NÃO é abuso — é a válvula de escape projetada pela Onda 3. Justificativa registrada em `sprint5_onda3_validations.diag.override_reason`.

### Q4. Quantos bloqueios da Onda 3 ocorreram nos últimos 30 dias?

**Resposta: 5 nos últimos 30 dias** (todos: 5).

Detalhes:
- 2 OS bloqueadas por `missing: ont_identifier` (instalação sem ONT)
- 0 OS bloqueadas por `missing: cto_id`
- 0 OS bloqueadas por `missing: port_number`
- 3 outros tipos de bloqueio

A Onda 3 está **ATIVA e funcionando**. O CTO/Porta está sendo respeitado. Falta apenas ONT em alguns casos.

### Q5. 🔴 P0 CRÍTICO — Existe caminho que permite finalizar OS sem ONU/CTO/Porta/Ticket/Técnico?

**Resposta: SIM. 2 caminhos identificados.**

#### **5.1 — `lousa_rompimento.py` (linhas 345 e 412)**

```python
# Sem chamar validate_finalization da Onda 3
await db.tickets.update_one(
    {"id": ticket_id},
    {"$set": {"status": "finalizada", "outcome": "sucesso", ...}}
)
```

**Evidência (30 d):** 4 tickets fechados via esse caminho — `tkt-5fd404371b`, `tkt-8d50b58c37`, `tkt-d26909c84d`, `tkt-7b5eff4fe1`. Outcome=`sucesso`, sem ONT, sem CTO, sem porta.

- Nota: rompimento de fibra NÃO tem ONT/CTO/Porta de cliente. Mas o validador `os_finalization_validator` lista `"rompimento"` em `ENFORCED_SERVICE_TYPES`. Inconsistência.
- Decisão necessária: ou (a) tirar `rompimento` do ENFORCED e fazer regra própria (ticket + técnico + materiais), ou (b) plugar `validate_finalization` em `lousa_rompimento.py:345/412` com modo `rompimento_skip`.

#### **5.2 — `lousa_manager_callbacks.py:152` (resolved_close pelo gestor)**

```python
await db.tickets.update_one(
    {"id": ticket_id},
    {"$set": {"status": "finalizada", "outcome": outcome, ...}}
)
```

**Evidência (30 d):** 2 tickets — `tkt-989e57f6fb` (ROMPIMENTO) e `tkt-f83799d7e4` (REPARO MAGE) — outcome=`rompimento_solucionado`, fechados sem chamar Onda 3.

- Risco: gestor pode escolher `outcome="sucesso"` e fechar OS de instalação/reparo sem ONT/CTO. Atualmente é mitigado porque o frontend só oferece outcomes ["informada","sucesso","cancelada"] no callback, mas a regra de negócio precisa do gate Onda 3.

---

## 5. Gaps Encontrados — Classificação

### 🔴 P0 — Bypass Onda 3 (CRÍTICO)

| ID | Gap | Arquivo | Linha | Impacto |
|---|---|---|---|---|
| P0-1 | Rompimento bypass | `routes/lousa_rompimento.py` | 345, 412 | 4 OS últimos 30 d sem trilha Onda 3 |
| P0-2 | Manager callback bypass | `routes/lousa_manager_callbacks.py` | 152 | 2 OS últimos 30 d sem trilha; superfície para gestor furar gate |

**Plano de correção:**
1. Hook `validate_finalization` nos 2 arquivos com modo `service_type="rompimento"` corretamente sinalizado. (~1h)
2. Adicionar `rompimento_solucionado` ao `EXEMPT_SERVICE_TYPES` OU criar `RompimentoFinalizationValidator` separado. (~30 min)
3. Adicionar testes de regressão: `test_no_finalization_bypass.py`. (~1h)
4. **Estimativa total: 2.5h.**

### 🟡 P1 — Cobertura Operacional (78.83 % → 90 %)

| ID | Gap | Bloqueio |
|---|---|---|
| P1-1 | 387 ONUs em quarentena sem PPPoE | Phase D bloqueada |
| P1-2 | 389 ONUs SmartOLT sem registro em estoque | Cobertura travada |
| P1-3 | 87 swaps com `pending_confirmation` (backfill Onda 2) | Confiabilidade swap_events |

**Plano de correção (Phase C):**
1. Integração SmartOLT sync pull de `pppoe_user` + reprocessamento de quarentena. (~4h)
2. Script `genesis_smartolt_v2.py` para promover quarentena com PPPoE recém-descoberto. (~3h)
3. Worker WhatsApp para confirmar os 87 backfill swaps com técnicos. (~2h)
4. **Estimativa total: 9h** para subir de 78.83 % → ≥ 90 %.

### 🟢 P2 — Refinamento (não bloqueante)

| ID | Gap | Estimativa |
|---|---|---|
| P2-1 | Apenas 5 swap_events orgânicos pós-Onda 3 (validar volume) | 1h investigação |
| P2-2 | 1 porta `occupied` sem ONU link | 30 min limpeza |
| P2-3 | 0 promoções quarentena → oficial na semana | KPI estagnado, depende P1 |

---

## 6. Impacto

### Patrimonial
- ✅ Compliance 78.85 % (cresce conforme quarentena é promovida).
- 🟡 Cobertura 78.83 % bloqueia Phase D (gauge Watchtower).
- ✅ Auto Balanço (Onda 6) operando diariamente; certidões SHA-256 íntegras.

### Operacional
- 🔴 2 caminhos de bypass abertos comprometem o KPI "Cobertura Operacional Bloqueante" — operação pode finalizar OS sem ONT/CTO em circunstâncias específicas (rompimento + manager_close).
- 🟢 Caminho normal da Lousa (`public_finalize_ticket`, JWT colaborador) respeita Onda 3.
- 🟢 E2E sintético 6/6: stack core íntegra.

### Financeiro
- 🟢 Auto Balanço Patrimonial roda sem erro 00:05 UTC.
- 🟡 Os 87 swap_events `pending_confirmation` não geram custo errado por enquanto, mas atrasam fechamento Compliance Score V2.

### Rastreabilidade
- 🟢 Stack canônica (network_access_canonical + swap_events + stok_history) **funciona 100 % em E2E sintético**.
- 🔴 Em produção real, 6/152 (3.94 %) das movimentações `stok_history` últimos 30 d não têm `ticket_id` — provavelmente backfill ou bypass acima.

---

## 7. Próximos Passos (ordem CEO)

### Antes de liberar Phase C
- [ ] **P0-1 + P0-2**: fechar bypasses em `lousa_rompimento.py` e `lousa_manager_callbacks.py` (2.5h).
- [ ] Re-rodar Phase A e validar:
  - score ≥ 8.5/10
  - `lousa_finalizacoes_sem_ont` = 0 nos próximos 7 dias

### Phase C (Cobertura Operacional 78.83 % → 90 %)
- [ ] Pull PPPoE do SmartOLT + reprocessar quarentena.
- [ ] Worker WhatsApp para os 87 backfill swaps pendentes.
- [ ] Genesis v2 com PPPoE descoberto.

### Phase D (BLOQUEADA até cobertura ≥ 90 %)
- [ ] Construir gauge "Cobertura Operacional" no Watchtower Patrimônio.
- [ ] Alertas automáticos se cair abaixo de 85 %.

---

**Assinado:** SmartProv Audit Engine · Sprint 5 Post-Audit · Versão 1.0  
**Hash Auditoria A:** `b4c289cf32caf057a639562136c47ca64f70a51aa47024e512231c13cc573324`  
**Run ID Simulação B:** `e2e-64559ab13e2e`
