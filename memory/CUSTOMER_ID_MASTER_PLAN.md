# 🧭 CUSTOMER ID MASTER PLAN — 15/06/2026

> Plano técnico para "Operação Identidade Única". Sai do estado atual (96,44% unificável por document, 0% por external_id Atlaz) para **≥99% unificado em 2 passos idempotentes e reversíveis**.

## 1. Chave mestra recomendada

**`subscribers.id`** (UUID interno SmartProv) é a identidade oficial canônica de todo cliente. **Toda coleção downstream deve referenciar via `subscriber_id`.**

### Justificativa
- Existe em 100% dos subscribers reais; é gerado internamente e estável.
- Independente de mudanças externas no Atlaz (CNPJ/CPF pode ser corrigido, telefone muda, e-mail muda).
- Já é a chave usada por `aihub_wa_messages` (98,75%), `universo_ligo_*` (100%) e `customer_intelligence` (100%).

## 2. Campos auxiliares (vínculos cross-system)

Persistir no documento de `subscribers`:

| Campo | Origem | Cobertura alvo | Uso |
|---|---|---|---|
| `id` (existente) | interno | **100%** | chave mestra |
| `document` (existente) | Atlaz / cadastro | 99,96% (real hoje) | resolver Atlaz, faturas, tickets |
| `atlaz_external_id` (**criar**) | copiar de `loyalty.external_id` (snapshot Ativo mais recente) | 100% (alvo) | JOIN ↔ `subscriber_invoices.subscriber_external_id` (100%) e `tickets.atlaz_external_id` (28%) |
| `phone_e164` (**criar normalizado**) | normalizar `phone`/`phone1` para formato E.164 | ≥98% | JOIN ↔ `aihub_wa_messages.phone` (resolução residual) |
| `atlaz_link_status` | preenchido pelo backfill | 100% | rastreabilidade (linked/no_atlaz_record/no_document_or_test) |

Persistir em coleções downstream (apenas se ausente):

| Coleção | Campo a popular | Origem do JOIN |
|---|---|---|
| `subscriber_invoices` | `subscriber_id` | JOIN por `subscriber_external_id == subscribers.atlaz_external_id` |
| `tickets` | `subscriber_id` | JOIN por `atlaz_external_id == subscribers.atlaz_external_id` (28%) + fallback por nome+document |
| `loyalty_imported_db` (canônico) | `subscriber_id` | JOIN inverso por `(company_id, document)` no snapshot Ativo |
| `aihub_wa_messages` | `subscriber_id` (restante 1,25%) | JOIN por `phone_e164 == subscribers.phone_e164` |

## 3. Índices necessários

```python
# subscribers (essenciais)
("company_id", "document")          # já criado no script v2
("company_id", "atlaz_external_id") # novo
("company_id", "phone_e164")        # novo (após backfill de normalização)

# loyalty_imported_db
("company_id", "document")          # já criado
("company_id", "subscriber_id")     # já criado (vazio hoje)
("company_id", "external_id")       # novo (acelera o JOIN canônico)

# subscriber_invoices
("company_id", "subscriber_id")             # novo
("company_id", "subscriber_external_id")    # acelera JOIN backfill

# tickets
("company_id", "subscriber_id")           # novo
("company_id", "atlaz_external_id")       # acelera JOIN backfill

# aihub_wa_messages
("company_id", "subscriber_id")    # provavelmente já existe
("company_id", "phone")            # provavelmente já existe
```

Todos `background=True`, idempotentes (`create_index` é no-op se existir).

## 4. Plano de migração (3 sprints reversíveis)

### Sprint 1 — Backfill `subscribers.atlaz_external_id` (1 passo · ~30s)
```python
# Para cada (company_id, document) com loyalty Ativo canônico:
#   subscribers.update_one({...}, {"$set": {"atlaz_external_id": loyalty.external_id,
#                                            "atlaz_link_status": "linked",
#                                            "_atlaz_link_at": now,
#                                            "_atlaz_link_by": "identidade_unica_v2"}})
```
**Resultado esperado:** 2.654 subs com `atlaz_external_id` (96,44%) · 98 ficam `no_atlaz_record`.

### Sprint 2 — Backfill `subscriber_id` em `subscriber_invoices` (1 JOIN)
```python
# Para cada invoice em co-demo:
#   sub = subs_by_external[invoice.subscriber_external_id]
#   if sub: invoices.update_one({...}, {"$set": {"subscriber_id": sub.id}})
```
**Resultado esperado:** ≥7.593 invoices com `subscriber_id` (100% dos que têm external_id válido).

### Sprint 3 — Backfill `subscriber_id` em `tickets` (JOIN + fallback nome)
```python
# 1ª passada: por atlaz_external_id (108 tickets · 28%)
# 2ª passada: por document direto se houver
# 3ª passada: por customer_name+phone (requer validação humana antes de aceitar match)
```
**Resultado esperado:** ≥35% canônico automático · resto vai para fila de revisão humana.

## 5. Plano de rollback

Cada Sprint usa o padrão já adotado na Etapa 3:
- Tag `_atlaz_link_by = "identidade_unica_v2"` em todo write.
- Script reverso `--rollback` que faz `$unset` apenas dos campos próprios.
- Nenhum delete físico. Nenhum delete lógico em campos preexistentes.

Comando de rollback (1 linha por sprint):
```bash
python3 scripts/identidade_unica_atlaz.py --rollback           # Sprint 1
python3 scripts/identidade_unica_invoices.py --rollback        # Sprint 2 (a criar)
python3 scripts/identidade_unica_tickets.py --rollback         # Sprint 3 (a criar)
```

## 6. Riscos

| # | Risco | Severidade | Mitigação |
|---|---|---|---|
| R1 | 98 subscribers reais sem snapshot Atlaz ainda | 🟡 médio | Próximo import Atlaz (job externo) recupera; até lá, ficam `no_atlaz_record` mas seguem ativos em todos os outros sistemas internos. |
| R2 | Duplicidade de `loyalty.external_id` em snapshots históricos | 🟢 baixo | Filtramos por `status=Ativo` mais recente; histórico não entra no link canônico. |
| R3 | `tickets.customer_name` fuzzy match (3ª passada) | 🔴 alto | NÃO automatizar — só sugerir match para revisão humana via fila. |
| R4 | Conflito quando subscriber troca de CPF/CNPJ | 🟡 médio | `atlaz_external_id` segura o vínculo mesmo se document mudar. |
| R5 | Performance — bulk_write em coleções grandes (invoices=7.593) | 🟢 baixo | Batches de 1.000, `ordered=False`. Tempo < 60s observado. |

## 7. Esforço estimado

| Sprint | Esforço (dev) | Risco | Reversibilidade |
|---|---|---|---|
| 1. atlaz_external_id em subscribers | 1h | baixo | total |
| 2. subscriber_id em invoices | 1h | baixo | total |
| 3. subscriber_id em tickets (auto + fila humana) | 4h | médio (UI da fila) | total |
| **Total** | **~6h** | — | — |

## 8. Etapas (ordem de execução)

1. ⏳ **Aprovação CTO/CEO** para sair do estado read-only e iniciar Sprint 1.
2. **Sprint 1** — backfill `atlaz_external_id` (já existe script base · adaptar a versão v2).
3. **Sprint 2** — backfill `subscriber_id` em invoices.
4. **Sprint 3a** — backfill auto de `subscriber_id` em tickets via `atlaz_external_id`.
5. **Sprint 3b** — fila humana para tickets sem match Atlaz (UI mínima na Curadoria).
6. **Operação Identidade Única · v1 ENCERRADA** → habilitar `CUSTOMER_INTELLIGENCE_ISABELLA_CONTEXT=true` em `co-demo` com auditoria.

## 9. Resposta sintética às 10 perguntas do critério de aceite

1. **Identidade oficial recomendada:** `subscribers.id` (UUID interno) como chave mestra; `atlaz_external_id` como auxiliar Atlaz; `phone_e164` como auxiliar WA; `document` como cross-check.
2. **Unificáveis hoje:** **2.654 / 2.753 · 96,44%** (por `document` matching loyalty Ativo).
3. **Órfãos hoje:** **99** (98 sem record Atlaz + 1 loyalty órfão).
4. **Fonte mais confiável:** `subscribers.id` (interno, 100%) + `loyalty.external_id` (Atlaz, 100% nos snapshots Ativo) — combinação > qualquer fonte sozinha.
5. **Campo que falta preencher primeiro:** `subscribers.atlaz_external_id` (hoje 0%).
6. **Plano mínimo para sair de 10% → 90%+:** Sprint 1 (1h) eleva para 96,44% direto. Sprint 2 (1h) leva invoices para 100%. Sprint 3a leva tickets para 28% automático. **Total: ~2h de execução real.**
7. **Pode ser feito automaticamente:** Sprints 1, 2 e 3a (≥97% dos casos).
8. **Precisa validação humana:** Sprint 3b (tickets sem chave Atlaz, ~277 docs · revisão por curadoria com UI mínima).
9. **Bloqueadores hoje:** Universo Ligo Phase B, Pamela V3 e Isabella V14 dependem do score `subscriber_id` resolvido → **NÃO BLOQUEIA** (já em 100%). Bloqueador real é UX/contextual: tickets e invoices precisam de FK canônico para Isabella conseguir narrar histórico operacional + financeiro do cliente. Sem Sprint 2 e 3a, Isabella V14 fica cega para histórico de cobrança e suporte.
10. **Próximo passo executável:** aguardar `VOCÊ AUTORIZA?` para Sprint 1 (backfill `subscribers.atlaz_external_id` · ~30s · 2.654 docs · totalmente reversível via `--rollback`).
