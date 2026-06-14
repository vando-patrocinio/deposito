# 💰 EXECUTIVE REVENUE — CONTRATOS DE FONTE DE VERDADE

> **Operação:** LIGO EXECUTIVE OS — Fase A · Etapa 1 · Doc 3/5
> **Data:** 14/06/2026
> **Status:** Documento normativo.
> **Princípio:** *Não pode existir mais de uma resposta oficial para "Quanto a Ligo faturou?"*

---

## 🎯 RESPONSABILIDADE ÚNICA POR PERGUNTA

| Pergunta do CEO | Fonte oficial | Coleção primária |
|---|---|---|
| **"Quanto a Ligo faturou?"** (mês/dia) | `services/real_revenue.py` *(será renomeado para `revenue_realization.py` na Etapa 3)* | `subscriber_invoices` |
| **"Quanto cada agente IA gerou?"** | `services/agent_revenue.py` *(`revenue_agent.py`)* | `motor_ia_revenue_attribution` |
| **"Quanto a empresa economizou?"** | `services/agent_revenue.py` (campo `economy_brl`) | `motor_ia_revenue_attribution` + `motor_ia_actions.roi_brl` |
| **"Quais oportunidades de receita estão abertas?"** | `services/isabella_revenue.py` *(`isabella_opportunities_revenue.py`)* | `isabella_commander_opportunities` |
| **"Onde registramos cada outcome financeiro?"** | `services/revenue_attribution.py` | `motor_ia_revenue_attribution` (escrita) |
| **"Como join entre actions/outcomes/invoices funciona?"** | `services/v7_2_revenue.py` *(internalizado em revenue_attribution na Etapa 3)* | utilitário interno |

**Regra de ouro:** se um endpoint precisa de "receita do mês", **chama `revenue_realization.month_total(cid)`**. Se outro endpoint chamar de outra fonte para a mesma resposta, **bug a corrigir em code review**.

---

## CAMADA 1 — Realização Financeira (RESPONDE "QUANTO FATUROU")

### `services/real_revenue.py` → renomeação proposta: `revenue_realization.py`

**Função:** separar **Estimado / Confirmado / Recebido**. Nunca mistura projeção com realizado.

**📥 Lê de:**
- `subscriber_invoices` (status=paid, due_date, paid_at)
- `contracts` (mrr_brl, plan_price)

**📤 Saída pública:**
- `month_total(cid)` → R$ recebido no mês corrente
- `day_total(cid)` → R$ recebido ontem
- `forecast_30d(cid)` → R$ previsto próximos 30d (boletos abertos com vencimento)
- `inadimplencia(cid)` → {n_clientes, total_brl, % over_30d}

**🚫 Não faz:**
- Atribuição por agente (vai para `revenue_agent`)
- Oportunidades futuras (vai para `isabella_opportunities_revenue`)

**Status:** Legado funcional (V6.2). **Mantém.** Renome conceitual na Etapa 3.

---

## CAMADA 2 — Atribuição por Agente IA (RESPONDE "QUANTO CADA AGENTE GEROU")

### `services/agent_revenue.py` → renomeação proposta: `revenue_agent.py`

**Função:** atribuição cruzada de outcomes a agentes IA (Isabella / Pâmela / Vendas / Álvaro). 3 métricas:
- **Receita Gerada** (R$ novos: venda/upsell/expansão)
- **Receita Protegida** (R$ churn evitado — LTV preservado)
- **Economia** (R$ recuperados + visitas evitadas + custos prevenidos)

**📥 Lê de:**
- `motor_ia_revenue_attribution` (kind in {recovered, generated, protected, cost_saved})
- `executive_ledger` (modulo, valor_confirmado_brl) — **após tag pre_sanitize_2026_06_14**
- `motor_ia_actions` (roi_brl + agent attribution)

**📤 Saída pública:**
- Tabela por agente (Isabella / Pâmela / Vendas / Álvaro)
- Métricas em R$ por janela (7d/30d/MTD)

**🚫 Não faz:**
- "Quanto a empresa faturou" → use `revenue_realization`
- Detecção de oportunidade aberta → use `isabella_opportunities_revenue`

**Status:** **Mantém.** Renome conceitual na Etapa 3.

---

## CAMADA 3 — Persistência de Outcomes (RESPONDE "ONDE REGISTRAMOS")

### `services/revenue_attribution.py`

**Função:** **única escrita** na coleção `motor_ia_revenue_attribution`. Toda ação IA com outcome financeiro **passa por aqui**.

**Kinds suportados (fechado):**
- `recovered` — cobrança automática que recuperou R$
- `generated` — receita nova (upsell, cross-sell, indicação convertida)
- `churn_prevented` — cliente que ia cancelar e foi retido
- `cost_saved` — visita técnica evitada, hora-homem poupada

**📥 Lê:**
- Nenhum. **Escritor puro.**

**📤 Saída:**
- `attribute(...)` → insert em `motor_ia_revenue_attribution`
- `summary(cid, days)` → agregação rápida (lido por `agent_revenue` e `alvaro_director`)

**🚫 Não faz:**
- Cálculos derivados — só persiste

**Status:** **Mantém.** Sem renome.

---

## CAMADA 4 — Detector de Oportunidades (RESPONDE "ONDE PODE VENDER MAIS")

### `services/isabella_revenue.py` → renomeação proposta: `isabella_opportunities_revenue.py`

**Função:** detector ativo. **Não calcula receita realizada.** Apenas identifica casos com sinal de potencial receita.

**Detecta:**
- Upgrade de plano (assinante em plano antigo, sem upgrade ≥12 meses, pagamentos em dia, novo plano superior disponível)
- Add-ons potenciais (PlayHub, Ligo 5G, IP fixo, WiFi Premium)
- Reativação de cancelados recentes (≤90d) sem ticket de churn definitivo

**📥 Lê de:**
- `subscribers` (status=ativo + plano + tenure)
- `tickets` (sinais)
- `isabella_commander_opportunities` (estado atual)

**📤 Saída:**
- Insere em `isabella_commander_opportunities` (kind=revenue, kind=expansion)
- **Não dispara nada** — humano aciona via painel (1-click)

**Status:** **Mantém.** Renome conceitual na Etapa 3 para deixar claro que é **detector**, não calculadora.

---

## CAMADA UTILITÁRIA — Joins/Matching

### `services/v7_2_revenue.py` → **será internalizado em `revenue_attribution.py` na Etapa 3**

**Função:** resolve 4 bugs de join entre actions/outcomes/invoices:
- Bug #1: `motor_ia_outcomes` usa chave `outcome_id` em vez de `id`
- Bug #2: outcomes não têm `subscriber_id` — está em actions/decisions
- Bug #3: `subscribers.external_code` prefixado ("ATLAZ-1813301") vs invoices cru ("1813301")
- Bug #4: `revenue_realization=0` com 3.445 invoices paid → ignora receita orgânica

**Conteúdo:**
- Função `_ext_candidates` — gera lista de external_codes possíveis
- Lógica de matching entre actions, decisions, outcomes, invoices

**Status pós-Fase A:** **Não é receita. É infra de matching.** Funções serão expostas dentro de `revenue_attribution.py` (que já tem `attribute()`). O arquivo `v7_2_revenue.py` vira **stub** por 30 dias com `from services.revenue_attribution import _ext_candidates`.

**Hoje é importado por:** `v8_4_cohort.py`, `v8_3_causality.py`. Esses imports continuam funcionando via stub.

---

## TABELA DE CONSULTA RÁPIDA

| O endpoint precisa de... | Chama... |
|---|---|
| Receita do mês para CEO Briefing | `revenue_realization.month_total(cid)` |
| Receita por agente no Conselho Comercial | `revenue_agent.by_agent(cid, days=30)` |
| Outcome de uma ação IA | `revenue_attribution.attribute(action_id, kind, valor_brl)` |
| Lista de oportunidades de upsell | `isabella_opportunities_revenue.detect(cid)` |
| Inadimplência atual | `revenue_realization.inadimplencia(cid)` |
| Resolver join "essa ação gerou essa invoice?" | `revenue_attribution._ext_candidates(...)` (ex-v7_2) |

---

## COLEÇÃO ÚNICA DE ATRIBUIÇÃO

**`motor_ia_revenue_attribution`** é a **única** coleção de atribuição de receita. Estrutura:

```json
{
  "id": "rev-attr-<uuid>",
  "company_id": "co-demo",
  "kind": "recovered | generated | churn_prevented | cost_saved",
  "valor_brl": 234.50,
  "action_id": "...",         // FK motor_ia_actions
  "subscriber_id": "...",
  "agent": "isabella | pamela | vendas | alvaro",  // persona/agente
  "source": {
    "template": "...",
    "channel": "whatsapp_baileys | email | sms | call",
    "campaign_id": "...optional..."
  },
  "created_at": "..."
}
```

**Outras coleções relacionadas:**
- `executive_ledger` — ledger consolidado (sintéticos serão tagueados `pre_sanitize_2026_06_14=true` na Etapa 3)
- `motor_ia_actions.roi_brl` — receita prevista no momento da ação (não realizada)
- `subscriber_invoices` — fonte primária do "Quanto faturou"

---

## DECISÕES TOMADAS POR ESTE DOC

1. ✅ **`revenue_realization` (ex-`real_revenue`)** é a **única** fonte para "Quanto a Ligo faturou?"
2. ✅ **`revenue_agent` (ex-`agent_revenue`)** é a **única** fonte para "Quanto cada agente gerou?"
3. ✅ **`revenue_attribution`** é a **única** escrita em `motor_ia_revenue_attribution`. Nenhum outro serviço escreve nessa coleção.
4. ✅ **`v7_2_revenue`** vira **utilitário interno** de `revenue_attribution`. Stub mantém imports antigos por 30 dias.
5. ✅ **`isabella_opportunities_revenue` (ex-`isabella_revenue`)** é **detector**, não calculadora.
6. ✅ **CEO Briefing** chama exatamente DOIS pontos: `revenue_realization` (linha "Receita") e `revenue_agent` (linha "Por agente"). Não três.

## DÚVIDAS EM ABERTO

| # | Dúvida | Quem decide |
|---|---|---|
| D1 | `executive_ledger` (após tag) ainda é fonte primária de algum cálculo? Ou foi substituído por `motor_ia_revenue_attribution`? | Auditoria na Etapa 3 |
| D2 | "Pamela" como agente em `agent_revenue.py` — atribuição por heurística (`modulo='Receita'`). Manter ou explicitar persona-only? | Decisão alinhada a `PERSONAS_GOVERNANCE.md` |
| D3 | Receita protegida (`churn_prevented`) requer ground-truth (cliente sob risco mas ficou). Como auditar? | Decisão na Fase B |
| D4 | Teste `test_one_truth` — qual tolerância exata? Documento sugere ±2%. Aceita? | CTO decide |
