# ☕ EXECUTIVE BRIEFING — CONTRATOS

> **Operação:** LIGO EXECUTIVE OS — Fase A · Etapa 1 · Doc 4/5
> **Data:** 14/06/2026
> **Status:** Documento normativo.
> **Princípio:** *Existem 3 arquivos com "briefing" no nome. Apenas 1 é briefing do CEO. Esse doc desambigua.*

---

## RESUMO EM 1 FRASE

```
presidente_ia_briefing.py   = BRIEFING DO CEO (Café com IA do CEO)
briefing_dispatcher.py      = TRANSPORTE (envio WhatsApp)
disparo_briefing.py         = CONTEXTO DE CAMPANHA (não é briefing — é prompt da Isabella)
```

---

## #1 — BRIEFING DO CEO

### `services/presidente_ia_briefing.py` (213 linhas)
**→ renomeação proposta na Etapa 3: `services/ceo_briefing.py`**

### 🎯 Função
**Único briefing executivo do CEO.** "Café com a IA do CEO" — texto curto que o gestor recebe ao acordar (08:00 BRT) com:
- Saúde corporativa em 1 linha (emoji + score)
- Top 1 risco do dia (R$ ou impacto operacional)
- Top 1 oportunidade do dia (R$)

### 📥 Lê de
- `services.presidente_ia.compute_corporate_health(cid)` → Health Score
- `services.presidente_ia.compute_risks(cid, health)` → riscos
- `services.presidente_ia.compute_opportunities(cid)` → oportunidades
- **(Fase B futura)** também consumirá `services.presidente_executive.build_executive_report(cid)` para a linha financeira em R$

### 📤 Saída
- `build_briefing_text(cid)` → texto curto (atualmente 2-3 linhas)
- `send_briefing(cid)` → orquestra `build_briefing_text` + chama `briefing_dispatcher.dispatch_briefing`

### 🤖 LLM?
**Hoje não.** Determinístico. Pode passar a usar LLM na Fase B se decidirmos sintetizar bullets.

### ⏰ Frequência
- **Diária às 08:00 BRT** via `conselho_ia_scheduler._worker_loop` quando `conselho_ia_settings.presidente_briefing_enabled=true`

### ✅ Quem aciona
- `services/conselho_ia_scheduler.py` (cron)
- `routes/presidente_ia.py::POST /briefing/test` (teste manual)
- `routes/presidente_ia.py::GET /briefing/preview` (preview sem envio)

### 🚫 Quem **NÃO** deve usar
- ❌ Pedir parecer LLM por papel (CEO/COO/...) — use `presidente_ia_conselho`
- ❌ Relatório longo formal — use `conselho_ia` (route)

### ⚠️ Risco
Hoje o briefing tem só 2-3 linhas. **Fase B vai expandir para 1 página** com seções obrigatórias (clientes, financeiro, atendimento, rede, comercial, universo, presidente IA). Esse arquivo precisará crescer; **continua sendo o único briefing do CEO**.

---

## #2 — TRANSPORTE WhatsApp

### `services/briefing_dispatcher.py` (87 linhas)
**→ renomeação proposta na Etapa 3: `services/ceo_briefing_dispatcher.py`**

### 🎯 Função
**Transporte apenas.** Pega o texto montado por `ceo_briefing` e envia via WhatsApp (Baileys). Se WA estiver bloqueado, persiste como simulação com status correto. **Não mente. Não mascara.**

### 📥 Lê
- Texto pronto recebido como argumento
- `services/transport_check` (verifica se canal WA está ativo)
- `services/wa_dispatcher` (envio efetivo)

### 📤 Saída
- WhatsApp message enviado (ou simulação registrada)
- Status: `sent | simulated | failed`

### 🤖 LLM?
**Não.**

### ⏰ Frequência
Sob demanda (chamado pelo briefing CEO ou outros disparos).

### ✅ Quem aciona
- `services/ceo_briefing.send_briefing`
- **(Fase B futura)** também enviará link curto para o painel "Café com o CEO" web

### 🚫 Quem **NÃO** deve usar
- ❌ Para enviar mensagens promocionais — use `services/sales_outreach`
- ❌ Para enviar mensagens a cliente final — use `services/wa_dispatcher` diretamente

---

## #3 — CONTEXTO DE CAMPANHA (NÃO É BRIEFING DO CEO)

### `services/disparo_briefing.py`
**→ renomeação proposta na Etapa 3: `services/disparo_campaign_context.py`**

### 🎯 Função real
**Injetor de contexto da campanha "Disparo IA" no system_prompt da Isabella.** Quando um cliente recebe mensagem de uma campanha Disparo IA e responde, a Isabella precisa do CONTEXTO da campanha (briefing, tom, objeções, KPIs). Esta função busca a campanha ativa mais recente para o telefone e devolve um bloco de texto para concatenar no system_prompt.

### 📥 Lê de
- Coleções de campanhas Disparo IA
- Janela de relevância: **14 dias** após o disparo

### 📤 Saída
- Bloco de texto (string) para injetar no system_prompt da Isabella
- Vazio se não houver campanha relevante

### 🤖 LLM?
**Não diretamente.** Alimenta o LLM que conversa (Isabella).

### ⏰ Frequência
Sob demanda (a cada inbound de WhatsApp).

### ✅ Quem aciona
- `services/isabella` (no monte do system_prompt antes de conversar)

### 🚫 Quem **NÃO** deve usar
- ❌ **NÃO é briefing do CEO.** Confusão original que motivou esta documentação.
- ❌ Não envia mensagem nenhuma — só compõe prompt.

### ⚠️ Risco
Nome do arquivo (`disparo_briefing.py`) é **ativamente enganoso**. Já causou confusão no Discovery. Renomeação na Etapa 3 elimina essa armadilha permanentemente.

---

## DESAMBIGUAÇÃO PERMANENTE

| Quando você ler... | Pense em... |
|---|---|
| "briefing do CEO" / "Café com IA do CEO" | `ceo_briefing.py` (ex-`presidente_ia_briefing.py`) |
| "briefing matinal do operador" | função dentro de `presidente_operator.py` (DIFERENTE do CEO) |
| "briefing da campanha" / "contexto de campanha" | `disparo_campaign_context.py` (ex-`disparo_briefing.py`) — **interno à Isabella** |
| "transporte WhatsApp" | `ceo_briefing_dispatcher.py` (ex-`briefing_dispatcher.py`) |

---

## CONTRATO DO CAFÉ COM O CEO (FASE B FUTURA)

> Estrutura proposta para quando expandirmos de 2-3 linhas → 1 página. **Não implementado nesta etapa.**

**Princípios:**
- 1 página, leitura em <3 minutos
- Sem gráficos pesados
- Sem widgets
- Todas as linhas com **call-to-action** quando aplicável (clica e abre painel)
- **Confiança declarada** em campos com dados ruins (NPS, referrals)

**Estrutura (das 7 seções do CTO):**
```
☕ CAFÉ COM O CEO · DD/MM
━━━━━━━━━━━━━━━━━━━━━━━━━━

CLIENTES
  ativos: N | novos 7d: N | cancel. 7d: N | saldo: +/-N | evolução 30d: +/-N

FINANCEIRO        (vem de revenue_realization.py)
  receita ontem: R$ X | mês: R$ X | inadimplência: X% | previsão 30d: R$ X

ATENDIMENTO       (vem de aihub_wa_messages + isabella_queue)
  Isabella: N convs | auto-resol: X% | transferências: N | irritados: N
  TMA: Xm Ys

REDE              (vem de isabella_incidents + network_outages)
  incidentes: N | bairros afetados: N | CTOs críticas: N | capacidade: X%

COMERCIAL         (vem de revenue_agent + isabella_opportunities)
  vendas 7d: N | conversões: X% | indicações: INDISPONÍVEL | oportunidades: N

UNIVERSO LIGO     (vem de universo_ligo_invites)
  fundadores: N APTO | embaixadores: N | invisíveis cuidados 7d: N | convites pendentes: N

PRESIDENTE IA     (vem de presidente_ia.compute_risks/opportunities)
  ⚠ alerta: ...
  💡 oportunidade: ...
  🛡️ risco: ...
```

---

## DECISÕES TOMADAS POR ESTE DOC

1. ✅ **Apenas 1 briefing do CEO** (`ceo_briefing.py`).
2. ✅ **`disparo_briefing.py` renomeado** para `disparo_campaign_context.py` — elimina ambiguidade permanentemente.
3. ✅ **`briefing_dispatcher` renomeado** para `ceo_briefing_dispatcher.py` — fica claro que é só do CEO.
4. ✅ **CEO Briefing chama exatamente 4 fontes:**
   - `presidente_ia` (risco / oportunidade / Health interno)
   - `presidente_executive` (linha financeira monetizada)
   - `revenue_realization` (linha "Faturou no mês")
   - `revenue_agent` (linha "Por agente")
5. ✅ **Briefing matinal do operador (dentro de `presidente_operator`)** existe e é **diferente** do Café com o CEO. Não confundir.

## DÚVIDAS EM ABERTO

| # | Dúvida | Quem decide |
|---|---|---|
| D1 | Canal único ou duplo (WhatsApp + painel web)? CTO já respondeu **ambos**. | Implementação na Fase B |
| D2 | LLM no `ceo_briefing` para refinar tom? Ou determinístico para garantir reprodutibilidade? | Decisão na Fase B |
| D3 | Briefing matinal do operador (`presidente_operator`) deve ser **silenciado** ou continuar como sinal interno separado? | Decisão pós-Fase A |
