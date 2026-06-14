# 🧹 FASE A — CONSOLIDAÇÃO EXECUTIVA

> **Operação:** LIGO EXECUTIVE OS — Fase A (Consolidação)
> **Data:** 14/06/2026
> **Modo:** CTO — Discovery + Proposta + Risco + Rollback
> **Status:** 🚫 ZERO código alterado. Aguardando autorização para iniciar fusões.
> **Princípio:** "Uma empresa. Uma verdade. Um briefing."

---

## 🎯 OBJETIVO DA FASE A

Eliminar a **fragmentação de verdade executiva** descoberta no Discovery:
- 4 Presidentes IA
- 3 Conselhos
- 5 motores de receita
- 3 "briefings"
- 4 collections vazias/duplicadas

Resultado esperado: **1 Presidente · 1 Conselho · 1 Receita · 1 Briefing** com responsáveis nominais claros, contrato de saída único, e plano de rollback testado.

---

## 1️⃣ MAPA DOS 4 PRESIDENTES IA

> 🟢 **CONCLUSÃO IMPORTANTE:** **NÃO são 4 verdades concorrentes.** São **4 camadas distintas** que ninguém documentou. O risco real é de **divergência futura** se não definirmos contratos.

| # | Arquivo | Linhas | Papel real (lido do header) | Coleções/dados | LLM? |
|---|---|---:|---|---|---|
| 1 | `services/presidente_ia.py` | 660 | **Núcleo de memória corporativa.** "OBSERVA → ENTENDE → CORRELACIONA → PREVÊ → DECIDE → AGE → APRENDE". Apenas agrega dados e mantém memória. | `motor_ia_events/memory/insights/predictions/decisions/actions/learnings` | ❌ não chama LLM |
| 2 | `services/presidente_executive.py` | 884 | **Camada de monetização.** Saída: 8 blocos em R$ — president_score, riscos, oportunidades, previsao_30d, dinheiro_em_risco, dinheiro_recuperavel, surpresas, ações. | `subscribers`, `smartolt_onus`, `tickets`, `network_outages`, `ctos`, `contracts/invoices`, `sales_leads`, `referrals` | ❌ heurística determinística |
| 3 | `services/presidente_brain.py` | 521 | **V12+V13+V14: Causality Engine + Digital Twin + Autopilot Simulation.** Read-only sobre dados de outros módulos. | `corporate_goals` + simulação | ❌ read-only |
| 4 | `services/presidente_operator.py` | 1.033 | **Executor operacional.** 3 motores (Oportunidades / Economia / Recuperação) + Matriz de Autonomia 4 níveis + Briefing matinal (6 perguntas) + execução. | `motor_ia_actions`, `corporate_goals`, `executor_ia` | ❌ chama executor |

### Dependência cruzada (de quem importa quem)

```
routes/presidente_ia.py
    ├─ services/presidente_ia_briefing.py
    │      └─ services/presidente_ia            (compute_corporate_health, compute_risks, compute_opportunities)
    └─ services/presidente_executive.py         (build_executive_report)

services/secretaria_tools.py
    └─ services/presidente_ia                   (5 funções de saúde/risco/oportunidade)

services/executor_ia.py
    └─ services/presidente_executive.py         (build_executive_report)

services/score_recovery.py                      → presidente_executive (3 chamadas)
services/governador_ia.py                       → presidente_executive (2 chamadas)
services/presidente_evolution.py                → presidente_executive
services/presidente_brain.py                    → presidente_executive  (intra-família)
services/presidente_cash.py                     → presidente_operator   (company_value × 2)
```

### O que falta para "uma verdade" mesmo nestes 4

| Risco | Probabilidade hoje | Mitigação proposta |
|---|---|---|
| Métrica "Saúde corporativa" calculada diferente em cada lugar | **MÉDIA** — `presidente_ia.compute_corporate_health` é importada por 5 lugares (centralizada), mas `presidente_executive.build_executive_report` calcula `president_score` separado | Documentar no header: **Health Score vem do presidente_ia. Executive Score vem do presidente_executive (são DIFERENTES e propositais).** |
| "Riscos" / "oportunidades" — origem confusa | **ALTA** — `presidente_ia` e `presidente_executive` ambos geram riscos+oportunidades, com regras distintas | Definir um único endpoint público (`presidente_ia`) que delega para os 3 outros como módulos internos |
| Nomes ambíguos | **ALTA** — "Presidente" significa coisas diferentes em cada arquivo | **Renomear conceitualmente** (não os arquivos): `presidente_ia` = `presidente_observability`, `presidente_executive` = `presidente_monetization`, `presidente_brain` = `presidente_simulation`, `presidente_operator` = `presidente_execution` |

### Decisão proposta: **MANTER os 4, FORMALIZAR contratos**

Estes 4 arquivos NÃO devem ser fundidos — cada um tem 500-1.000 linhas com escopo bem definido. Mas precisam de **contratos públicos explícitos** no header e um **README de família**.

---

## 2️⃣ MAPA DOS 3 CONSELHOS

| # | Arquivo | Linhas | Papel | Saída | LLM? | Cron |
|---|---|---:|---|---|---|---|
| 1 | `services/isabella_conselho.py` | 224 | **Ata diária dos Commanders** (Churn + Dunning + Revenue + Twin + Expansion). Convergência das oportunidades + riscos. | `isabella_council_minutes` | ❌ agregação | rodando |
| 2 | `services/presidente_ia_conselho.py` | 235 | **Pareceres especializados das 6 cadeiras** (CEO/COO/CTO/CFO/CPO + Estrategista) via Claude Sonnet 4.6. | cache em memória por (cid, role) 60min | ✅ LLM | sob demanda |
| 3 | `routes/conselho_ia.py` | 1.362 | **Endpoint configurável** com auditor IA + agent loop (executa tools como `flag_dunning`). Coleta de overview/network/technicians/atendimento/sales/universo/protege. | `conselho_ia_reports` (1 doc co-demo) + `conselho_ia_settings` | ✅ LLM (`_ai_brief`) | cron 08:00 BRT |

### Comparação lado a lado

| Dimensão | isabella_conselho | presidente_ia_conselho | conselho_ia |
|---|---|---|---|
| **O que produz** | Ata consolidada de Commanders | 6 pareceres CEO/COO/CTO/CFO/CPO/Estrateg | Relatório executivo configurável |
| **Persiste em** | `isabella_council_minutes` | cache 60min in-memory | `conselho_ia_reports` |
| **Lê de** | `isabella_commander_opportunities` + `isabella_incidents` | dashboard do `presidente_ia` | 7 collectors (overview, network, tech, atend, sales, universo, protege) |
| **Usa LLM** | Não | Sim (cara) | Sim |
| **Tom** | Operacional | Estratégico (executivo sênior) | Executivo geral |
| **Frequência** | Diária | Sob demanda | Diária (cron) |
| **Sobreposição com outros** | Alta com #3 (ambos diários) | Baixa (LLM puro) | Alta com #1 (ambos diários) |

### Decisão proposta: **MANTER 3 NÍVEIS, REDEFINIR HIERARQUIA**

- **Camada 1 (raw data):** `isabella_conselho.py` — ata operacional dos Commanders. **Mantém.**
- **Camada 2 (relatório):** `conselho_ia.py` (rota) — relatório executivo configurável que **agora consome** ata da Camada 1. **Mantém.**
- **Camada 3 (parecer humano):** `presidente_ia_conselho.py` — pareceres LLM por papel, **acionados sob demanda** (não diariamente). **Mantém + renomeia como "Pareceres Executivos"** para deixar claro que NÃO é ata.

**Os 5 Conselhos do CTO (Comercial/Operacional/Financeiro/Produto/Universo Ligo)** entrariam como **subseções** do `conselho_ia.py::generate_report` (Camada 2), não como módulos separados. Cada subseção lê de provedores específicos.

---

## 3️⃣ MAPA DOS 5 MOTORES DE RECEITA

> 🟢 **CONCLUSÃO:** **NÃO são 5 receitas concorrentes.** São **5 funções complementares** que precisam de header documentando isso.

| # | Arquivo | Linhas | O que faz | Saída |
|---|---|---:|---|---|
| 1 | `services/agent_revenue.py` | 452 | **Receita atribuída a cada agente IA** (Isabella/Pamela/Vendas/Álvaro). 3 métricas: Receita Gerada, Receita Protegida, Economia. | API JSON por agente |
| 2 | `services/real_revenue.py` | ~? | **Estimado / Confirmado / Recebido.** Separa projeção de realização. Prioriza ações por ROI Score. | objeto V6.2 |
| 3 | `services/v7_2_revenue.py` | ~? | **Fix Action→Cash.** Resolve 4 bugs de join (outcomes sem subscriber_id, prefixo ATLAZ em external_code, etc). Não é "receita" — é **engine de matching**. | `_ext_candidates`, joins |
| 4 | `services/revenue_attribution.py` | ~? | **Persistência.** Cada outcome financeiro é gravado em `motor_ia_revenue_attribution` com kind (recovered/generated/churn_prevented/cost_saved). Apenas escrita. | `motor_ia_revenue_attribution` insert |
| 5 | `services/isabella_revenue.py` | ~? | **Detector ativo de oportunidades.** Mapeia upgrades pendentes, add-ons potenciais, reativações de cancelados. **Não calcula receita realizada** — gera oportunidades para humano acionar. | `isabella_commander_opportunities` |

### Sobreposição real

```
        recovered  generated  churn_prevented  cost_saved  oportunidade  detector
agent_revenue.py         ✓        ✓              ✓             ✓
real_revenue.py          ✓        ✓                           ✓
v7_2_revenue.py                                                          ✓ (joins)
revenue_attribution.py   ✓        ✓              ✓             ✓
isabella_revenue.py                                                      ✓                  ✓
```

**Sobreposição clara:** `agent_revenue.py` e `real_revenue.py` calculam métricas similares em pontos de vista diferentes (por agente vs. por momento). **Mas usam fontes diferentes**:
- `agent_revenue` lê de `motor_ia_revenue_attribution` + `executive_ledger` + `motor_ia_actions`
- `real_revenue` lê de `subscriber_invoices` + previsões

→ **Risco real:** "Quanto a Ligo faturou no mês?" pode dar números diferentes nos dois.

### Decisão proposta: **CONSOLIDAR EM 2 ARQUIVOS**

| Antes | Depois | Justificativa |
|---|---|---|
| `agent_revenue.py` | **`revenue_agent.py`** (renomeado, sem fusão) | Receita POR AGENTE — ponto de vista de IA. Única fonte para "quanto Isabella gerou". |
| `real_revenue.py` | **`revenue_realization.py`** (renomeado, sem fusão) | Receita REAL realizada — ponto de vista financeiro. Única fonte para "quanto a empresa faturou". |
| `v7_2_revenue.py` | **internalizar dentro de `revenue_attribution.py`** | É código de matching/join, não de receita. Não merece arquivo próprio. |
| `revenue_attribution.py` | mantém | Persistência única (escrita). |
| `isabella_revenue.py` | **renomear para `isabella_opportunities_revenue.py`** | Fica claro que é detector, não calculadora. |

**Princípio:** dois ARQUIVOS DE LEITURA (`revenue_agent`, `revenue_realization`) + 1 escritor (`revenue_attribution`) + 1 detector (`isabella_opportunities_revenue`). Tudo escreve em `motor_ia_revenue_attribution` (ÚNICA collection de atribuição).

---

## 4️⃣ MAPA DOS 3 "BRIEFINGS"

> 🚨 **DESCOBERTA CRÍTICA:** **`disparo_briefing.py` NÃO é briefing do CEO.** É injetor de contexto da campanha "Disparo IA" no system_prompt da Isabella. Nome confuso causou ruído no Discovery anterior.

| # | Arquivo | Linhas | O que **REALMENTE** faz |
|---|---|---:|---|
| 1 | `services/presidente_ia_briefing.py` | 213 | **Único briefing executivo real.** "Café com a IA do CEO" — texto 2-3 linhas via WhatsApp ao gestor, com top risco + top oportunidade. Hook do `conselho_ia_scheduler`. |
| 2 | `services/briefing_dispatcher.py` | 87 | **Transporte WhatsApp.** Pega o texto montado e envia via Baileys (ou simula se WA bloqueado). NÃO gera conteúdo. |
| 3 | `services/disparo_briefing.py` | ~? | **Não é briefing do CEO.** Briefing **da campanha Disparo IA** injetado no prompt da Isabella quando cliente responde. |

### Decisão proposta: **RENOMEAR + MANTER**

| Antes | Depois | Justificativa |
|---|---|---|
| `presidente_ia_briefing.py` | **`ceo_briefing.py`** | Nome reflete o que é. |
| `briefing_dispatcher.py` | **`ceo_briefing_dispatcher.py`** | Idem. |
| `disparo_briefing.py` | **`disparo_campaign_context.py`** | Não é briefing. É contexto da Isabella. |

Sem fusão. Sem deleção. Apenas **renomes** para eliminar a ambiguidade.

---

## 5️⃣ DUPLICIDADES DE COLLECTIONS

| Collection | Docs co-demo | Docs total | % sintético | Decisão |
|---|---:|---:|---:|---|
| `executive_ledger` | 16 | 2.351 | **99,3%** 🚨 | **Marcar docs sintéticos com `pre_sanitize_2026_06_14=true`**, manter histórico para debug. Não usar para briefing. |
| `presidente_ledger` | 0 | 0 | — | **Drop.** Collection nunca foi usada. |
| `briefing_executive` | 0 | 0 | — | **Drop.** Collection nunca foi usada. |
| `agent_revenue_events` | 0 | 0 | — | **Drop.** Collection nunca foi usada. |

### Riscos da limpeza
- Algum código pode tentar inserir em `presidente_ledger` ou `briefing_executive` e falhar silenciosamente. **Mitigação:** grep antes de drop.

---

## 6️⃣ DESCOBERTA DE PAMELA E CAMILA (Q3 do CTO)

> ✅ **CONFIRMADO:** **Não existem como agentes próprios.**

### Evidência

```bash
$ grep -lE "(pamela_|camila_|class Pamela|class Camila)" services/ routes/
services/agent_bus.py            # menção em prompt de bus
services/prompt_loader.py        # carrega prompts por nome
routes/neo_reports.py            # menção em config
routes/neo_chat.py               # menção em config
```

- ❌ Não há `services/pamela_*.py`, `services/camila_*.py`
- ❌ Não há `routes/pamela_*.py`, `routes/camila_*.py`
- ❌ Não há collection `pamela_*` ou `camila_*`
- ✅ `services/agent_revenue.py` atribui receita a "Pâmela" via heurística (modulo='Receita')
- ✅ `services/prompt_loader.py` carrega prompts por nome (provavelmente prompts versionados em arquivos `.md` ou collection)

### Função real

**Pâmela** = **persona** que aparece em:
1. Texto-faceta da IA conversando com clientes em fluxo de venda/relacionamento
2. Atribuição de receita (modulo='Receita') no `agent_revenue.py`
3. **Não tem código, decisões, eventos ou collection próprios.**

**Camila** = mesma coisa para **outreach de vendas humanas / leads**. Provável que esteja embutida em `services/sales_outreach.py`.

### Decisão proposta: **DECLARAR PERSONAS, NÃO AGENTES**

Documento `LIGO_AGENT_ROSTER.md` (a criar):
- **Agentes com código próprio (módulos):** Isabella, Álvaro, Presidente IA, Rede IA, SmartOLT IA, Motor IA, Avaliador IA, Coach IA, Sentinela IA, Secretária IA
- **Personas (sem código próprio, são "voz/tom" da IA):** Pâmela, Camila, Leo

**Implicação para Conselhos:** o "Conselho Comercial" tem como responsáveis técnicos **Isabella Revenue Commander + Vendas IA + agent_revenue.py**. Camila é a **voz** que aparece nas comunicações externas — não a inteligência.

---

## 7️⃣ PROPOSTA DE FUSÃO

> 🟢 **A maior parte do "débito" não é duplicidade real — é ausência de contratos.** Por isso a Fase A propõe **mais documentação que código**.

### Resumo da fusão proposta

| Antes | Ação | Depois |
|---|---|---|
| 4 Presidentes | **DOCUMENTAR contratos** no header de cada um + criar `PRESIDENTE_ARCHITECTURE.md` | 4 camadas formalizadas (observability/monetization/simulation/execution) |
| 3 Conselhos | **HIERARQUIZAR** em 3 camadas (raw / report / parecer) + 5 Conselhos do CTO viram SUBSEÇÕES do report | 3 conselhos, 3 papéis claros |
| 5 Receitas | **RENOMEAR 4, INTERNALIZAR 1** (v7_2_revenue → revenue_attribution) | 2 leitores + 1 escritor + 1 detector |
| 3 "Briefings" | **RENOMEAR 3** (disparo_briefing NÃO é briefing) | 2 briefings reais + 1 dispatcher + 1 contexto de campanha |
| 4 Collections vazias/contaminadas | **3 DROP + 1 TAG** (executive_ledger marca sintéticos) | 1 collection limpa |
| Pamela/Camila | **DECLARAR personas oficialmente** em `LIGO_AGENT_ROSTER.md` | Sem prometer agente onde não há |

### O que **NÃO** está sendo fundido

- ❌ `presidente_ia.py` + `presidente_executive.py` → NÃO fundir. Camadas distintas, contratos claros.
- ❌ `isabella_conselho.py` + `conselho_ia.py` → NÃO fundir. O primeiro é input, o segundo é orquestrador.
- ❌ `agent_revenue.py` + `real_revenue.py` → NÃO fundir. Pontos de vista diferentes (agente vs financeiro).

A regra é **clarificar, não amalgamar**.

---

## 8️⃣ RISCOS DA FUSÃO

| # | Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|---|
| R1 | Renomear arquivos quebra imports de outros 30+ módulos | **ALTA** se feito sem cuidado | **ALTO** — backend não sobe | Usar **aliases** (`presidente_ia_briefing.py` permanece como `from ceo_briefing import *`) por 30 dias antes de remover |
| R2 | Drop de collection ainda em uso silencioso | MÉDIA | MÉDIO — perda de logs | `grep` exaustivo antes de drop + manter dump local |
| R3 | Documentação extensa nunca é lida (briefing ainda errado) | ALTA | MÉDIO | **Header de cada arquivo** com 5 linhas obrigatórias: "Eu sou. Eu leio. Eu escrevo. Eu chamo. NÃO me confunda com Y." |
| R4 | Health Score (presidente_ia) vs Executive Score (presidente_executive) — dois números, confusão | ALTA | ALTO | Definir politicamente: **briefing usa Executive Score**. Health Score vira métrica interna |
| R5 | Renomes quebram dashboards/painéis de monitoramento | MÉDIA | BAIXO | Aliases por 30d |
| R6 | "Personas oficiais" Pamela/Camila pode descontentar quem já vendeu Pamela como "agente" interno | ALTA | BAIXO | Comunicar claramente: **persona ≠ menos importante. É a voz da Ligo na comunicação.** |
| R7 | Auditor IA já em `conselho_ia.py` (auto-corrige whitelist) pode rodar sobre fontes renomeadas e quebrar | BAIXA | ALTO | Não tocar no Auditor nessa fase. Só após estabilização |
| R8 | `executive_ledger` tag `pre_sanitize_2026_06_14` quebra queries existentes | BAIXA | BAIXO | Adicionar campo, não remover. Queries antigas continuam funcionando |
| R9 | LLM cost subir sem perceber porque conselho passa a ser chamado mais vezes | MÉDIA | MÉDIO | **Métrica de custo LLM por dia** persistida em `llm_budget_log` (já existe!) — alertar se >20% acima da média |

---

## 9️⃣ PLANO DE ROLLBACK

> Toda mudança da Fase A é **idempotente, reversível e instrumentada**.

### Estrutura de rollback (por categoria)

**Renomes:**
- Cada renome é feito via `git mv` + **stub** no nome antigo:
```python
# /app/backend/services/presidente_ia_briefing.py
# DEPRECATED 14/06/2026 → use services/ceo_briefing.py
from services.ceo_briefing import *  # noqa
```
- Rollback: `git revert <commit>` ou remover o stub e renomear de volta.

**Documentação:**
- Apenas adição (`*_ARCHITECTURE.md`, `LIGO_AGENT_ROSTER.md`). Zero risco. Rollback trivial: `git rm`.

**Headers:**
- Apenas adição de comentários no topo de cada arquivo. Zero risco em runtime. Rollback trivial.

**Drop de collections (`presidente_ledger`, `briefing_executive`, `agent_revenue_events`):**
- **NÃO usar `drop()`** — usar `rename` para `_archive_<col>_<date>` (idempotente, reversível em 1 comando).
- Rollback: `db.<archive>.renameCollection('<original>')`.

**Tag em `executive_ledger`:**
- `db.executive_ledger.update_many({"company_id": {"$in": SYNTHETIC_TENANTS}}, {"$set": {"pre_sanitize_2026_06_14": True}})`
- Rollback: `update_many({"pre_sanitize_2026_06_14": True}, {"$unset": {"pre_sanitize_2026_06_14": ""}})`

### Janela de rollback

- **0-24h após deploy:** rollback via `git revert` + restart backend. Sem perda de dados.
- **24-72h:** rollback ainda viável; collections arquivadas ainda intactas.
- **3-30 dias:** rollback parcial — código volta, collections arquivadas viram source-of-truth se restauradas.
- **>30 dias:** consolidação assumida — rollback exigirá análise manual.

### Checkpoint testável

Após Fase A, executar este teste antes de declarar sucesso:

```python
# /app/backend/tests/test_phase_a_consolidation.py
async def test_one_truth():
    """Briefing, Conselho e Dashboard devem reportar o MESMO número de
    receita do mês para co-demo (tolerância: ±2%)."""
    # 1. via agent_revenue:
    a = await agent_revenue.month_total("co-demo")
    # 2. via real_revenue / revenue_realization:
    b = await revenue_realization.month_total("co-demo")
    # 3. via dashboard endpoint:
    c = await GET /api/dashboard/revenue/month
    assert abs(a - b) / max(b, 1) < 0.02
    assert abs(a - c) / max(c, 1) < 0.02
```

Se esse teste falhar — a fusão NÃO foi suficiente. Volta para discovery.

---

## 🔟 ENTREGÁVEIS FINAIS DA FASE A

Documentos a criar (zero código de produção):

1. ✅ **Este documento** (`FASE_A_CONSOLIDACAO_EXECUTIVA.md`) — diagnóstico + plano
2. 📋 `LIGO_AGENT_ROSTER.md` — quem é agente, quem é persona (Pamela/Camila/Leo declaradas)
3. 📋 `PRESIDENTE_ARCHITECTURE.md` — contratos dos 4 cérebros + diagrama
4. 📋 `CONSELHO_HIERARCHY.md` — os 3 níveis + onde os 5 Conselhos do CTO entram
5. 📋 `REVENUE_TRUTH.md` — qual fonte responde "quanto a Ligo faturou" (resposta: `revenue_realization.py`)

Mudanças no código (apenas se autorizado APÓS revisão dos documentos acima):

6. 🛠️ Headers atualizados nos 4 Presidentes + 3 Conselhos + 5 Receitas + 3 Briefings (apenas comentários)
7. 🛠️ Renomes com stubs:
   - `presidente_ia_briefing.py` → `ceo_briefing.py` (+ stub)
   - `briefing_dispatcher.py` → `ceo_briefing_dispatcher.py` (+ stub)
   - `disparo_briefing.py` → `disparo_campaign_context.py` (+ stub)
   - `agent_revenue.py` → `revenue_agent.py` (+ stub)
   - `real_revenue.py` → `revenue_realization.py` (+ stub)
   - `isabella_revenue.py` → `isabella_opportunities_revenue.py` (+ stub)
8. 🛠️ `revenue_attribution.py` absorve helpers de `v7_2_revenue.py` (mantém arquivo original como `from revenue_attribution import _ext_candidates`)
9. 🛠️ Rename collections vazias (`presidente_ledger` → `_archive_presidente_ledger_2026_06_14`, idem `briefing_executive`, `agent_revenue_events`)
10. 🛠️ Tag `pre_sanitize_2026_06_14=true` nos sintéticos do `executive_ledger`
11. 🧪 Teste de regressão `tests/test_phase_a_consolidation.py`

**Esforço estimado:** 2-3 dias úteis. Maioria é documentação + renomes mecânicos.

---

## ⏳ ORDEM DE EXECUÇÃO PROPOSTA

| Dia | Atividade | Verificação |
|---|---|---|
| **D1** | Criar 4 docs (`LIGO_AGENT_ROSTER`, `PRESIDENTE_ARCHITECTURE`, `CONSELHO_HIERARCHY`, `REVENUE_TRUTH`) | Revisão do CTO |
| **D1** | Atualizar headers dos 15 arquivos (Presidentes/Conselhos/Receitas/Briefings) | `python -m py_compile` em todos |
| **D2** | Executar renomes + stubs | `pytest` + `supervisorctl restart` + smoke test |
| **D2** | Archive das 3 collections vazias | Verificar nenhum código quebra |
| **D2** | Tag em `executive_ledger` | Briefing roda novamente, agora sem sintéticos |
| **D3** | Criar `tests/test_phase_a_consolidation.py` | Teste passa (números convergem ±2%) |
| **D3** | Logbook final + entrega ao CTO | Autorização para Fase B |

---

## ✅ AUTORIZAÇÃO SOLICITADA — FASE A

CTO, três perguntas finais antes de executar:

### Q-A1 — Escopo dos docs
a) ✅ Crio os 5 documentos primeiro, você revisa, **só depois** mexo em código (mais seguro)
b) Crio docs + faço renomes simultaneamente (mais rápido, mais risco)
c) Só mexer em código quando todos os 5 docs forem aprovados nominalmente

### Q-A2 — Política de aliases de import
a) ✅ Manter stubs por **30 dias** depois de cada renome (mais conservador)
b) Manter stubs por **7 dias** (mais agressivo)
c) Romper imediatamente sem stubs (mais limpo, mais arriscado)

### Q-A3 — Tag de sintéticos em `executive_ledger`
a) ✅ Aplicar **tag** `pre_sanitize_2026_06_14=true` (reversível, mantém histórico)
b) Mover para `_archive_executive_ledger_2026_06_14` (mais drástico)
c) Apenas filtrar nos endpoints sem tocar dado (zero risco mas confunde futuro)

---

> **Princípio reforçado:** Uma empresa. Uma verdade. Um briefing.
> Quando esta Fase A terminar com o teste `test_one_truth` passando, então — e só então — Fase B (Café com o CEO de verdade) faz sentido.
