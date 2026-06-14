# 🌌 UNIVERSO LIGO CUSTOMER INTELLIGENCE — Arquitetura

> **Operação:** Universo Ligo Customer Intelligence — Discovery + Arquitetura
> **Data:** 14/06/2026 · CTO Mode
> **Status:** ⛔ ZERO código escrito. Documento normativo + plano.
> **Missão:** Qualquer colaborador entende quem é o cliente em **<3 segundos**.

---

## 🎯 PRINCÍPIOS NÃO-NEGOCIÁVEIS

- ❌ Não é fidelidade, cashback, pontos, milhas, gamificação, ranking público
- ✅ É **contexto, relacionamento, pertencimento, história**
- ✅ Tag principal Universo Ligo (6 níveis) representa **história**, não dinheiro
- ✅ Classificações complementares (Black, Fundador, etc) são **secundárias** — nunca substituem a tag principal
- ✅ Score é **interno**. Cliente nunca vê. Apenas Isabella/Pâmela/Presidente IA/Atendimento/Gestão.

---

## 1️⃣ MAPA DO QUE JÁ EXISTE (REUSO INTEGRAL)

| Componente | Estado | Reuso |
|---|---|---|
| **6 níveis seedados** em `universo_ligo_levels` (Explorador → Embaixador) | ✅ existe | **Reuso integral** — JÁ tem key/icon/min_score/max_score/entry_rule |
| `universo_ligo_scores` (200 docs co-demo) | ✅ existe | **Estender com novos campos** (vide models.py — `level_key_v2`, `family_tree_l1_count`, `embaixador_card_number`) |
| `universo_ligo_invites` (curadoria, 2 docs APTO/DNC) | ✅ entregue 14/06 | Reuso — usado para flag "Embaixador convidado" |
| Relatórios já gerados em `/app/memory/`: Fundadores (130), Embaixadores naturais (113), Invisíveis (84), Mapa da base | ✅ existe | **Reuso integral** como classificadores |
| `subscribers` + `loyalty_imported_db` (rico: city, district, registration_date, invoices_paid, tickets, plan, fee) | ✅ existe | **Fonte primária** dos sinais |
| `isabella_commander_opportunities` (2.043 oportunidades co-demo) | ✅ existe | Sinal de cliente em risco / em oportunidade |
| `experience_campaigns` (17 reais — aniv_1y/3y/5y/vip) | ✅ existe | Sinal de embaixador natural já carimbado |
| `nps_responses_mvp` (recém-criado) | ✅ existe | Sinal de promoter/detractor |
| `motor_ia_revenue_attribution` | ✅ existe | High Ticket / Black calculation |
| `UniversoLigoPanel.js` + `UniversoLigoCuradoriaPanel.js` | ✅ existe | Painéis internos — não cliente-facing |
| Isabella prompt loader (`prompt_loader.py`) | ✅ existe | Hook para injetar contexto no system_prompt |

---

## 2️⃣ TABELAS / COLLECTIONS A USAR

### Coleção primária (já existe)
**`universo_ligo_scores`** — 1 doc por subscriber/company com:
- `subscriber_id`, `company_id`, `document`
- `level_key` (explorador/viajante/cometa/constelacao/galaxia/embaixador)
- `level_name`, `score_total` (interno, 0-1000)
- `tags_secondary` (array: ["high_ticket","fundador","invisible",...])
- `tenure_months`, `invoices_paid_lifetime`, `tickets_closed_lifetime`
- `confidence` (alta/media/baixa)
- `reasons` (array de strings explicáveis)
- `last_recalc_at`, `recalc_version`

### Coleções auxiliares (já existem)
- `universo_ligo_levels` (config — 6 docs)
- `universo_ligo_invites` (curadoria/DNC/embaixador convidado)
- `subscribers` (DNC global + flag de "high contrast" no atendimento)

### Nova coleção mínima (proposta)
- **`universo_ligo_score_audit`** — histórico de recálculos. 1 doc por subscriber por recálculo:
  - `subscriber_id`, `recalc_at`, `level_before`, `level_after`, `score_before`, `score_after`, `reason_changes`, `recalc_version`
  - **Por quê:** garantir auditabilidade total. Quando alguém pergunta "por que esse cliente virou Embaixador?", rastreio histórico completo.

---

## 3️⃣ FÓRMULA AUDITÁVEL

### Score Total (interno, 0-1000)

```
SCORE_TOTAL = 
    TEMPO_RELACIONAMENTO    × 0.30   (peso muito alto)
  + ESTABILIDADE_FINANCEIRA × 0.20   (peso alto)
  + RELACIONAMENTO          × 0.20   (peso alto)
  + PARTICIPACAO            × 0.10   (peso médio)
  + INDICACOES              × 0.10   (peso médio)
  + HISTORICO_TECNICO       × 0.10   (peso médio)
  
  × MULTIPLICADOR_FUNDADOR  (1.0 ou 1.5 se fundador histórico)

# Cada dimensão normalizada 0-1000 antes do peso.
```

### Cada dimensão (todas auditáveis)

| Dimensão | Cálculo | Fonte |
|---|---|---|
| **TEMPO_RELACIONAMENTO** | `min(1000, tenure_months × 10)` — 100 meses = 1000 | `loyalty_imported_db.registration_date` |
| **ESTABILIDADE_FINANCEIRA** | `1000 - (invoices_overdue × 200) - (cancellations × 300)` floor 0 | `loyalty_imported_db.invoices_overdue` + count `Desativado` |
| **RELACIONAMENTO** | `1000 - max(0, tickets_closed_lifetime - 5) × 30` + NPS_BONUS | `tickets`, `nps_responses_mvp` |
| **PARTICIPACAO** | `experience_campaigns.count × 200` (max 1000) | `experience_campaigns` |
| **INDICACOES** | `referrals_real × 100` (max 1000) — **hoje todos sintéticos, score=0 com confidence=baixa** | `referrals` (após filtro real) |
| **HISTORICO_TECNICO** | `1000 - (incidents_affecting × 50) - (signal_alerts × 20)` | `isabella_incidents`, `smartolt_onus` |
| **MULTIPLICADOR_FUNDADOR** | `1.5` se documento ∈ lista dos 130 fundadores; `1.0` caso contrário | `/app/memory/CLIENTE_FUNDADOR_REPORT.md` |

### Mapeamento Score → Nível (do seed existente)
- `0-99` → 🌱 **Explorador**
- `100-249` → 🚶 **Viajante**
- `250-449` → ☄️ **Cometa**
- `450-699` → ✨ **Constelação**
- `700-899` → 🌌 **Galáxia**
- **Embaixador (⭐)**: requires_invite=True. **NÃO é por score**. É por **convite humano** (via `universo_ligo_invites.decision=APTO` + invited=accepted).

### Tags complementares (não substituem a principal)

| Tag | Critério | Fonte | Confiança |
|---|---|---|---|
| 💎 **HIGH TICKET** | `monthly_fee >= 3 × média da base` (média co-demo ativa = R$ 103,37 → corte R$ 310) | `loyalty.monthly_fee` | 🟢 ALTA |
| 🖤 **BLACK** | `monthly_fee >= 6 × média` (corte R$ 620) | `loyalty.monthly_fee` | 🟢 ALTA |
| 🏛️ **FUNDADOR** | Documento ∈ 130 fundadores estritos (sem cancel + reg<2020 + paid≥50) | `CLIENTE_FUNDADOR_REPORT.md` | 🟡 MÉDIA-ALTA |
| 🤝 **EMBAIXADOR NATURAL** | Documento ∈ 113 candidatos OU ∈ Lista Ouro de 17 | `EMBAIXADORES_NATURAIS.md` + `experience_campaigns` | 🟡 MÉDIA |
| 🧭 **CLIENTE INVISÍVEL** | Documento ∈ 84 (zero tickets + zero atraso + paid≥12) | `CLIENTES_INVISIVEIS.md` | 🟢 ALTA |
| ⚠️ **CLIENTE EM RISCO** | `isabella_commander_opportunities.kind=churn AND status=pending AND score>=70` | `isabella_commander_opportunities` | 🟢 ALTA |
| 🔄 **CLIENTE RECUPERADO** | Já teve tag em risco resolvida (`opportunities.status=resolved AND outcome=retained`) | mesma coleção | 🟢 ALTA |

### Confiança do cálculo (campo declarado)
- 🟢 **ALTA**: ≥80% dos sinais com dados reais + tenure ≥12m
- 🟡 **MÉDIA**: faltam 1-2 sinais OU tenure <12m
- 🔴 **BAIXA**: faltam ≥3 sinais OU dependência crítica de campo indisponível (ex: referrals)

---

## 4️⃣ INTEGRAÇÕES (REUSO)

| Sistema | Como integra | Esforço |
|---|---|---|
| **Isabella** (`isabella` services + prompt_loader) | Injetar bloco "CUSTOMER_INTELLIGENCE" no system_prompt antes de conversar. Já existe pattern em `disparo_campaign_context.py`. | 1 função `customer_intel_block(subscriber_id)` |
| **Pâmela** (persona) | Mesmo prompt — bloco vai no system_prompt da Isabella quando assinatura=Pâmela | sem trabalho extra |
| **WhatsApp** (interface do atendente) | Painel lateral mostrando tag + tags secundárias + razões | endpoint novo + componente React |
| **Atendimento humano** (CRM/lousa) | Mesmo painel lateral. Badge visível no topo de cada conversa | mesmo endpoint |
| **CRM/Perfil do cliente** | Página de perfil já existente ganha **bloco Universo Ligo Intelligence** no topo | edição de página existente |
| **Lousa Mobile** (colaborador campo) | Header da OS mostra tag + nível em alto contraste | edição do header |

---

## 5️⃣ WIREFRAME — Bloco "Universo Ligo Intelligence"

### Versão compacta (badge para listas, conversas)
```
┌──────────────────────────────────────────────┐
│ ⭐ EMBAIXADOR · 🖤 · 🏛️       ↑ 121 meses    │
└──────────────────────────────────────────────┘
```

### Versão expandida (perfil, abertura de conversa)
```
┌──────────────────────────────────────────────────────────┐
│ WASHINGTON SILVA                                          │
│                                                            │
│ ⭐ EMBAIXADOR    🖤 BLACK    🏛️ FUNDADOR                 │
│                                                            │
│ Cliente desde 2014 (121 meses · 10 anos)                  │
│ Cordovil · Rio de Janeiro                                  │
│                                                            │
│ Produtos:                                                  │
│   • Link Dedicado                                          │
│   • Ligo+                                                  │
│   • Ligo 5G                                                │
│                                                            │
│ Motivos (auditáveis):                                      │
│   ✓ Cliente histórico (zero cancel + reg 2014)            │
│   ✓ Receita 6× média (R$ 620+/mês)                        │
│   ✓ Convite Embaixador aceito em 14/06/2026               │
│   ✓ 67 faturas pagas, zero overdue                        │
│                                                            │
│ Status financeiro: 🟢 em dia                              │
│ Últimos atendimentos: 0 nos últimos 12m                   │
│ Últimos tickets: nenhum aberto                             │
│                                                            │
│ Score interno: 947/1000 · Confiança: 🟢 ALTA              │
│                                                            │
│ [Ver histórico completo]  [Falar com Pâmela]              │
└──────────────────────────────────────────────────────────┘
```

### Princípios visuais
- Badge principal **sempre primeiro** (Universo Ligo)
- Tags secundárias **menores, ao lado**
- Score só visível para roles autorizados (admin/atendente/gestão)
- Cliente comum (cliente-facing) **nunca vê score**
- Cores: emoji + neutro (sem ranking visual entre clientes)

---

## 6️⃣ ARQUITETURA COMPLETA

```
┌─────────────────────────────────────────────────────────┐
│           CUSTOMER INTELLIGENCE — Camada Única           │
│                                                           │
│   services/customer_intelligence.py  (novo · ~400 linhas)│
│   ├─ get_intelligence(subscriber_id) → JSON estruturado  │
│   ├─ recalc(subscriber_id, force=False)                  │
│   ├─ recalc_all(cid, batch_size=500)                     │
│   ├─ _compute_score(sub) → 6 dimensões + multiplicador   │
│   ├─ _compute_tags(sub) → array de tags secundárias      │
│   ├─ _compute_confidence(sub) → alta/media/baixa         │
│   └─ _customer_intel_block(sub) → string p/ prompt LLM   │
└────────────────┬─────────────────────────┬──────────────┘
                 │ lê                       │ escreve
                 ▼                          ▼
   ┌──────────────────────────┐  ┌─────────────────────────┐
   │ FONTES (já existem)      │  │ universo_ligo_scores    │
   │  subscribers             │  │ (estendido)             │
   │  loyalty_imported_db     │  │ universo_ligo_score_audit│
   │  tickets                 │  │ (novo — histórico)      │
   │  experience_campaigns    │  └─────────────────────────┘
   │  isabella_commander_op   │
   │  nps_responses_mvp       │
   │  motor_ia_revenue_attr   │
   │  universo_ligo_invites   │
   │  /app/memory/* (listas)  │
   └──────────────────────────┘
                 │
                 │ consumido por
                 ▼
   ┌────────────────────────────────────────────────────────┐
   │  Isabella prompts · WhatsApp badge · Atendimento card   │
   │  Lousa header · CRM perfil · Painel admin universo      │
   └────────────────────────────────────────────────────────┘
```

### Endpoint público único
- `GET /api/customer-intelligence/{subscriber_id}` → JSON da versão expandida
- `GET /api/customer-intelligence/{subscriber_id}/badge` → versão compacta (cache 1h)
- `POST /api/customer-intelligence/{subscriber_id}/recalc` → admin only

---

## 7️⃣ PLANO DE IMPLANTAÇÃO

### Etapa 1 — Documentação (este doc)
✅ Entregue. Aguardando autorização CTO.

### Etapa 2 — Backend (~2-3 dias)
1. Criar `services/customer_intelligence.py` (~400 linhas)
2. Estender `universo_ligo_scores` com novos campos (não-destrutivo)
3. Criar coleção `universo_ligo_score_audit`
4. Criar route `routes/customer_intelligence.py` (3 endpoints)
5. Job batch: recalc inicial dos 2.746 ativos co-demo
6. Hook em `isabella` para injetar `customer_intel_block` em conversas

### Etapa 3 — Frontend (~2-3 dias)
1. Componente `<CustomerIntelligenceBadge>` (compacto, p/ listas)
2. Componente `<CustomerIntelligenceCard>` (expandido, p/ perfis)
3. Integrar em:
   - Header de conversas WhatsApp (atendimento)
   - Topo do perfil do cliente (CRM)
   - Header da OS na Lousa Mobile
   - Painel admin Universo Ligo (já existe — adicionar aba)

### Etapa 4 — Testes (1 dia)
1. `test_score_explainability` — toda tag tem razão
2. `test_no_invented_data` — nenhuma fonte mockada
3. `test_under_3_seconds` — endpoint responde <500ms cacheado
4. `test_embaixador_requires_invite` — não vira embaixador por score

### Etapa 5 — Gradual rollout
1. **Semana 1:** apenas backend rodando, dados em `universo_ligo_scores` recalculados, **sem mudança visual**
2. **Semana 2:** Badge nas listas de conversas (interno apenas)
3. **Semana 3:** Card no perfil
4. **Semana 4:** Hook na Isabella (injetar contexto em prompt)
5. **Mês 2:** Hook na Lousa Mobile

---

## 8️⃣ PLANO DE ROLLBACK

| Cenário | Rollback | Tempo |
|---|---|---|
| Backend cálculo errado | Feature flag `customer_intelligence_enabled=false` em `conselho_ia_settings`. Endpoint passa a retornar 404. | 30s |
| Score divergente de expectativa | `universo_ligo_score_audit` permite recalcular com `recalc_version` anterior. Histórico preservado. | 5min |
| Tag exibida assusta cliente (vazamento) | Componente `<CustomerIntelligenceBadge>` tem `role_required=["atendente","admin","gestor"]`. Se um bug expor ao cliente, hot-fix de role. | 10min |
| LLM (Isabella) confundir contexto e responder mal | Hook tem flag `inject_intelligence_in_prompt` por tenant. Desliga sem deploy. | 30s |
| Performance — recalc sobrecarrega DB | Job batch tem `batch_size=500` + `sleep_between_batches=2s`. Pode pausar via flag. | imediato |

**Princípio:** todo recálculo passa por `universo_ligo_score_audit` — rollback **nunca** perde histórico.

---

## 9️⃣ PLANO DE EVOLUÇÃO FUTURA

| Fase | Quando | O que entra |
|---|---|---|
| **V1** (esta proposta) | imediato | 6 níveis + 7 tags secundárias + score interno + explicabilidade |
| **V2** | +3 meses | Sinais comportamentais via NLP em `aihub_wa_messages` (sentimento, elogio espontâneo) |
| **V3** | +6 meses | Score familiar (clientes da mesma família/rede com 1+ embaixador) — sem cashback |
| **V4** | +9 meses | Recomendações de tratamento por nível (Embaixador → 0800 dedicado, Galáxia → fila prioritária) |
| **V5** | +12 meses | Promover Pâmela/Camila a agentes próprios SE virar prioridade (decisão ainda em aberto) |

---

## 🔟 DECISÕES + DÚVIDAS + RISCOS

### Decisões tomadas neste doc
1. ✅ **Reuso integral** das 6 collections já existentes (universo_ligo_*)
2. ✅ **Score 0-1000 interno**, 6 dimensões, multiplicador Fundador
3. ✅ **Embaixador** continua sendo **por convite humano**, nunca por score
4. ✅ **Confiança declarada** em cada classificação (alta/media/baixa)
5. ✅ **7 tags secundárias** com critérios numéricos auditáveis
6. ✅ **Coleção nova mínima**: apenas `universo_ligo_score_audit` (histórico)
7. ✅ **Endpoint único**: `GET /api/customer-intelligence/{sub_id}`

### Dúvidas em aberto (precisam decisão CTO antes de Etapa 2)
| # | Dúvida | Default proposto |
|---|---|---|
| D1 | Cliente comum (cliente-facing portal/app) vê alguma versão da tag? | Apenas o **nível principal** (sem score, sem tags secundárias). Mostra "Você é Galáxia 🌌" como reconhecimento, sem competição. |
| D2 | Recalc é diário (batch 03:00) ou em real-time por evento? | Híbrido: batch diário + invalidação por eventos críticos (cancelamento, embaixador aceito) |
| D3 | High Ticket e Black usam ticket médio **da base ativa** ou **da operação**? | Da base ativa (2.746 co-demo). Recalcular trimestralmente. |
| D4 | Hook em Isabella é opt-in por tenant ou default-on? | Default-OFF nesta versão. Ligar manualmente após validação. |
| D5 | Quem promove cliente para Embaixador? Botão exclusivo de Pâmela? | Sim — endpoint POST `/embaixador/promote` exige role específico + comentário obrigatório |
| D6 | Tag "Cliente em risco" aparece visualmente para o cliente? | NÃO. Apenas interno. |
| D7 | Mudança de nível dispara evento `UNIVERSO_LEVEL_CHANGED`? | Sim — já existe em `event_bus.py::EventType` |

### Riscos
| # | Risco | Severidade | Mitigação |
|---|---|---|---|
| R1 | Score errado promove cliente equivocado a Embaixador | 🔴 alta — Embaixador é status simbólico | **Embaixador SÓ por convite humano**, nunca por score. |
| R2 | Dado de tenure (registration_date) vir vazio para subscribers recém-criados | 🟡 média | Confiança=baixa quando tenure indisponível; cliente cai em Explorador |
| R3 | Atendente discrimina cliente Explorador vs Embaixador (oposto do objetivo) | 🟡 média | Treinamento + frase no card: "Todo cliente merece o mesmo cuidado. O nível ajuda a personalizar, não a hierarquizar." |
| R4 | LLM com bloco no prompt vira manipulativo ("é Embaixador, dê desconto") | 🟡 média | System prompt **proíbe** uso comercial do nível. Auditoria de outputs LLM em sample. |
| R5 | Vazamento de tag para cliente final (ex: "Você é Cliente em Risco") | 🔴 alta | Whitelist explícita de tags exibíveis ao cliente. Default-deny. |
| R6 | Recalc sobrecarrega DB | 🟢 baixa | Batch + sleep + cache 1h |

---

## ✅ CRITÉRIO DE ACEITE FINAL

Quando V1 estiver em produção:
1. Atendente abre conversa → vê tag principal + tags secundárias em **<3 segundos**
2. Toda tag tem razão clicável → "por quê?" responde com sinais reais
3. Score interno reproduzível: rodar recalc 2× dá mesmo número
4. Nenhum cliente vê score
5. Nenhum cliente vê tag "Em Risco" ou similar negativa
6. Embaixador continua exclusivo por convite humano
7. `test_no_invented_data` passa
8. `test_under_3_seconds` passa (endpoint <500ms cacheado, <2s sem cache)

---

## 🚦 PRÓXIMO PASSO

⛔ **NADA FOI ALTERADO NO BACKEND OU FRONTEND.**

CTO, autorizo a continuar? Três perguntas finais:

**Q1 — Iniciar Etapa 2 (backend) com defaults propostos D1-D7 acima?**
a) Sim, defaults aceitos
b) Sim, mas mude D1/D2/.../D7 (especificar)
c) Não — primeiro discutir cada D

**Q2 — Visualização do cliente comum (D1)**
a) Cliente vê só o nível principal (sem score, sem tags secundárias) — **proposta**
b) Cliente não vê nada
c) Cliente vê o nível + 1 frase ("Você está com a gente há X meses")

**Q3 — Hook na Isabella (D4)**
a) Default-off, ligamos após auditoria de output LLM
b) Default-on em todos os tenants
c) Default-on apenas em co-demo (piloto)
