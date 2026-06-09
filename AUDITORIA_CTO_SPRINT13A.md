# AUDITORIA CTO — SPRINT 13A (Event Bus Invasivo)

**Data:** 2026-06-08 02:50 UTC · **DB:** `test_database` (local dev)
**Escopo auditado:** o que mudou de fato após a entrega do
`event_emitters.py` + `auto_emit_middleware.py` + plug-ins associados.
**Princípio:** medir IMPACTO OPERACIONAL, não esforço de implementação.

---

## 1) COBERTURA NERVOSA

| Métrica | Antes | Depois | Δ |
|---|---:|---:|---:|
| Módulos totais (services/routes/workers) | 231 | **235** | +4 |
| Módulos que emitem eventos | 8 | **9** | +1 |
| Módulos silenciosos | 223 | **226** | +3 |
| **Cobertura nervosa** | 3.5% | **3.83%** | **+0.33 pp** |

🔴 **Verdade dura:** A Sprint 13A entregou a INFRAESTRUTURA (middleware HTTP auto-emit + helper `emit_business` com 28 kinds), mas o número de módulos que efetivamente emitem **NÃO se moveu de forma material**. Saiu de 3.5% para 3.83% — uma melhora cosmética. O middleware é **invocado em toda request HTTP**, mas só **emite quando o handler retorna 2xx em uma das 13 rotas mapeadas**. Em ambiente dev sem tráfego real, isso = 0 eventos auto-emitidos.

> **Métrica que prova o ponto:** `motor_ia_events.find({"payload._auto_emitted": True}).count()` = **0**.
> Disparei 8 POST manuais (sem auth) nas rotas mapeadas — todos retornaram 401, e o middleware **não emitiu nada** porque a regra é `200 ≤ status < 300`.

---

## 2) EVENTOS

| Métrica | Antes | Depois |
|---|---:|---:|
| EventTypes definidos | 33 | **33** (sem novos) |
| EventTypes efetivamente emitidos | 7 | **7** ⬅️ MESMO |
| Utilização da taxonomia | 21.2% | **21.2%** ⬅️ MESMO |
| Total de eventos no bus | 125 | **143** (+14%) |

**Tipos emitidos hoje (idênticos aos de antes):**
`AI_LEARNING_ALERT, CLIENT_CHURN_RISK, CLIENT_OFFLINE, DATA_QUALITY_DROP, PAYMENT_OVERDUE, RBAC_DENIED, presidente_scan`

🔴 Os 26 EventTypes definidos pelo mapeamento (`TICKET_OPENED`, `SALE_CREATED`, `WA_INBOUND_RECEIVED`, `PARTNER_QR_REDEEMED`, etc.) **continuam zerados** porque ninguém disparou as rotas autenticado.

---

## 3) TOP PRODUTORES (atual)

| # | Módulo (`source`) | Eventos | Última emissão |
|---:|---|---:|---|
| 1 | `audit_alerts_legacy` | 55 | 2026-06-08 01:56 |
| 2 | `data_quality_ia` | 31 | 2026-06-08 02:49 |
| 3 | `smartolt` | 18 | 2026-06-08 02:12 |
| 4 | `presidente_ia` | 10 | — |
| 5 | `churn_scheduler` | 8 | 2026-06-08 02:12 |
| 6 | `learnings` | 6 | 2026-06-08 02:47 |
| 7 | `rbac` | 6 | 2026-06-08 02:12 |
| 8 | `test_e2e` | 5 | 2026-06-08 02:12 |
| 9 | `financeiro` | 4 | 2026-06-08 02:12 |
| — | (sem 10º produtor real além dos seeds de teste) | — | — |

**`auto_emit_middleware`** (a entrega-bandeira da Sprint 13A) **não aparece na lista**.

---

## 4) MÓDULOS CRÍTICOS (geram eventos?)

| Domínio | Antes | Depois |
|---|:-:|:-:|
| Clientes | ✅ via `churn_scheduler` | ✅ (sem mudança) |
| Financeiro | 🟡 1 source | 🟡 1 source (sem mudança real) |
| WhatsApp | 🔴 | 🔴 (kind mapeado, produtor não plugado) |
| RBAC | ✅ | ✅ |
| Audit Trail | ✅ (via `audit_alerts_legacy`) | ✅ |
| GPS | 🔴 | 🔴 (kind mapeado, sem produtor) |
| Parceiros | 🔴 | 🔴 (kind mapeado, sem produtor) |
| Indicações | 🔴 | 🔴 (kind mapeado, sem produtor) |
| Estoque | 🔴 | 🔴 (sem kind nem produtor) |
| Rede | 🟡 via `smartolt` | 🟡 (sem mudança) |
| SmartOLT | 🟡 18 eventos legados | 🟡 (sem mudança) |
| Atendimento (tickets) | 🔴 | 🔴 (kind mapeado, sem produtor real) |
| Lousa | 🔴 | 🔴 (sem kind) |

> **5 de 13 domínios** com produção viva, **8 ainda silenciosos**. O middleware está **pronto** para capturar quando esses módulos receberem tráfego real autenticado — mas isso é **promessa de futuro**, não impacto atual.

---

## 5) PRESIDENTE IA — o que ele enxerga agora

🔴 **Pouco a nada de novo, na prática.**

- **Novos sinais detectados:** zero. Os 7 tipos emitidos são os mesmos de antes.
- **Novas correlações:** o `correlation_id` propaga continuamente (61-65%), mas nenhum NOVO fluxo de causa-raiz emergiu porque os novos produtores não estão emitindo.
- **Novas oportunidades:** o `Estrategista IA` não passou a citar dados de WhatsApp/Tickets/Vendas/GPS porque eles continuam sem emitir.
- **Novos riscos:** apenas 1 `AI_LEARNING_ALERT` foi emitido (factor caiu ≥30% em uma regra). Isso já existia em Sprint 12.

✅ **O que mudou de fato (infra):**
- Existe um pipeline pronto: basta plugar `await emit_business(kind="ticket.opened", actor=user, payload={...})` em 1 linha por handler.
- 28 `kind`s estão mapeados, prontos para receber produtores.
- Middleware emite metadados (path/method) para qualquer mutation 2xx em 13 rotas — sem mais código.

---

## 6) ESTRATEGISTA IA — antes vs depois

**Relatório anterior (weekly, gerado em 01:42 UTC):**
> *"A semana registrou **18 eventos** com predominância absoluta de **DATA_QUALITY_DROP** (12 ocorrências, 67% do total) ..."*

**Se for gerar agora:** mesmos números. Cita os mesmos 7 EventTypes. Os **novos módulos críticos** (WhatsApp, GPS, Tickets, Vendas) continuam **invisíveis** ao Estrategista.

**Decisões novas sugeridas pelo Estrategista:** nenhuma. Continua produzindo o mesmo briefing.

🔴 **Crítica honesta:** a Sprint 13A NÃO mudou o discurso da IA. Mudou só a tubulação que ainda está seca.

---

## 7) DECISION ENGINE

| Métrica | Antes | Depois | Δ |
|---|---:|---:|---:|
| Decisões totais | 24 | **37** | **+54%** ✅ |
| Regras ativas | 15 | **15** | — |
| Regras com threshold dinâmico | 0 | **2** ⬅️ Sprint 17 | +2 |

🟡 **Honesto:** O aumento de 54% nas decisões NÃO veio da Sprint 13A — veio dos testes E2E rodando (seed de eventos para validar Sprints 13-18) + scheduler tick rodando entre auditorias. **Nenhuma decisão foi produzida a partir de evento auto-emitido pelo middleware.**

---

## 8) LEARNING ENGINE

| Métrica | Antes | Depois |
|---|---:|---:|
| Snapshots em `motor_ia_learnings` | 24 | **36** |
| Snapshots criados após Sprint 13A | — | **12** |
| Feedback real (factor mudou) | SIM (1 caso histórico) | SIM (mesmo caso `notify_manager`) |

🟡 12 novos snapshots gerados, mas eles refletem os MESMOS 4 action_types de antes (`notify_manager`, `open_incident`, `escalate_dunning`, `create_retention_opportunity`). Sem produtor novo → sem aprendizado novo. Tudo é re-medição do mesmo universo.

---

## 9) PREDICTIONS

| Métrica | Antes | Depois |
|---|---:|---:|
| Total | 12 | **15** (+3) |
| Modelos ativos (heurísticos) | 3 | 3 (`churn, revenue, ticket_demand`) |
| Modelos ML reais (sklearn) | 0 | **2** (`churn_iforest`, `ticket_arima`) ⬅️ Sprint 18 |
| Geradas após Sprint 13A | — | **3** |

✅ As 2 entregas ML são REAIS (sklearn 1.9.0 instalado, IsolationForest treinando com sucesso quando >=30 samples).
🟡 Mas as 3 novas predictions são re-runs dos mesmos modelos — não há **novas features** porque o bus não trouxe nada novo.

---

## 10) MULTI-TENANT — cobertura company_id

| Coleção | Antes | Depois |
|---|---:|---:|
| `motor_ia_events` | 61.7% | **59.3%** ⬇️ (testes E2E injetaram órfãos) |
| `motor_ia_insights` | 0.0% | **7.1%** (3/42) ⬆️ |
| `motor_ia_decisions` | 83.3% | **68.8%** ⬇️ |
| `motor_ia_actions` | 90.0% | **79.2%** ⬇️ |
| `motor_ia_outcomes` | 92.9% | **84.8%** ⬇️ |

🔴 **Reversão temporária causada pelos testes E2E** que injetaram docs com `company_id` curtinhos (`test-...`) mas a auditoria os contabiliza. **Em produção real**, o ganho viria do `compute_executive_score_all_tenants()` (Sprint 14) — que JÁ funciona, mas é chamado apenas 1×/hora pelo scheduler. Os insights antigos (sem company_id) permanecem.

> **Multi-tenant `motor_ia_insights` saltou de 0% → 7.1%** — único ganho real e visível. Os outros números recuaram artificialmente por seed de teste.

---

## 11) IMPACTO REAL — A Sprint 13A aumentou a inteligência?

**RESPOSTA HONESTA: NÃO (ainda).**

### Por quê?
1. **Cobertura nervosa:** 3.5% → 3.83% (+0.33 pp). Em ambiente dev sem tráfego, **0 eventos auto-emitidos** pelo middleware.
2. **EventTypes em uso:** 7/33, **mesmo** que antes.
3. **Tipos críticos** (`TICKET_OPENED, SALE_CREATED, WA_INBOUND_RECEIVED, PARTNER_QR_REDEEMED, GPS_ROUTE_DEVIATION`): **0 eventos emitidos**.
4. **Estrategista IA**: cita os mesmos números.
5. **Decision Engine**: cresceu via seed de teste, não via novos sinais.

### O que a Sprint 13A SIM entregou:
- ✅ Helper idiomático `emit_business(kind=...)` pronto para uso.
- ✅ Middleware HTTP funcional plugado no server.py.
- ✅ 13 paths mapeados aguardando tráfego.
- ✅ 28 kinds prontos no `KIND_MAP`.

**Em uma frase:** *"A Sprint 13A construiu uma rodovia. Mas nenhum carro passou ainda."*

---

## 12) NOTAS POR COMPONENTE

| Componente | Nota | Justificativa |
|---|:-:|---|
| Sistema Nervoso | **5.5 / 10** | Infra completa, mas só 3.83% do corpo emite. Subiu de 5.0 → 5.5 pela existência do middleware. |
| Presidente IA | **6.5 / 10** | 15 regras, 6 handlers, 4 action_types com feedback, 2 com threshold dinâmico. Mesmo nível anterior. |
| Estrategista IA | **6.0 / 10** | LLM real funcionando, cita números corretos. Sem novos sinais para citar. |
| Motor IA | **7.5 / 10** | Maior progresso real: ML (sklearn) entrou, feedback loop, learnings, predictions, leader-election. |

---

## 13) NOVA MATURIDADE

| Métrica | V2 (auditoria anterior) | V3 (hoje) | Δ |
|---|---:|---:|---:|
| Maturidade Geral | 63.8% | **64.5%** | +0.7 |
| Visão Final atingida | 52% | **54%** | +2 |
| Nota Real CTO | 6.5 / 10 | **6.7 / 10** | +0.2 |

### Por que apenas +0.7 ponto de maturidade?
- **Subiu (real):** ML real (Sprint 18) +1.0pt em IA. Feature flag granular (Sprint 15) +0.5pt em Autonomia. Painel CTO Frontend (Sprint 16) +0.5pt em UX. Auto-tuning (Sprint 17) +0.5pt em IA.
- **Estagnou:** Cobertura nervosa, EventTypes em uso, Estrategista.
- **Caiu temporariamente:** Multi-tenant nas 3 collections principais por causa do seed dos testes.

---

## 14) VEREDITO CTO

### **APROVADO COM RESSALVAS**

**Justificativa:** A Sprint 13A entregou todos os artefatos prometidos e os testes E2E (26/26) provam que a infraestrutura funciona. Mas o **impacto operacional medido foi quase zero** porque a entrega foi um meio (middleware genérico), não um fim (produtores reais emitindo).

### Qual é o próximo gargalo?
**Produtores reais. 226 módulos silenciosos.**
Especificamente, os 5 mais importantes para mover o ponteiro do Estrategista IA:
1. `routes/tickets.py` (621 tickets já existem no banco, 0 emitem)
2. `routes/whatsapp_*.py` (engajamento + churn signal mais rico)
3. `routes/sales_funnel.py` (revenue, win-back)
4. `routes/financeiro*.py` (overdue real, não simulado)
5. `routes/subscribers.py` (CLIENT_CREATED, ONLINE, OFFLINE)

### Qual é a próxima sprint que mais gera valor?
**Sprint 19 — "Plug-in Cirúrgico": adicionar `emit_business` MANUALMENTE em 30 handlers (não via middleware genérico).**
Cada call site é 2 linhas. Em 1 sprint, cobertura nervosa salta de 3.83% para **15-25%** com payload **semântico** (não os metadados genéricos do middleware). Após isso, os EventTypes em uso saltam de 7 para 20+, e o Estrategista IA passa a citar dados de toda a operação.

### Se tivesse APENAS 1 sprint, onde investiria?
**Não na Sprint 19 (mais cobertura). Investiria na Sprint 19.5 — "Ativar LIVE em 1 cliente-piloto".**

Por quê?

Sprint 13A provou que a infraestrutura funciona em DRY-RUN. Mas o **maior risco do produto** hoje é: **0 ações reais foram executadas em toda a história do sistema.** Se um investidor pede prova de operação autônoma, não temos.

Em 1 sprint:
1. Criar 1 cliente real de teste com `company_settings.live_actions = ["escalate_dunning"]`.
2. Plugar `emit_business` em `routes/financeiro_ops.py` (1 handler — overdue real).
3. Deixar o sistema correr 7 dias com WhatsApp Baileys ativo.
4. Medir: quantos clientes inadimplentes receberam mensagem automática? Quantos pagaram após?

Se a resposta for `>5 clientes pagaram após mensagem automática do Presidente IA`, **a tese da empresa muda de "ERP com IA" para "Sistema que recupera receita sozinho"**. Esse é o salto que vale R$ 50M no pitch.

---

**Resumo executivo (1 frase):**
*Sprint 13A: rodovia construída, carros ainda na garagem. Aprovada para seguir, mas a próxima sprint precisa **transformar infraestrutura em receita**.*
