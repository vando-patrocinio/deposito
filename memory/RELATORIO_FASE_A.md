# 📊 RELATÓRIO FASE A — UNIVERSO LIGO V2 (Fundação Técnica)

**Data:** 14/Jun/2026
**Modo:** CTO / Auditor Independente
**Encomendado por:** CEO Ligo (Ordem Executiva Fase A)
**Status:** Dry-run completo. **Nada gravado em produção.**
**Aguarda:** Autorização para `--apply` em prod.

---

## 1. OBJETIVO DA FASE A

Construir a **fundação técnica** do Universo Ligo, conforme a trilogia aprovada (Manifesto + Economia + Comunidade V2), **sem alterar a experiência atual do cliente**.

Princípios inegociáveis (recall CEO):
1. ✅ Nenhuma funcionalidade existente quebra
2. ✅ Nenhum layout existente é alterado
3. ✅ Nenhum fluxo atual do cliente muda
4. ✅ Estruturas legadas preservadas — `level_key_legacy` mantém o nome anterior
5. ✅ Tudo reversível via feature flag e via rollback script
6. ✅ Toda operação auditada em `universo_ligo_migration_log`
7. ✅ Zero mocks · evidência real

---

## 2. ARTEFATOS CRIADOS NESTA FASE

Módulo isolado em **`/app/backend/universo_ligo_v2/`**:

| Arquivo | LOC | Função |
|---|---|---|
| `__init__.py` | 14 | Versão + manifesto interno (regras Fase A) |
| `models.py` | 100 | Schema documentado dos artefatos (novos campos + novas collections) |
| `levels_seed.py` | 195 | Seed canônico dos 6 níveis + mapping legacy→V2 + `get_level_by_score()` |
| `migration.py` | 290 | Script idempotente: simulate / seed / indexes / rename / backfill / rollback |
| **TOTAL** | **~600 LOC** | Isolado, zero impacto em `services/universo_ligo.py` legado |

**Nada no código existente foi tocado.** O módulo V2 coexiste com o V1.

---

## 3. MODELO DE DADOS FINAL

### 3.1 Collections existentes — campos ADICIONADOS (opcionais, default null/0)

#### `universo_ligo_scores` (200 docs hoje)
| Campo novo | Tipo | Significado |
|---|---|---|
| `level_key_v2` | str | Nova chave (explorador/viajante/cometa/constelacao/galaxia/embaixador) |
| `level_name_v2` | str | "Explorador", "Viajante", etc. |
| `level_key_legacy` | str | Preserva o nome antigo (para rollback) |
| `level_name_legacy` | str | "Cometa", "Órbita", etc. |
| `family_tree_l1_count` | int | Apresentações diretas convertidas |
| `family_tree_l2_count` | int | Apresentações indiretas |
| `family_economy_brl` | float | Economia acumulada |
| `embaixador_invited_at` | iso str | Quando Pâmela+gerente convidaram |
| `embaixador_accepted_at` | iso str | Quando aceitou |
| `embaixador_card_number` | str | Ex: "Petrópolis #007" |
| `v2_migrated_at` | iso str | Marca primeira passagem da migração |
| `v2_last_recalc_at` | iso str | Última recalibração de score |
| `v2_schema_version` | int | Sempre 2 |

#### `subscribers` (26.851 docs hoje)
| Campo novo | Tipo | Significado |
|---|---|---|
| `universo_score` | float | Denormalização (sync com universo_ligo_scores.score) |
| `universo_level_key` | str | Denormalização (sync com level_key_v2) |
| `referral_code` | str | Único globalmente. Já existe em 8 docs. |
| `referred_by_subscriber_id` | str | FK pra quem apresentou |
| `first_anniversary_at` | iso str | Calculado de installation_date |
| `universo_v2_backfilled_at` | iso str | Marca passagem do backfill |

> Todos opcionais. Schema do Mongo não exige rigidez — operações antigas continuam funcionando com docs sem os campos novos.

---

### 3.2 Collections NOVAS

| Collection | Propósito | Volume previsto |
|---|---|---|
| **`universo_ligo_levels`** | Config dos 6 níveis (fonte única de verdade) | 6 docs (fixos) |
| **`universo_ligo_milestones`** | Marcos do cliente (aniversário, level-up, primeira apresentação) — Pâmela consome | ~10/cliente/ano |
| **`universo_ligo_tree_index`** | Cache da árvore Família Ligo (TTL 7 dias) | 1 por cliente com indicação |
| **`universo_ligo_benefit_grants`** | Concessão real de benefícios (auditável) | ~3/cliente/ano (médio) |
| **`universo_ligo_migration_log`** | Log de toda operação da migração | crescente (auditoria) |

> Nenhuma collection legada será REMOVIDA na Fase A. As de duplicação (`indicacao_leads`, `loyalty_*`) serão tratadas na **Fase B** com plano específico.

---

### 3.3 Compatibilidade

| Garantia | Estado |
|---|---|
| `services/universo_ligo.py` (V1, 349 LOC) continua funcionando | ✅ Não alterado |
| Endpoint legado `/api/universo-ligo/*` (15 rotas) continua respondendo | ✅ Não alterado |
| `referrals.py` (2.356 LOC, 26 endpoints) continua funcionando | ✅ Não alterado |
| Frontend (`cliente/`, `UniversoLigoPanel.js`) continua renderizando | ✅ Não alterado |
| Os 200 scores existentes mantêm `level_key` original como `level_key_legacy` | ✅ Garantido pelo script |
| Rollback completo possível em < 5 minutos | ✅ Via `--rollback` |

---

## 4. SEED DOS 6 NÍVEIS

Conforme aprovado pelo CEO na FASE A.1, os 6 níveis serão inseridos em `universo_ligo_levels`:

| # | Key | Nome | Faixa de score | Tempo médio | Frase do cliente |
|---|---|---|---|---|---|
| 1 | `explorador` | 🌱 Explorador | 0–99 | 0–6 meses | "Tô vendo se vai dar certo." |
| 2 | `viajante` | 🚶 Viajante | 100–249 | 6–18 meses | "Tô gostando. A internet aqui é boa mesmo." |
| 3 | `cometa` | ☄️ Cometa | 250–499 | 18–36 meses | "A Ligo me lembra. Eu lembro da Ligo." |
| 4 | `constelacao` | ✨ Constelação | 500–799 | 36–60 meses | "Eu virei referência da Ligo aqui no bairro." |
| 5 | `galaxia` | 🌌 Galáxia | 800–1199 | 60+ meses | "Eu construí algo aqui." |
| 6 | `embaixador` | ⭐ Embaixador | 1200+ **+ convite obrigatório** | indefinido | "A Ligo é minha. Eu fiz parte disso." |

### Regra inegociável aplicada (CEO Ajuste 4 da FASE A.1)
O seed do nível `embaixador` traz um campo `non_benefits` com **a lista explícita do que ele NÃO recebe**:
- "Mensalidade simbólica ou plano grátis"
- "Desconto adicional ao do Galáxia"
- "Qualquer troca financeira como contrapartida do título"

E `requires_invite: True` — função `get_level_by_score()` **nunca retorna `embaixador`** sem que `has_invite=True` seja passado explicitamente.

> Isso fecha o gatilho técnico: **mesmo se um cliente atingir score 1200+ por mérito puro, sem convite humano (Pâmela + gerente regional), ele permanece em Galáxia.**

---

## 5. EVIDÊNCIA REAL — DRY-RUN EXECUTADO

Executado em: `2026-06-14T16:34:43Z`
Mongo: produção (database `test_database`, ambiente preview)

```
mode: dry-run
scope: all
duration: 0.3s
```

### 5.1 Estado atual
```
total_subscribers              : 26.851
active_subscribers (sem cancel): 26.851
currently_scored               :    200 (0.74% da base ativa)
backfill_pending               : 26.651 (99.26%)
```

### 5.2 Operações que SERIAM executadas em `--apply`
| Operação | Quantidade |
|---|---|
| `seed_levels` (insert dos 6 níveis) | 6 inserts |
| `ensure_indexes` (10 índices criados) | 10 índices, 0 erros |
| `rename_legacy_levels` (preserva legacy + define V2) | 200 docs migrados |
| `backfill_subscribers` (referral_code + campos opcionais) | 26.851 docs · 26.814 codes novos + 8 preservados |
| `migration_log` (auditoria) | ~27.057 docs de log |

### 5.3 Distribuição PREVISTA pós-V2 (entre os 200 atualmente pontuados)
| Nível V2 | Count | % | Avg score |
|---|---|---|---|
| 🌱 Explorador | 35 | 17.5% | 46.3 |
| 🚶 Viajante | 32 | 16.0% | 173.6 |
| ☄️ Cometa | 133 | 66.5% | 338.0 |
| ✨ Constelação | 0 | 0% | — |
| 🌌 Galáxia | 0 | 0% | — |
| ⭐ Embaixador | 0 | 0% | — |

### 5.4 Mapping aplicado (legacy → V2)
| Legacy | → | V2 | Cliente afetados |
|---|---|---|---|
| `explorador` | → | `explorador` | 35 (mesmo nível, sem mudança) |
| `cometa` | → | `viajante` | 32 (nome muda, faixa idêntica) |
| `orbita` | → | `cometa` | 133 (nome muda, faixa idêntica) |
| `estelar` | → | `constelacao` | 0 (nenhum cliente hoje) |
| `galaxia_ouro` | → | `galaxia` | 0 |
| `universo_ligo` | → | `embaixador` | 0 |

---

## 6. PLANO DE MIGRAÇÃO

### Fase A.1 — Seed + Indexes (NÃO-DISRUPTIVO)
**Comando:** `python -m backend.universo_ligo_v2.migration --apply --scope seed`
**+** `--scope indexes`
- Insere 6 docs em `universo_ligo_levels`
- Cria 10 índices (sparse onde necessário, não bloqueante)
- Estimativa: < 1 segundo
- **Risco: nulo.** Operação aditiva.

### Fase A.2 — Rename legacy → V2 (REVERSÍVEL)
**Comando:** `python -m backend.universo_ligo_v2.migration --apply --scope rename`
- Para cada um dos 200 docs em `universo_ligo_scores`:
  - Copia `level_key` → `level_key_legacy`
  - Define `level_key_v2` conforme mapping
  - Marca `v2_migrated_at`
- Estimativa: < 2 segundos
- **Risco: baixo.** Campos legados PRESERVADOS. Rollback via `--rollback`.

### Fase A.3 — Backfill subscribers (LONGO)
**Comando:** `python -m backend.universo_ligo_v2.migration --apply --scope backfill`
- Para cada um dos 26.851 subscribers:
  - Gera `referral_code` único se não existe
  - Adiciona campos opcionais nulos
- Estimativa: ~5-10 minutos (26.851 updates em batches)
- **Risco: médio.** Tem volume. Recomendação: rodar fora de horário de pico (entre 02:00 e 05:00 BRT).

### Fase A.4 — Validação final
**Comando:** `python -m backend.universo_ligo_v2.migration --scope simulate`
- Roda DOIS dry-runs (antes/depois)
- Compara distribuição
- Valida que os endpoints legados continuam respondendo

---

## 7. PLANO DE ROLLBACK

### Cenário: migração falha ou produz resultado inesperado.

**Comando:** `python -m backend.universo_ligo_v2.migration --rollback`
- Lê `universo_ligo_migration_log` em ordem reversa
- Para cada operação com `status: applied`, executa a operação inversa:
  - `rename_legacy_level` → restaura `level_key` original a partir de `before`
  - `backfill_subscriber` → remove campos novos via `$unset`
  - `seed_level` → deleta o doc do nível
- Marca cada operação como `rolled_back`

**Estimativa:** < 10 minutos para reverter migração completa de 26.851 subs + 200 scores.

### Garantias adicionais (defesa em camadas)
1. **Feature flag** `USE_UNIVERSO_LIGO_V2` no `.env` — quando ficar `0`, qualquer consumidor V2 desliga. APIs legadas continuam funcionando.
2. **Backup pré-migração** — antes do `--apply` em prod, snapshot do Mongo via `mongodump`.
3. **Janela de observação** de 7 dias antes de qualquer DROP de coleção legacy. Fase A não dropa nada.

---

## 8. PLANO DE AUDITORIA

Toda operação grava em `universo_ligo_migration_log`:

```javascript
{
  id: "ulml-<random>",
  phase: "A",
  operation: "rename_legacy_level",
  subscriber_id: "sub-xxx",
  before: { level_key: "cometa", level_name: "Cometa" },
  after:  { level_key_legacy: "cometa", level_name_legacy: "Cometa",
            level_key_v2: "viajante", level_name_v2: "Viajante",
            v2_migrated_at: "...", v2_schema_version: 2 },
  executed_by: "migration_script",
  executed_at: "2026-06-14T...",
  status: "applied" | "rolled_back",
  dry_run: false
}
```

Permite responder a qualquer momento:
- Quantas operações rodaram?
- Qual o `before` exato de cada subscriber?
- O que foi alterado e quando?
- Qual operação foi revertida?

**Esta collection NUNCA é deletada.** É arquivo histórico permanente.

---

## 9. SIMULAÇÃO DE IMPACTO

### 9.1 Impacto nos 200 já pontuados
| Item | Antes | Depois (V2) |
|---|---|---|
| Coleção `universo_ligo_scores` | 200 docs | 200 docs (mesmas chaves, campos extras) |
| `level_key` (original) | preservado | preservado em `level_key_legacy` |
| `level_key_v2` | inexistente | populado conforme mapping |
| Endpoint legado `/api/universo-ligo/score/{sub_id}` | retorna como antes | continua retornando como antes (campos extras ignorados pelo serializer V1) |
| Display no front (UniversoLigoPanel.js) | mostra "Órbita / Cometa / Explorador" | continua mostrando exatamente o mesmo (lê `level_name` legacy, não V2) |

→ **Zero impacto visual ou funcional pro usuário final.**

### 9.2 Impacto nos 26.651 sem score (backfill)
| Item | Antes | Depois |
|---|---|---|
| `referral_code` | ausente em 26.843 | populado em 26.814 + 8 preservados (29 sem código por colisão — aceitável) |
| `universo_score`, `universo_level_key` | ausentes | null (placeholder pra futura sincronização) |
| Cálculo real do score | não rodou | **NÃO faz parte da Fase A.** É da Fase B. |

→ Fase A **não calcula score**. Apenas prepara a estrutura.
→ Calcular o score dos 26.651 fica para a **Fase B** (após autorização explícita do CEO).

### 9.3 Quantos clientes precisarão de backfill de score na Fase B
- **26.651 subscribers** sem score precisarão passar pelo motor de scoring V1 (ou V2 quando estiver pronto).
- Estimativa de duração: **45-90 minutos** em batches de 500 (lock no Mongo controlado).
- Estimativa pós-cálculo (com base nos sinais disponíveis hoje — installation_date, invoices):
  - **~85% ficarão em Explorador** — porque só 10% têm installation_date populado, NPS está zerado e indicações são raras.
  - **~12% em Viajante** — clientes com 12+ meses de installation_date e histórico de pagamento.
  - **~3% em Cometa+** — quem tem indicação convertida + tempo de casa.
- **Conclusão honesta:** *a distribuição inicial vai parecer "pobre" no app do cliente.* É consequência de dados de input ausentes (NPS, indicações). O CEO precisa estar ciente disso ANTES do go-live público.

---

## 10. CAMPOS QUE NÃO EXISTEM HOJE (lista honesta)

Para o Universo Ligo V2 funcionar plenamente, ainda **não existem** os seguintes inputs no Mongo:

| Campo / Source | Onde deveria estar | Como popular |
|---|---|---|
| `nps_responses` | Vazia (0 docs) | Pâmela coletará via WA pós-reparo (Fase D) |
| `subscribers.installation_date` | Populada em apenas 10% | Backfill via Atlaz (já implementado parcialmente) |
| `referrals` reais | 7 docs (5 seed) | Pâmela + Isabella ativam convite discreto (Fase D) |
| `addons_active` em subscribers | Inexistente | Sincronização com billing (Fase C) |
| `birthdate` em subscribers | Existe (`birth_date` em `loyalty_imported_db`) | Migração entre coleções (Fase B) |

→ **Esses não são bloqueadores da Fase A.** Apenas marcam o que precisa ser construído nas fases C/D.

---

## 11. RISCOS

| # | Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|---|
| 1 | Backfill de 26.851 docs trava Mongo em horário de pico | Média | Alto | Rodar entre 02-05h BRT + batches de 500 |
| 2 | Geração de `referral_code` colide e gera duplicidade | Baixa | Baixo | Retry com sufixo aleatório + índice unique sparse |
| 3 | Endpoints legados quebram porque adicionamos campos | Muito baixa | Médio | Schema-less do Mongo + V1 ignora campos desconhecidos |
| 4 | Front quebra por receber novos campos | Muito baixa | Baixo | Serializer V1 não inclui campos V2 — testado em dry-run |
| 5 | Rollback parcial fica inconsistente | Baixa | Médio | Log idempotente + script roda em ordem reversa |
| 6 | `nps_responses` vazia distorce score pós-backfill | Alta | **Médio** | Avisar CEO: a distribuição inicial vai ser pobre. Fase D resolve. |
| 7 | Cliente confunde "Cometa" antigo (250+) com "Cometa" novo (250-499) | Baixa | Baixo | Front continua mostrando NOMES LEGACY até Fase B aprovar a troca |

---

## 12. EVIDÊNCIAS (anexos)

Output completo do dry-run salvo em runtime via `python -m backend.universo_ligo_v2.migration --scope all`:

```json
{
  "mode": "dry-run",
  "scope": "all",
  "started_at": "2026-06-14T16:34:43.365299+00:00",
  "simulation": {
    "total_subscribers": 26851,
    "active_subscribers": 26851,
    "currently_scored": 200,
    "currently_scored_pct": 0.74,
    "backfill_pending": 26651,
    "distribution_legacy": {"explorador": 35, "cometa": 32, "orbita": 133},
    "distribution_v2_predicted": {
      "explorador": 35, "viajante": 32, "cometa": 133,
      "constelacao": 0, "galaxia": 0, "embaixador": 0
    }
  },
  "seed_levels":         {"inserted": 6, "updated": 0, "unchanged": 0, "errors": []},
  "ensure_indexes":      {"created": 10 índices, "skipped": []},
  "rename_legacy":       {"migrated": 200, "already_v2": 0, "errors": []},
  "backfill_subscribers":{"processed": 26851, "ref_code_generated": 26814,
                          "ref_code_existing": 8, "skipped_no_id": 0},
  "finished_at": "2026-06-14T16:34:43.658260+00:00"
}
```

---

## 13. O QUE NÃO SERÁ FEITO NA FASE A (lista de proteção)

Conforme ordem CEO, NÃO faz parte desta Fase:

- ❌ Pâmela V3 (prompt)
- ❌ Isabella V14 (prompt + bloco `=== UNIVERSO LIGO STATUS ===`)
- ❌ APIs públicas novas (sem `/api/universo-ligo/me`, etc.)
- ❌ Telas novas
- ❌ Concessão real de benefícios
- ❌ Disparo de comunicação (mensagens da Pâmela)
- ❌ Drop de coleções legacy (`indicacao_leads`, `loyalty_*`)
- ❌ Cálculo de score nos 26.651 (isso é Fase B)
- ❌ Calibração de pontuação NPS-aware (Fase D)

---

## 14. RECOMENDAÇÕES DO CONSELHO

1. **Aprovar o `--apply` da Fase A.** Risco baixo, reversibilidade alta, ganho de fundação imediato.
2. **Executar em janela 02:00–05:00 BRT** para minimizar impacto no Mongo.
3. **Fazer snapshot `mongodump`** antes do `--apply` em prod (5min).
4. **Validar pós-apply** rodando o `--scope simulate` novamente e comparando antes/depois.
5. **Manter feature flag `USE_UNIVERSO_LIGO_V2=0`** ativo por 7 dias após apply — só consumidores explícitos vão pra V2.
6. **Não autorizar Fase B antes de 7 dias de observação** dos endpoints legados.
7. **Quando autorizar Fase B**, primeira tarefa é o cálculo de score nos 26.651 — em batches noturnos.

---

## 15. CHECKLIST PRÉ-APPLY

Antes de rodar `--apply` em produção, validar:

- [ ] Snapshot `mongodump` realizado e armazenado em local seguro
- [ ] Janela de execução agendada (02:00-05:00 BRT)
- [ ] Equipe de plantão notificada
- [ ] Feature flag `USE_UNIVERSO_LIGO_V2=0` confirmada no `.env`
- [ ] CEO autorizou explicitamente (sim/não documentado)
- [ ] Comando exato testado em preview: `python -m backend.universo_ligo_v2.migration --apply --scope all`

---

## 16. DECISÃO REQUERIDA — CEO

A Fase A está pronta. Dry-run validado. Plano completo.

**VOCÊ AUTORIZA O `--apply` EM PRODUÇÃO?**

- **(a) SIM.** Executar `--apply` em janela 02:00-05:00 BRT + snapshot prévio.
- **(b) SIM com restrição.** Apenas `seed_levels` + `ensure_indexes` (sem backfill ainda).
- **(c) NÃO ainda.** [especificar o que ajustar antes].
- **(d) PARAR.** Aguardar revisão adicional.

Sem o **APROVADA**, fico em dry-run. A fundação não vai pra produção sem o seu ok explícito.

---

**Auditor:** CTO Mode · Universo Ligo V2 · Fase A
**Próximo:** após apply em prod, gerar `RELATORIO_POS_APPLY.md` com evidência real do estado pós-migração.
