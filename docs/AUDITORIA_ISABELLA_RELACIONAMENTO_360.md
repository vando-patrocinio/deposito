# 🔥 AUDITORIA CRÍTICA — ISABELLA RELACIONAMENTO 360°
**Data:** 2026-02-10 (banco: produção/preview real)

> Não é arquitetura. Não é promessa. É evidência crua do MongoDB.

---

## 📊 RESPOSTAS DIRETAS — ANTES DA INTERVENÇÃO

| # | Pergunta | Resposta REAL | Evidência |
|---|---|---|---|
| 1 | Clientes atendidos/dia | **4,8** clientes únicos/dia (30d), 58 total | `aihub_wa_messages` distinct phone (sem outlier 5521998176526) |
| 2 | Follow-ups | **ZERO** (ai_evaluations kind=FOLLOWUP = 0) | `ai_evaluations.kind` distinct: só OS_LEARNING(1), SHORT_TERM_MEMORY(10), TECHNICIAN_SCORE(0) |
| 3 | Propostas Universo Ligo (30d) | **4 phones** receberam (0,13/dia) | Regex `playhub\|ligo security\|ligo móvel\|combo` em outbound |
| 4 | Vendas | **0** vendas registradas (`SALE`/`CROSS_SELL` inexistentes no ledger) | `executive_ledger.kind` — só eventos operacionais |
| 5 | Cancelamentos (30d) | **1** menção, **0** tickets type=cancel | `aihub_wa_messages` regex + `tickets.type` |
| 6 | Satisfação (NPS) | NPS médio **6,01** — **15.092 detratores vs 0 promotores** (15.295 evals; **15.200 SÃO BACKFILL SINTÉTICO**) | `ai_evaluations.nps_inferido` + `backfill_outbound_id` ≠ null |
| 7 | Reabertura ≤30d | **453 subscribers** com >1 ticket em 60d (top 4 tickets cada) | `tickets` group by subscriber_id |

---

## 🚨 SMOKING GUNS — GARGALOS REAIS

### G1. **Config WhatsApp aponta pra agente ERRADO**
```
aihub_settings.whatsapp_auto_reply (co-demo):
  agent_name: "Jerusa"   ← agente de VOZ/telefone (gpt-4o-mini)
  enabled: True
```
Jerusa é de voz/WebRTC. Mas tá configurada como respondedor do WhatsApp.

### G2. **Roteador devolve "Camila" no fallback**
`pick_agent_for_message("co-demo", phone, "oi fatura")` → **Camila** (3º agente).
- Razão: nenhum agente tem `routing_intent` preenchido → score=0 → fallback usa `agents[0]` da lista (Camila vem antes na ordem de criação).
- Isabella é o agente correto pra atendimento premium, mas o roteador nem chega nela.

### G3. **Company `co-id-auto` SEM auto_reply configurado**
Cliente `5511990000004` mandou:
```
[03:49] "meu cpf é 123.456.789-09"
[03:49] "ainda nao desbloqueou"
```
SEM resposta. `aihub_settings.whatsapp_auto_reply` não existe pra `co-id-auto`.

### G4. **Conversa unilateral de 58 mensagens**
Phone `5521969294397-1516311488` (grupo) mandou **58 mensagens** em 7d, **zero resposta** da Isabella. Provável grupo WhatsApp ignorado (correto operacionalmente).

### G5. **Outlier teste poluindo todas as métricas**
`5521998176526` tem **41.974 msgs** (26.805 inbound + 15.147 outbound). É bot/teste. 15.200 entradas em `ai_evaluations` foram BACKFILL desse phone — distorcem NPS, vendas, etc.

### G6. **`ai_evaluations` real PARADO**
- Backfill criou 15.200 evals históricos com `outcomes` artificiais (TODOS marcando `vendeu=true, resolveu=false, NPS=6`).
- **Em 30d reais: 1 OS_LEARNING + 10 SHORT_TERM_MEMORY + 0 TECHNICIAN_SCORE = 11 evals**.
- Pipeline de `register_followup` (Operação Atribuição Automática) parou de gravar OUTCOMES em outbound real.

### G7. **`isabella_queue` worker VIVO, mas só processou outlier**
14.973 jobs processados, **todos antes do reset da consulta** (status=done). A última job é de **02:40 hoje** — então worker tá rodando. Mas processou só o phone outlier (5521998176526).

### G8. **Reincidência sem reabertura proativa**
453 subscribers com 2-4 tickets do tipo `lentidão`/`sem internet`/`ONU offline` em 60d. Nenhuma das Operações anteriores está agendando contato proativo pra esses casos. `OS_NO_RETURN_30D: 72` no ledger só REGISTRA o sucesso quando o cliente NÃO voltou — não há contraponto que ataca quem voltou.

### G9. **Cross-sell Universo Ligo ausente**
Apenas **4 mensagens** da Isabella mencionaram PlayHub/Ligo Security/Móvel/Combo em 30 dias. Phone `5511990099999` recebeu "Aproveitando, quer conhecer o PlayHub?" no escuro. Sem gatilho contextual.

---

## 🎯 PLANO DE ATAQUE (fixes em ordem de impacto)

| # | Fix | Gargalo atacado | Custo |
|---|---|---|---|
| F1 | Setar `whatsapp_auto_reply.agent_name="Isabella"` em todas companies com tráfego | G1, G3 | 1 update |
| F2 | Passar `default_agent=Isabella` em pick_agent_for_message no twilio handler | G2 | 1 linha |
| F3 | Implementar `register_isabella_outcome` que grava ai_evaluations REAL a cada outbound auto_reply (extrai outcomes + NPS inferido + acompanhamento) | G6 | service novo |
| F4 | Implementar `followup_scheduler` — quando outcome `acompanhamento=true` ou cliente reincidente em <30d, agenda mensagem de follow-up (24h/48h/7d) | G2, G8 | service + worker |
| F5 | Implementar `relationship_memory` — bloco no system prompt com "última conversa" / "último problema" / "VIP score" | G6 | service novo |
| F6 | Implementar `universo_ligo_pitch_contextual` — depois de outcome=resolveu + NPS≥8, propõe próximo passo do Universo Ligo via marker | G9 | service novo |
| F7 | Implementar `encerramento_humanizado` — quando detecta sinal de fim ("obrigado", "valeu", "blz"), envia mensagem de despedida + sondagem NPS direta | G6 | service novo |
| F8 | Implementar `case_reopener` — reabre OS automaticamente quando subscriber reabre chamado do mesmo tipo em <30d | G8 | service novo |
| F9 | Job de purge/quarantine pro outlier 5521998176526 (marca como `is_test=true`, exclui de métricas) | G5 | 1 update |

---

## 🔢 DEPOIS — ALVOS

| Métrica | Antes (real, 30d, sem outlier) | Meta após fixes |
|---|---|---|
| Conversas com resposta auto-reply | 1/5 = 20% | ≥95% |
| Follow-ups agendados | 0 | ≥1 por conversa qualificada |
| Outcomes registrados em ai_evaluations | 11 reais | 1 por outbound (≈ 134/30d) |
| Propostas Universo Ligo contextuais | 4 phones | ≥10% das conversas com resolução |
| Reabertura proativa (OS reincidente) | 0 | 453 → todos com case_reopener acionado |
| Sondagens NPS pós-atendimento | 0 | 1 por encerramento detectado |
