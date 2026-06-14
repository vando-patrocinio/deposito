# 📋 FASE A · ETAPA 1 — RESUMO EXECUTIVO

> **Operação:** LIGO EXECUTIVE OS — Fase A · Etapa 1 (Documentação ANTES de Código)
> **Data:** 14/06/2026
> **Status:** ✅ 5 documentos entregues. ⛔ ZERO código alterado. ⛔ ZERO collection tocada.

---

## 📎 OS 5 DOCUMENTOS ENTREGUES

```
/app/memory/
├── EXECUTIVE_OS_CONTRACTS.md          ← Os 4 Presidentes como camadas
├── EXECUTIVE_COUNCILS_CONTRACTS.md    ← Os 3 Conselhos como hierarquia + 5 do CTO
├── EXECUTIVE_REVENUE_CONTRACTS.md     ← Os 5 motores de receita + fonte única
├── EXECUTIVE_BRIEFING_CONTRACTS.md    ← Os 3 "briefings" desambiguados
└── PERSONAS_GOVERNANCE.md             ← Pamela/Camila/Leo como personas
```

---

## ✅ DECISÕES TOMADAS (UMA VERDADE POR PERGUNTA)

| Pergunta | Resposta única |
|---|---|
| **"Quanto a Ligo faturou?"** | `revenue_realization` (ex-`real_revenue.py`) → lê `subscriber_invoices` |
| **"Quanto cada agente gerou?"** | `revenue_agent` (ex-`agent_revenue.py`) → lê `motor_ia_revenue_attribution` |
| **"Onde registramos cada outcome?"** | `revenue_attribution.py` (único escritor) |
| **"Quais oportunidades estão abertas?"** | `isabella_opportunities_revenue` (ex-`isabella_revenue.py`) |
| **"Qual é a Saúde corporativa interna?"** | `presidente_ia.compute_corporate_health` — Health Score 0-100 |
| **"Qual é a saúde monetizada?"** | `presidente_executive.build_executive_report` — Executive Score R$ |
| **"E se rodarmos ação X?"** | `presidente_brain` — simulação V12-V14 |
| **"Executar ação operacional?"** | `presidente_operator` — Matriz Autonomia 4 níveis |
| **"Quem orquestra o relatório diário?"** | `routes/conselho_ia.py` (Nível 2) |
| **"Quem produz a ata raw dos Commanders?"** | `services/isabella_conselho.py` (Nível 1) |
| **"Quem dá parecer LLM por cadeira (CEO/COO/CTO/CFO/CPO)?"** | `services/presidente_ia_conselho.py` (Nível 3, sob demanda) |
| **"Quem manda o Café com o CEO?"** | `ceo_briefing` (ex-`presidente_ia_briefing.py`) + `ceo_briefing_dispatcher` |
| **"O que é disparo_briefing.py?"** | É **contexto de campanha para Isabella**, NÃO briefing do CEO. Renomeia para `disparo_campaign_context`. |
| **"Pâmela é agente?"** | NÃO. É persona — voz de relacionamento. Sem código, sem decisão. |
| **"Camila é agente?"** | NÃO. É persona — voz comercial. Sem código, sem decisão. |

---

## 🏛️ CONTRATOS DEFINIDOS

### 4 Presidentes → 4 camadas com escopo único
1. `presidente_ia` = memória / visão (motor_ia_*)
2. `presidente_executive` = financeiro / R$ (8 blocos)
3. `presidente_brain` = simulação / cenários (V12-V14)
4. `presidente_operator` = execução / ações (Matriz Autonomia)

### 3 Conselhos → hierarquia pirâmide
1. `isabella_conselho` = ata raw (input)
2. `conselho_ia` (route) = orquestrador → **abriga os 5 do CTO como subseções**
3. `presidente_ia_conselho` = parecer LLM sob demanda

### 5 Conselhos do CTO → blocos no orquestrador (NÃO módulos novos)
- **Comercial** ("Como vender mais?") — assina Camila, computa `revenue_agent` + `isabella_opportunities_revenue`
- **Operacional** ("Onde estamos falhando?") — assina Álvaro, computa `alvaro_v5` + `isabella_incident`
- **Financeiro** ("Onde perdemos dinheiro?") — assina Pâmela, computa `revenue_realization` + `isabella_dunning`
- **Produto** ("O que clientes querem?") — assina Isabella, computa `motor_ia_intel` + `nps_responses_mvp`
- **Universo Ligo** ("Estamos criando pertencimento?") — assina Pâmela, computa `universo_ligo_curadoria`

### 5 Motores de Receita → 5 funções complementares, 1 coleção
- `revenue_realization` (Camada 1 — quanto faturou)
- `revenue_agent` (Camada 2 — quanto cada agente)
- `revenue_attribution` (Camada 3 — escrita única)
- `isabella_opportunities_revenue` (Camada 4 — detector)
- `v7_2_revenue` (utilitário — vai virar parte do `revenue_attribution`)
- Coleção única de atribuição: **`motor_ia_revenue_attribution`**

### 3 "Briefings" → 1 do CEO + 1 transporte + 1 contexto de campanha
- `ceo_briefing` (ex-`presidente_ia_briefing`) = ÚNICO briefing do CEO
- `ceo_briefing_dispatcher` (ex-`briefing_dispatcher`) = transporte WhatsApp
- `disparo_campaign_context` (ex-`disparo_briefing`) = injetor de prompt da Isabella, NÃO é briefing do CEO

### Pamela / Camila / Leo → declaradas PERSONAS oficialmente
- Persona = voz, identidade de marca, assinatura.
- **NÃO** tomam decisões autônomas
- **PODEM** assinar Conselhos e Briefings
- Painéis devem mostrar badge "Persona" ao lado dos nomes

---

## ❓ DÚVIDAS EM ABERTO (consolidadas dos 5 docs)

| # | Doc | Dúvida | Quem decide / quando |
|---|---|---|---|
| 1 | OS | `presidente_brain` (simulação) entra no Café com CEO como "previsão" ou "recomendação"? | CTO na Fase B |
| 2 | OS | Operador deve sugerir ações no Café com CEO ou só no painel próprio? | CTO na Fase B |
| 3 | OS | Pasta dedicada `services/presidente/` (move arquivos)? | Pós-Fase A |
| 4 | Councils | Conselhos sempre exibidos ou só quando houver "algo a dizer"? | CTO na Fase C |
| 5 | Councils | Quem é responsável editorial (humano revisa) do relatório antes do CEO? | CTO na Fase B |
| 6 | Councils | Parecer LLM (Nível 3) sob demanda ou 1x/semana? | Pós-Fase A |
| 7 | Revenue | `executive_ledger` após tag continua sendo fonte primária de algum cálculo? | Auditoria na Etapa 3 |
| 8 | Revenue | "Receita protegida" precisa ground-truth — como auditar? | CTO na Fase B |
| 9 | Revenue | Tolerância do `test_one_truth` — confirma ±2%? | CTO confirma agora |
| 10 | Briefing | LLM no `ceo_briefing` para refinar tom, ou determinístico? | CTO na Fase B |
| 11 | Briefing | Briefing matinal do operador (dentro de `presidente_operator`) silenciado ou mantido como sinal interno? | Pós-Fase A |
| 12 | Personas | Owner editorial oficial de Pâmela e Camila — Atendimento e Comercial respectivamente? | CTO + lideranças áreas |
| 13 | Personas | Auditoria de prompts versionados — quem versiona, onde fica, como rollback? | Pós-Fase A |

---

## 🎯 IMPACTO ESPERADO

### Imediato (apenas com docs, sem código)
- ✅ Time técnico entende **quem responde o quê** (5 perguntas críticas têm uma única resposta)
- ✅ Code review pode rejeitar PR que **duplique cálculo de Health Score, Executive Score ou Receita do mês**
- ✅ Board entende que **Pâmela/Camila são personas** (sem mais promessa de "vendedor IA dedicado")
- ✅ Discovery encerrado: ninguém mais perde 2h descobrindo a diferença entre 4 Presidentes

### Pós-Etapa 3 (renomes + tags)
- ✅ Arquivos refletem o que fazem (`disparo_briefing.py` deixa de mentir)
- ✅ `executive_ledger` parou de inflar dashboards (tag pre_sanitize_2026_06_14)
- ✅ Teste `test_one_truth` valida convergência ±2% entre 3 fontes de receita

### Longo prazo (Fases B+)
- ✅ Café com o CEO de 1 página com **dados confiáveis** (única verdade já consolidada)
- ✅ 5 Conselhos do CTO produzem valor sem competir entre si
- ✅ Auditoria de qualquer decisão executiva é **rastreável em 1 hop** (briefing → camada → coleção primária)

---

## ⚠️ RISCOS DE SEGUIR PARA CÓDIGO (Etapa 3)

| # | Risco | Severidade | Mitigação |
|---|---|---|---|
| R1 | Renomeação de 6 arquivos quebra ~30 imports em outros módulos | 🟡 MÉDIO | Stubs por 30d (já autorizado em Q-A2) |
| R2 | Header normativo adicionado em 15 arquivos não é lido por ninguém | 🟢 BAIXO | Adicionar ao guia de onboarding interno |
| R3 | Tag `pre_sanitize_2026_06_14` em `executive_ledger` quebra queries antigas que não filtram | 🟡 MÉDIO | Adicionar campo (não remover linha) — queries sem filtro continuam vendo dados |
| R4 | Teste `test_one_truth` falha → significa que ainda há divergência → **bom**, indica que precisamos consertar antes da Fase B | 🟢 BAIXO | É um sinal, não um bug |
| R5 | Renomes confundem ferramentas de log/observabilidade externas (Sentry, Datadog) | 🟢 BAIXO | Stubs mantêm caminhos antigos funcionando |
| R6 | Pâmela/Camila ganham badge "Persona" em painéis → algum stakeholder reage mal | 🟡 MÉDIO | Comunicar antes: "persona não é menos importante; é a VOZ" |

---

## ✅ CRITÉRIO DE ACEITE — ETAPA 1

- [x] 5 documentos existem em `/app/memory/`
- [x] Nenhum código foi alterado
- [x] Nenhuma collection foi alterada
- [x] Nenhum dado foi tagueado
- [x] Cada uma das perguntas críticas tem uma resposta única documentada:
  - "Quem responde receita?" → `revenue_realization`
  - "Quem responde conselho?" → `conselho_ia` (orquestrador) + 3 níveis
  - "Quem responde briefing?" → `ceo_briefing`

---

## 🚦 PRÓXIMO PASSO

CTO, **revisar os 5 documentos** nominalmente. Quando autorizar, executamos **Etapa 3**:

1. Headers normativos em 15 arquivos
2. Renomes com stubs de 30 dias:
   - `presidente_ia_briefing` → `ceo_briefing`
   - `briefing_dispatcher` → `ceo_briefing_dispatcher`
   - `disparo_briefing` → `disparo_campaign_context`
   - `agent_revenue` → `revenue_agent`
   - `real_revenue` → `revenue_realization`
   - `isabella_revenue` → `isabella_opportunities_revenue`
3. `v7_2_revenue` vira utility de `revenue_attribution` (stub)
4. Archive 3 collections vazias (`presidente_ledger`, `briefing_executive`, `agent_revenue_events`)
5. Tag `pre_sanitize_2026_06_14=true` em sintéticos do `executive_ledger`
6. Teste `tests/test_phase_a_consolidation.py::test_one_truth`
7. Rollback documentado e testado

**Tolerância proposta no teste:** convergência ±2% entre `revenue_realization.month_total`, `revenue_agent.total_by_period` e `GET /api/dashboard/revenue/month`. ✅ Confirma?

---

⛔ **NADA FOI MODIFICADO NO BACKEND ATÉ ESTE PONTO.** Aguardo aprovação dos 5 docs antes de prosseguir.
