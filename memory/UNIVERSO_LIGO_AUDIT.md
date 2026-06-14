# 🛰️ UNIVERSO LIGO — AUDITORIA EXECUTIVA + PLANO DE FUNDAÇÃO

**Data:** 13/Jun/2026
**Modo:** CTO / Auditor Independente · Zero ficção · Tudo extraído do código e do Mongo em produção
**Encomendado por:** CEO Ligo · Ordem Executiva V1
**Escopo:** Mapear tudo que existe relacionado a indicação · cashback · benefícios · gamificação · pontos · fidelidade · campanhas · promoções · referrals · universo ligo · playhub · ligo+ · ligo móvel · ligo tv · comunidade — antes de escrever 1 linha de código nova.

---

## 1. INVENTÁRIO ATUAL (o que EXISTE)

### 1.1 Backend — services
| Arquivo | LOC | Função | Status |
|---|---|---|---|
| `backend/services/universo_ligo.py` | 349 | Score engine + tabela de níveis | ✅ Em produção · usa dados reais |
| `backend/services/isabella_relationship.py` | 361 | NPS inference, contextual pitch, closing | ⚠️ Existe · **NÃO está plugado no fluxo Isabella WA** |
| `backend/services/isabella_experience.py` | 598 | Campaign engine (aniversário, birthday, level-up, referral conversion, incident resolution) | ⚠️ Roda · gera 17 campanhas · **0 EXECUTED real** |
| `backend/services/presidente_score_engine.py` | — | Score executivo | ✅ Em uso |
| **TOTAL backend services** | **~1.308** | | |

### 1.2 Backend — routes
| Arquivo | LOC | Endpoints | Status |
|---|---|---|---|
| `backend/routes/universo_ligo.py` | 244 | **15** (identify, score, levels, panel, refresh-all, history, experience/scan, campaigns/{id}/approve, /cancel, /execute, /council-review, audit, templates) | ✅ Em uso |
| `backend/routes/referrals.py` | **2.356** | **26** (códigos, mural, submit, customer/login, customer/stats, leaderboard, payouts approve/reject, blast-invite, admin/dashboard, engagement-alerts, campaign config CRUD, milestone cards, QR resolve) | ✅ Em uso |
| **TOTAL backend routes** | **~2.600** | **41 endpoints** | |

### 1.3 Frontend — Cliente App (`/app/frontend/src/cliente/`)
| Arquivo | LOC | Função |
|---|---|---|
| `ClienteIndicaApp.js` | 115 | App container (login + roteamento) |
| `HubScreen.js` | 243 | Hub principal do cliente |
| `IndiqueScreen.js` | 874 | Tela de indicação (gamificação completa) |
| `MinhaLigoScreen.js` | 192 | Perfil/conta do cliente |
| `PromocoesScreen.js` | 273 | Lista promoções ativas |
| `PromocoesSheet.js` | 250 | Bottom sheet de promo |
| `PromoDetailModal.js` | 211 | Modal de detalhes |
| `LoginCPF.js` | 229 | Login por CPF |
| `ClientQRModal.js` | 266 | QR code para compartilhar |
| `components.js` | 409 | Componentes compartilhados |
| `ligo-theme.js` | 166 | Theme tokens |
| **SUBTOTAL cliente app** | **3.228** | UI pronta — login + hub + indicação + promo |

### 1.4 Frontend — Admin
| Arquivo | LOC | Função |
|---|---|---|
| `frontend/src/ReferralsAdminPanel.js` | 752 | Painel admin de indicações |
| `frontend/src/ReferralLandingPage.js` | 483 | Landing pública `/r/{code}` |
| `frontend/src/ReferralsModal.js` | 374 | Modal interno |
| `frontend/src/UniversoLigoPanel.js` | 436 | Painel Universo Ligo (gestor) |
| **SUBTOTAL admin** | **2.045** | |

### 1.5 Prompts dos agentes
| Arquivo | LOC | Persona | Universo Ligo dentro do prompt? |
|---|---|---|---|
| `prompts/isabella_v13.md` | 388 | Consultora Universo Ligo | ❌ Cita 2 vezes (seção 6.7 opcional) |
| `prompts/pamela_v2.md` | 294 | Cobrança/Financeiro | ❌ Zero menção |
| `prompts/alvaro_v2.md` | 267 | Suporte técnico | ❌ Zero menção |

---

## 2. INVENTÁRIO MONGO — DADO REAL

### 2.1 Universo Ligo + Loyalty
| Collection | Docs | Significado |
|---|---|---|
| `subscribers` | **26.851** | Base real de assinantes |
| `loyalty_imported_db` | 24.040 | Base Atlaz importada |
| `universo_ligo_scores` | **200** (0.75%) | Só 200 dos 26k têm score |
| `universo_ligo_history` | 2 | Zero rastro de evolução |
| `nps_responses` | **0** | Score usa NPS, tabela vazia |
| `motor_ia_subscriber_scores` | 2.796 | Outro engine de scoring (sobreposto) |

### 2.2 Indicação / Cashback
| Collection | Docs | Significado |
|---|---|---|
| `referrals` | 7 | 5 são `milestone` (seed), 2 reais (contacted) |
| `referral_rewards` | **0** | Nenhuma recompensa creditada |
| `referral_payouts` | **0** | Zero pagamentos |
| `referral_streak_bonuses` | **0** | Streak abandonado |
| `referral_goal_bonuses` | **0** | Meta abandonada |
| `referral_campaign_config` | **0** | Sem campanha configurada |
| `indicacao_leads` | 1 | Conceito DUPLICADO de `referrals` |
| `indicacao_credits` | **0** | Conceito DUPLICADO de `referral_rewards` |

### 2.3 Campanhas / Oportunidades
| Collection | Docs | Significado |
|---|---|---|
| `isabella_commander_opportunities` | **2.027** | 78% pending, 21% expired, 0.25% approved |
| `experience_campaigns` | 17 | APPROVED/READY — 0 EXECUTED real |
| `experience_campaigns_audit` | 27 | |
| `loyalty_opportunities` | 8 | Sobreposição com isabella_commander |
| `loyalty_opportunities_ai` | 1 | |
| `corporate_goals` | 12 | |

### 2.4 Distribuição atual de níveis (entre os 200 pontuados)
| Nível | Count | Avg score |
|---|---|---|
| Explorador (0–99) | 35 (17%) | 46.3 |
| Cometa (100–249) | 32 (16%) | 173.6 |
| **Órbita (250–499)** | **133 (67%)** | 338.0 |
| Estelar (500–799) | 0 | — |
| Galáxia Ouro (800–1199) | 0 | — |
| Universo Ligo (1200+) | 0 | — |

→ **Curva enviesada pra Órbita** porque a tabela `nps_responses` está vazia (todos perdem até 50pts) e `referral_*` não atribui pontos (vazias). Fórmula está OK, **input ausente**.

---

## 3. SISTEMA DE NÍVEIS — HOJE vs ORDEM DO CEO

| # | Backend hoje (`universo_ligo.py:51`) | CEO ordenou | Ação V1 |
|---|---|---|---|
| 1 | **Explorador** (0–99) | **Explorador** | ✅ Mantém |
| 2 | Cometa (100–249) | **Viajante** | 🔄 Renomear/Shift |
| 3 | Órbita (250–499) | **Cometa** | 🔄 Shift |
| 4 | Estelar (500–799) | **Constelação** | 🔄 Renomear |
| 5 | Galáxia Ouro (800–1199) | **Galáxia** | 🔄 Renomear (limpar "Ouro") |
| 6 | Universo Ligo (1200+) | **Embaixador** | 🔄 Renomear |

**Impacto:** os 200 docs em `universo_ligo_scores` precisam de migration → `level_key` e `level_name` renomeados. Pontuação não muda. Sem perda de dado.

---

## 4. O QUE ESTÁ QUEBRADO (com evidência)

| # | O quê | Evidência | Severidade |
|---|---|---|---|
| 1 | **NPS sempre zero no score** | `nps_responses` = 0 docs → todos perdem até 50pts no scoring | 🔴 P0 |
| 2 | **Só 0.75% da base tem score** | 200/26.851 — falta job de refresh em massa | 🔴 P0 |
| 3 | **Programa de indicação morto** | 0 rewards, 0 payouts em 30+ dias com 26k base | 🔴 P0 |
| 4 | **Tabelas duplicadas** | `referrals` + `indicacao_leads`, `referral_rewards` + `indicacao_credits`, `loyalty_*` + `universo_ligo_*` | 🟡 P1 |
| 5 | **2.027 oportunidades Isabella, 0.25% aprovadas** | Gestor humano = gargalo. Sistema gera ruído | 🔴 P0 |
| 6 | **17 experience campaigns, 0 EXECUTED** | Aprovação ou execução está quebrada | 🟡 P1 |
| 7 | **`isabella_relationship.py` órfão** | 361 LOC com `universo_ligo_contextual_pitch` — não está plugado no fluxo Isabella WA | 🟡 P1 |
| 8 | **Pâmela = cobrança, não relacionamento** | `pamela_v2.md` (294 LOC) tem identidade "Cobrança da Ligo Fibra" | 🔴 P0 |
| 9 | **Isabella não conhece nível do cliente** | Prompt v13 não injeta `=== UNIVERSO LIGO STATUS ===` | 🔴 P0 |
| 10 | **Nomes de níveis NÃO batem com visão CEO** | 5 dos 6 renomeados | 🟡 P1 |
| 11 | **`subscribers` não tem campo `referral_code`** | Schema sample (40 campos): zero campo de indicação | 🟡 P1 |
| 12 | **Sem campos de produtos Ligo+ no subscriber** | Não há `addons.has_tv`, `addons.has_musica`, etc. | 🟡 P1 |

---

## 5. O QUE ESTÁ ABANDONADO (zerado há >30 dias)
- `nps_responses` · `referral_rewards` · `referral_payouts` · `referral_streak_bonuses` · `referral_goal_bonuses` · `referral_campaign_config` · `indicacao_credits` · `loyalty_dispatch_jobs` · `loyalty_ai_insights` · `loyalty_opportunities_ai` · `pre_subscribers`

Estas coleções foram **criadas mas nunca alimentadas**. Decisão: ou plugamos input, ou removemos do schema.

---

## 6. O QUE PODE SER REAPROVEITADO

| Asset | LOC | Uso na V1 |
|---|---|---|
| `services/universo_ligo.py` (score engine) | 349 | ✅ Mantém. Refator: renomear 5 níveis + criar Viajante/Constelação/Embaixador |
| `routes/referrals.py` (26 endpoints) | 2.356 | ✅ Mantém integralmente. Já tem R$50 direto + R$10 indireto + streak + tier + goal |
| `services/isabella_experience.py` (campaign engine) | 598 | ✅ Mantém. Conectar de verdade no scheduler diário |
| `cliente/HubScreen.js` + `IndiqueScreen.js` + `MinhaLigoScreen.js` | 1.309 | ✅ Mantém. Já é app pronto |
| `UniversoLigoPanel.js` (admin) | 436 | ✅ Mantém. Já refatorado pra tema claro hoje |
| `services/isabella_relationship.py` | 361 | ✅ Plugar de verdade no contexto do prompt |

**Reaproveitamento total estimado: ~5.500 LOC.** Não vamos reescrever — **vamos conectar.**

---

## 7. MODELO DE DADOS — V1

### 7.1 Collections novas
```yaml
universo_ligo_levels:           # CONFIG (única collection, 6 docs)
  - level_id, key, name, description, icon, min_score, max_score
  - benefits: [{type, label, value, conditions}]
  - requirements: [{factor, min_value, label}]
  - badge_image_url

universo_ligo_benefits_grant:    # Concessão real ao cliente
  - id, subscriber_id, level_id, benefit_key
  - granted_at, expires_at, status (active|used|expired)
  - usage_count, last_used_at

universo_ligo_milestones:        # Marcos do cliente
  - id, subscriber_id, milestone_type (1_ano_ligo|nivel_up|N_indicacoes|aniversario|sem_ticket_90d)
  - reached_at, celebrated_at (null se ainda não comunicado)
  - context (level_key, count, etc.)

universo_ligo_tree_index:        # Cache da árvore de indicações
  - root_subscriber_id, level_1_count, level_2_count
  - last_calculated_at
```

### 7.2 Collections existentes que GANHAM campos
```yaml
subscribers:
  + universo_score (denormalizado, atualizado pelo job)
  + universo_level_key
  + referral_code (índice unique)
  + referred_by_subscriber_id (FK)
  + addons_active: [tv, musica, filmes, ip_fixo, wifi_plus, 5g]
  + nps_last_score, nps_last_at

universo_ligo_scores:           # já existe
  + tree_level_1_count          # qtd indicações diretas
  + tree_level_2_count          # qtd indiretas
  + economia_acumulada_brl      # benefícios usados + rewards
```

### 7.3 Tabelas a DEPRECAR (duplicadas)
```
indicacao_leads        → migrar pra referrals
indicacao_credits      → migrar pra referral_rewards
loyalty_opportunities  → migrar pra isabella_commander_opportunities (unificar)
loyalty_opportunities_ai → idem
pre_subscribers        → unused
```

---

## 8. SERVIÇOS — V1

| Serviço (novo ou refator) | Função | Esforço |
|---|---|---|
| `services/universo_ligo.py` (refator) | Renomear 6 níveis, adicionar tree counts e economia ao score, **publicar evento `universo.level.changed` em level-up** | 1 dia |
| `services/universo_ligo_benefits.py` (novo) | Conceder benefícios por nível, registrar uso, expirar | 2 dias |
| `services/universo_ligo_tree.py` (novo) | Calcular árvore (nível 1 + nível 2), cachear em `tree_index` | 1 dia |
| `services/universo_ligo_scheduler.py` (novo) | Job diário: refresh-all scores + detectar milestones + trigger Pâmela | 1 dia |
| `services/isabella_relationship.py` (plug) | Acoplar `universo_ligo_contextual_pitch` ao fluxo Isabella WA (já existe, só não está plugado) | 0.5 dia |
| `services/pamela_relationship.py` (novo) | Pâmela 2.0 — celebra marcos, parabeniza, agradece, comunica nível-up | 3 dias |
| `services/presidente_universo_kpis.py` (novo) | KPIs executivos: receita gerada/protegida via Universo, % base por nível, ROI por agente | 2 dias |

**Total esforço serviços:** ~10.5 dias-dev.

---

## 9. APIs — V1

### 9.1 Novas
```
GET  /api/universo-ligo/me                              # próprio cliente vê seu perfil + árvore
GET  /api/universo-ligo/tree/{subscriber_id}            # árvore com nomes blurred (anti-doxx)
GET  /api/universo-ligo/benefits/{subscriber_id}        # benefícios desbloqueados
POST /api/universo-ligo/benefits/{benefit_id}/redeem    # usar benefício
GET  /api/universo-ligo/milestones/{subscriber_id}      # marcos do cliente
POST /api/universo-ligo/milestones/{id}/celebrate       # marca como comunicado (Pâmela usa)
GET  /api/universo-ligo/admin/level-config              # gestor edita config dos níveis
PUT  /api/universo-ligo/admin/level-config              # idem
GET  /api/universo-ligo/admin/distribution              # distribuição executiva (Presidente IA)
POST /api/universo-ligo/admin/refresh-all               # já existe — só plugar no scheduler
```

### 9.2 Refator
```
GET /api/universo-ligo/score/{subscriber_id}            # adicionar tree_counts + benefits_unlocked
GET /api/universo-ligo/levels                           # retornar 6 níveis NOVOS (Explorador→Embaixador)
```

### 9.3 Mantém intactas
Todas as 26 rotas de `referrals.py`. **Já cobrem indicação direta + indireta + tier + goal + streak.**

---

## 10. MIGRAÇÃO — V1

### 10.1 Sequência segura (3 fases)
```
FASE A · Schema + Config (não-disruptiva, 1 dia)
  1. Seed `universo_ligo_levels` com 6 níveis novos (Explorador→Embaixador)
  2. Add fields em subscribers (universo_score, level_key, referral_code, etc.)
  3. Backfill referral_code em todos os 26.851 subscribers (idempotente)
  4. Criar índices: subscribers.referral_code (unique), .universo_score (-1)

FASE B · Migração dados existentes (4 dias)
  5. universo_ligo_scores: rename `level_key` antigo → novo (explorador OK,
     cometa→viajante, orbita→cometa, estelar→constelacao,
     galaxia_ouro→galaxia, universo_ligo→embaixador)
  6. Migrar indicacao_leads → referrals (deduplica por phone+document)
  7. Migrar indicacao_credits → referral_rewards
  8. Migrar loyalty_opportunities → isabella_commander_opportunities (status=expired se >7d)
  9. Job refresh-all: calcular score em todos os 26.851 subscribers
     (paralelo, batches de 500, prevê 30-60min de execução)
 10. Construir tree_index pra todos os clientes com indicação

FASE C · Plug & Communications (3 dias)
 11. Plugar isabella_relationship.universo_ligo_contextual_pitch no fluxo WA
 12. Adicionar bloco === UNIVERSO LIGO STATUS === ao contexto da Isabella
 13. Reescrever pamela_v2.md → pamela_v3.md (cobrança vira módulo, persona
     principal vira relacionamento)
 14. Scheduler diário: detectar milestones + trigger Pâmela
 15. Presidente IA: adicionar bloco "Universo Ligo" no briefing
```

### 10.2 Rollback
- Manter `level_key` antigo num campo `level_key_legacy` por 30 dias.
- Backfill: `referral_code` é unique mas nullable → seguro deletar campo se necessário.
- Pamela: manter `pamela_v2.md` em produção até v3 passar em smoke test.
- Feature flag `USE_UNIVERSO_LIGO_V1=0/1` no `.env` — controle de rollout.

---

## 11. PLANO DE ROLLOUT — V1

| Semana | Entregável | Dono | Critério de saída |
|---|---|---|---|
| **S1** | Audit, modelo de dados, seed de níveis novos, backfill referral_code | Backend dev | 26k subscribers com referral_code, 6 níveis em DB |
| **S2** | Refator universo_ligo.py (níveis), refresh-all em massa, tree_index | Backend dev | 100% subscribers com score, 100% árvore calculada |
| **S3** | Pamela_v3 (relacionamento), benefícios por nível, scheduler de milestones | Backend dev + Prompt eng | Pamela dispara 1ª mensagem de parabéns em preview |
| **S4** | Isabella v14 (status no contexto), front cliente conectado, Presidente IA briefing | Full-stack | Cliente vê nível + árvore + benefícios no app |
| **S5** | Soft launch — 10% da base, monitorar churn + indicação | Full team | KPIs estáveis · zero P0 |
| **S6** | Full rollout | Full team | 100% base · ativar campanhas de comunicação Pamela |

**Total: 6 semanas (42 dias).** Pode comprimir pra 4 semanas com 2 devs full-time.

---

## 12. RISCOS

| # | Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|---|
| 1 | Refresh-all em 26k subscribers trava DB | Média | Alto | Batches de 500, throttle, rodar em horário noturno |
| 2 | NPS table vazia → score continua subdimensionado | **Alta** | Alto | Criar fluxo de coleta de NPS via WA (Pamela após reparo) |
| 3 | Pamela v3 começa parabenizando cliente errado | Média | Alto | Dry-run em sandbox, opt-in flag, taxa máx 100/dia primeira semana |
| 4 | Isabella v14 quebra contrato (bolhas, markers) | Baixa | Médio | Red-team script existente (`red_team_isabella.py`) com 20+ cenários |
| 5 | Indicação genera fraude (auto-indicação) | Média | Médio | CPF/phone match + análise por device fingerprint (já existe `_is_valid_cpf`) |
| 6 | Cliente confunde "Embaixador" (status) vs "Embaixador" (cargo Ligo) | Baixa | Baixo | Copy clara no app + ícone único |
| 7 | Migração `loyalty_*` perde dados históricos | Baixa | Alto | Cópia em `loyalty_legacy_2026_06_archive` antes de drop |
| 8 | Tree calculation custo Mongo cresce | Média | Médio | TTL 7 dias no tree_index + recalculo incremental |

---

## 13. GANHO ESTIMADO (cálculo honesto, sem ficção)

> **Premissas:** 26.851 subscribers ativos · ARPU mediano ISP Brasil R$ 90 · churn médio ISP regional 1.5%/mês = ~18%/ano · referência: Cogeco, Brisanet, Desktop Sigmanet em RI.

### 13.1 Indicação
| Cenário | Indicações/ano | Conversão | Novos clientes | LTV 24m × ARPU | Receita 24m |
|---|---|---|---|---|---|
| Baixo (5% base) | 1.342 | 25% | 336 | R$ 2.160 | **R$ 726k** |
| Médio (8% base) | 2.148 | 30% | 644 | R$ 2.160 | **R$ 1.39M** |
| Alto (12% base) | 3.222 | 35% | 1.128 | R$ 2.160 | **R$ 2.44M** |

**Custo do programa:** ~R$ 60/indicação convertida (R$50 + R$10 indireto + ~R$5 operacional) = **margem 97%+**.

### 13.2 Retenção
| Cenário | Redução churn (pp/ano) | Clientes retidos | LTV 12m × ARPU | Receita protegida 12m |
|---|---|---|---|---|
| Baixo | 0.5pp | 134 | R$ 1.080 | **R$ 145k** |
| Médio | 1.5pp | 402 | R$ 1.080 | **R$ 434k** |
| Alto | 3.0pp | 805 | R$ 1.080 | **R$ 870k** |

### 13.3 ARPU expansion (Ligo+ TV/Música/Filmes)
| Cenário | Penetração 12m | Clientes | +ARPU/mês | Receita 12m |
|---|---|---|---|---|
| Baixo | 5% | 1.343 | R$ 10 | **R$ 161k** |
| Médio | 10% | 2.685 | R$ 12 | **R$ 387k** |
| Alto | 18% | 4.833 | R$ 15 | **R$ 870k** |

### 13.4 Total potencial 12 meses
- **Cenário Baixo:** R$ 726k + R$ 145k + R$ 161k = **R$ 1.03M**
- **Cenário Médio:** R$ 1.39M + R$ 434k + R$ 387k = **R$ 2.21M**
- **Cenário Alto:** R$ 2.44M + R$ 870k + R$ 870k = **R$ 4.18M**

**Investimento (6 semanas, 2 devs + 1 prompt eng):** ~R$ 90k.
**Payback:** 2-4 meses (cenário médio).

---

## 14. ENTREGÁVEIS — STATUS

| # | Entregável (ordem CEO) | Onde está |
|---|---|---|
| 1 | Auditoria completa | ✅ Este documento (seções 1–6) |
| 2 | Modelo de dados | ✅ Seção 7 |
| 3 | Serviços | ✅ Seção 8 |
| 4 | APIs | ✅ Seção 9 |
| 5 | Migração | ✅ Seção 10 |
| 6 | Plano de rollout | ✅ Seção 11 |
| 7 | Riscos | ✅ Seção 12 |
| 8 | Ganho financeiro estimado | ✅ Seção 13.1 + 13.3 + 13.4 |
| 9 | Ganho de retenção estimado | ✅ Seção 13.2 |
| 10 | Ganho de indicação estimado | ✅ Seção 13.1 |

---

## 15. PRÓXIMO PASSO — AGUARDA AUTORIZAÇÃO CTO

Esta é a **Fase 0 (Auditoria)**. Ainda **não toquei em código**.

Para iniciar a **Fase A (Schema + Config — 1 dia)**, preciso da sua autorização explícita:

**VOCÊ AUTORIZA A CONSTRUÇÃO DA FUNDAÇÃO V1?**
- (a) **SIM**, comece pela Fase A (schema + seed dos 6 níveis novos)
- (b) Antes de começar, alinhar X (descreva)
- (c) Mude algo neste plano (descreva)

Sem autorização, fico parado.

---

**Auditor:** CTO Mode · Smart Prov v1
**Última atualização:** 13/Jun/2026
**Próxima atualização:** após primeira autorização
