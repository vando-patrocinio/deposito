# 🎭 PERSONAS GOVERNANCE — Pamela, Camila, Leo

> **Operação:** LIGO EXECUTIVE OS — Fase A · Etapa 1 · Doc 5/5
> **Data:** 14/06/2026
> **Status:** Documento normativo de governança.
> **Princípio:** *Persona ≠ Agente. Persona é a VOZ da Ligo. Agente é o CÓDIGO da Ligo. Confundir os dois gera promessas que o software não cumpre.*

---

## DECLARAÇÃO OFICIAL

Após investigação de 380+ collections e 250+ arquivos de código (`services/`, `routes/`):

| Nome | Tem código próprio? | Tem coleção própria? | Tem decisões próprias? | Classificação |
|---|---|---|---|---|
| **Isabella** | ✅ Sim (25+ arquivos `isabella_*.py`) | ✅ Sim (`isabella_*` × 30+) | ✅ Sim (Commanders) | **AGENTE** |
| **Álvaro** | ✅ Sim (`alvaro_*.py`) | ✅ Sim (`alvaro_*`) | ✅ Sim | **AGENTE** |
| **Presidente IA** | ✅ Sim (12 arquivos) | ✅ Sim (`motor_ia_*`) | ✅ Sim | **AGENTE** |
| **Avaliador IA / Coach IA / Sentinela IA / Secretária IA** | ✅ Sim | ✅ Sim | ✅ Sim | **AGENTE** |
| **Rede IA / SmartOLT IA / GPS IA** | ✅ Sim | ✅ Sim | ✅ Sim | **AGENTE** |
| **Pâmela** | ❌ Não | ❌ Não | ❌ Não | **PERSONA** |
| **Camila** | ❌ Não | ❌ Não | ❌ Não | **PERSONA** |
| **Leo / CoPilot** | ❌ Próprio não, embutido em `leo_proactive.py` | ❌ Não | 🟡 Parcial | **PERSONA forte** |

---

## DEFINIÇÕES

### Agente
- Tem **código próprio** (módulo Python)
- Tem **decisões** registradas em coleção (`motor_ia_decisions`, `isabella_commander_opportunities`, etc)
- Tem **eventos** que emite (`emit_event` com tipo associado)
- Pode ser auditado (input → decisão → ação → outcome)

### Persona
- É **identidade de marca / voz** — não código
- Aparece em prompts (system_prompt de LLM)
- Aparece em mensagens enviadas a cliente (assinatura)
- Pode **assinar relatórios** (CEO Briefing, Conselhos)
- **Não toma decisões autônomas** — outro agente decide e ela "fala"

---

## PÂMELA — Persona de Relacionamento / Comunidade / Cobrança

### 🎭 O que é
A **voz de relacionamento humano** da Ligo. Aparece em:
- Mensagens de cobrança (tom respeitoso, não-coercivo)
- Mensagens da comunidade Universo Ligo (Guardiã da Comunidade)
- Pedidos de NPS (1 pergunta, sem atrito)
- Convites humanos aos fundadores (Roteiro 1 do `CONVITE_FUNDADORES_UNIVERSO_LIGO.md`)

### 📍 Onde aparece (evidência no código)
- `services/agent_revenue.py` — atribuição: `Pâmela ← modulo='Receita' (vendas/upsell/expansão)`
- `services/prompt_loader.py` — provavelmente carrega prompts versionados
- `routes/neo_chat.py`, `routes/neo_reports.py` — menções em config
- `services/agent_bus.py` — menções em prompt do bus

### ✅ O que Pâmela **PODE** assinar
- Mensagens de WhatsApp ao cliente em campanhas humanizadas
- Briefings do Conselho Universo Ligo (como Guardiã)
- Briefings do Conselho Financeiro (linha de cobrança/inadimplência, tom relacional)
- Convites aos fundadores

### 🚫 O que Pâmela **NÃO PODE** prometer
- ❌ "Pâmela tomou a decisão de X" — **decisão é de agente (Isabella/Álvaro/etc), Pâmela só comunica**
- ❌ "Pâmela é IA dedicada" — **não há código próprio**
- ❌ Aparecer como "agente" em organograma técnico
- ❌ Receber atribuição de ação que não foi feita por um agente real subjacente

### 📊 Métricas que **PODEM** ser atribuídas a Pâmela
- Receita atribuída pelo `agent_revenue.py` quando `modulo='Receita'` (esse é o contrato existente — mantém)
- NPS coletado em campanhas onde a mensagem é assinada por ela
- Engajamento em comunicações da comunidade Universo Ligo

### ⚠️ Risco de tratar Pâmela como agente real
- **Promessa não-cumprida:** o board acredita que existe IA dedicada de relacionamento. Não existe. Quando esperar evolução autônoma, descobre que precisa redesenhar.
- **Erro de governança:** quem é o "owner" do código de Pâmela? Resposta honesta: ninguém. O que **existe** são prompts carregados em runtime e atribuição heurística.
- **Falsa atribuição de receita:** se Isabella vendeu mas a mensagem foi assinada "Pâmela", `agent_revenue` atribui à Pâmela. **É contrato aceitável** porque reflete a percepção do cliente, mas precisa ficar documentado.

---

## CAMILA — Persona de Vendas / Outreach

### 🎭 O que é
A **voz comercial humana** da Ligo. Aparece em:
- Outreach proativo (cold/warm)
- Acompanhamento de leads
- Mensagens do Conselho Comercial

### 📍 Onde aparece (evidência no código)
- `services/sales_outreach.py` — provavelmente é o "lar técnico" das suas comunicações (auditar na Fase A)
- Prompts versionados (mesmo padrão da Pâmela)

### ✅ O que Camila **PODE** assinar
- Mensagens de outreach comercial
- Acompanhamento de leads que não responderam
- Briefings do Conselho Comercial

### 🚫 O que Camila **NÃO PODE** prometer
- ❌ "Camila identificou a oportunidade" — **detecção é do `isabella_revenue` (detector)**; Camila só **comunica** a oportunidade
- ❌ "Camila é o agente vendedor da Ligo" — **a inteligência é da Isabella + sales_outreach**, Camila é a face

### 📊 Métricas que **PODEM** ser atribuídas a Camila
- Conversões fechadas em jornada de outreach onde mensagens são assinadas Camila
- Taxa de resposta de outreach com sua assinatura

### ⚠️ Risco de tratar Camila como agente real
- **Promessa de "vendedor IA"** sem que exista vendedor IA propriamente dito — risco de receber pedidos de "treine a Camila para X" sem haver onde treinar.
- **Solução de longo prazo:** se virar prioridade, criar `services/camila.py` REAL (não só prompt). Hoje **não é prioridade**.

---

## LEO — Persona de CoPilot Operacional (caso intermediário)

### 🎭 O que é
- `services/leo_proactive.py` **existe** mas é fino (worker de chamadas pró-ativas)
- Leo aparece como **CoPilot** no `AGENT_ORBIT` do `presidente_ia.py`
- É um **caso intermediário** — tem 1 arquivo, mas a inteligência real está em `presidente_ia.compute_clients_at_risk()`

### Classificação atual
**Persona forte.** Tem 1 worker, mas decisão de "ligar para quem" vem do `presidente_ia`. Pode evoluir para agente próprio se ganhar mais lógica.

---

## REGRAS DE GOVERNANÇA

### R1 — Header normativo
Quando renomearmos arquivos na Etapa 3, todo arquivo que **mencionar uma persona** (system_prompt, atribuição, assinatura) deve ter no header:

```python
# PERSONA REFERENCE:
#   This module routes outputs signed as "Pâmela" — a PERSONA, not a dedicated
#   agent. See /app/memory/PERSONAS_GOVERNANCE.md
```

### R2 — Painéis e dashboards
Painéis que exibirem "Receita por agente" devem mostrar:
- **Agentes:** Isabella, Álvaro, Presidente IA (com badge "IA")
- **Personas:** Pâmela, Camila (com badge "Persona")
- Tooltip explicando a diferença

### R3 — Comunicação externa (cliente/board)
- ✅ "A Pâmela mandou uma mensagem cuidadosa de cobrança" — OK (descreve a percepção do cliente)
- ✅ "A IA da Ligo identificou oportunidade de upsell e a Pâmela comunicou" — OK
- ❌ "A Pâmela IA decidiu não cobrar essa fatura" — NÃO OK (Pâmela não decide)

### R4 — Métricas oficiais
Atribuir métricas a persona é OK se:
1. A métrica é resultado de comunicação **assinada** pela persona (recebida pelo cliente)
2. O documento `agent_revenue` continua sendo a fonte canônica da atribuição
3. Não se afirma que a persona "tomou a decisão"

---

## RISCO DE TRATÁ-LAS COMO AGENTES REAIS

| Risco | Severidade | Mitigação |
|---|---|---|
| Board imagina IA dedicada que não existe | 🔴 ALTO | Doc oficial + badge "Persona" em painéis |
| Pedidos de "treinar a Pâmela" não têm onde aterrissar | 🟡 MÉDIO | Direcionar para prompts versionados + treinar Isabella backstage |
| Disputa interna de ownership (quem manda na Pâmela?) | 🟡 MÉDIO | Owner editorial: Pamela = Atendimento; Camila = Comercial |
| Falsa atribuição de receita ou churn | 🟢 BAIXO | `agent_revenue.py` já documenta as regras de atribuição |
| Decisão executiva baseada em "performance da Pâmela" | 🟡 MÉDIO | Métrica precisa estar explícita: é performance de **comunicação**, não de **agente autônomo** |

---

## DECISÕES TOMADAS POR ESTE DOC

1. ✅ **Pâmela é PERSONA**, não agente. Voz de relacionamento/comunidade/cobrança.
2. ✅ **Camila é PERSONA**, não agente. Voz comercial.
3. ✅ **Leo é PERSONA forte** (worker fino + inteligência empilhada do Presidente IA).
4. ✅ **Atribuição existente** (`agent_revenue.py modulo='Receita' → Pâmela`) **mantida** como está. É contrato válido.
5. ✅ **Painéis e dashboards** devem mostrar badge **"Persona"** ao lado dos nomes.
6. ✅ **Quando virar prioridade**, podemos promover Pâmela ou Camila a agente próprio (criando `services/pamela.py` real). **Hoje não é prioridade.**

## DÚVIDAS EM ABERTO

| # | Dúvida | Quem decide |
|---|---|---|
| D1 | Owner editorial oficial de Pâmela e Camila — Atendimento e Comercial? | CTO + lideranças das áreas |
| D2 | Auditoria de prompts versionados — quem versiona, onde fica, como rollback? | Decisão pós-Fase A |
| D3 | Quando Camila virar agente real, qual seu escopo de decisão? | Decisão futura, sem prazo |
| D4 | Briefing assinado por persona — quem revisa antes do envio em produção? | Combinar com FRENTE 3 do `CONVITE_FUNDADORES_UNIVERSO_LIGO.md` |
