# ETAPA 2.1 — Relatório de Entrega (Pre-Migration Clean Room)

**Data:** 13/06/2026
**Status:** ✅ Entregue. Aguardando aprovação CTO por linha.

---

## 1. ENTREGAS

| # | Entrega | Arquivo | Estado |
|---|---|---|---|
| P0 | Tabela de decisão de órfãos | `/app/memory/IAM_ORPHANS_DECISION_TABLE.md` | ✅ |
| P1 | Plano de backup & rollback | `/app/memory/IAM_BACKUP_ROLLBACK_PLAN.md` | ✅ |
| P2 | Dry-run das phases 1-7 (CLI + JSON) | `/app/backend/iam_v2/migrate.py` + `/app/memory/IAM_V2_DRY_RUN_PLAN.json` | ✅ |
| P3 | Matriz de permissões (11 perfis canônicos) | `/app/memory/IAM_PERMISSION_MATRIX.md` | ✅ |
| P4 | Red-team de compatibilidade (9 checagens) | `/app/backend/scripts/test_iam_v2_dry_run.py` | ✅ 9/9 verde |

## 2. RED-TEAM — 9/9 PASSARAM

```
✅  1. USE_NEW_IAM=0 (feature flag desligada)
✅  2. Login legado /api/auth/login funciona (status=200)
✅  3. Phase 0 detecta os 6 órfãos
✅  4a. Dry-run NÃO escreveu nada (users=12→12)
✅  4b. Phases 1-6 retornaram plano estruturado
✅  5. auth.py / rbac_policy.py / access_profiles.py INALTERADOS
✅  6. Nenhum arquivo de produção importa iam_v2 (0 leaks)
✅  7. Pytest regression 10/10 verde
✅  8. Permission catalog íntegro (95 keys, legacy mapping consistente)
```

Baseline de hashes registrado em `/app/memory/.iam_v2_baseline_hashes.json`.

## 3. NÚMEROS DO DRY-RUN (co-demo)

```
Phase 1 (Identities a partir de users):       12 identities a criar, 0 skipped
Phase 2 (Merge colaboradores):                12 identities adicionais por colab, 1 não-matched
Phase 3 (Credentials):                        password=12, magic_link=14, google=0 → 26 total
Phase 4 (Memberships):                        12 memberships, 7 precisam de mapping role→profile
Phase 5 (Portal users):                       8 usuários em 4 portais (2 merge, 6 nova identity) + 3 api_keys
Phase 6 (Sessions):                           4 índices criados, JWT legado expira naturalmente em 30d
```

⚠️ **Phase 2 retorna 12 novos colabs em dry-run pois Phase 1 não escreveu** (identities collection vazia). Em rodada real, Phase 2 detectará Identities criadas pela Phase 1 e fará merge (não criação) na maioria dos casos. **Em execução real: estimativa de 6-8 merges + 4-6 novas (órfãos).**

## 4. RISCOS REMANESCENTES

| Risco | Severidade | Bloqueador ETAPA 2.5? |
|---|---|---|
| Bucket S3 com Object Lock NÃO PROVISIONADO | 🔴 ALTA | **SIM** |
| Operador on-call pra rollback NÃO atribuído | 🟡 média | sim |
| 6 órfãos sem decisão CTO confirmada por linha | 🟡 média | sim |
| 7 users sem profile sem mapping aprovado | 🟢 baixa | sim |
| Jefferson (item 2 da tabela) decisão A/B/C pendente | 🟡 média | sim |
| Dual-write em endpoints legados não implementado | 🟢 baixa (vem na 2.5) | não |
| 2-eyes pra ops críticas (kill_switch/refund>R$1k) não implementado | 🟢 baixa (vem na ETAPA 7) | não |
| `gestor_rede` role inexistente em VALID_ROLES | 🟢 baixa | não (resolvido no shim) |

## 5. CRITÉRIO `ready_to_migrate=true`

Para flippar de `false → true`, **TUDO** abaixo precisa estar ✅:

- [ ] **CTO aprova P0 linha-a-linha** (6 órfãos + 7 users sem profile + 2 portais)
- [ ] **CTO aprova P3** (matriz de permissões dos 11 perfis canônicos)
- [ ] **Bucket S3 `smartprov-backups/` com Object Lock provisionado** (manual)
- [ ] **Backup MongoDB pré-migração feito e validado** (SHA256 + dry-restore OK)
- [ ] **Janela de manutenção PROD agendada** (60min de colchão)
- [ ] **Operador on-call definido** (response < 15min)
- [ ] **Decisão Jefferson (item 2)** definida: A / B / C
- [ ] **Re-rodar `test_iam_v2_dry_run.py`** após aprovações: ainda 9/9 verde

**Score atual: 0/8** ✅. **ETAPA 2.5 bloqueada.**

## 6. RESPOSTA OBJETIVA À ORDEM

> "Estamos prontos para Etapa 2.5?"

### ❌ NÃO

**Por quê (sem mascarar):**

1. Backup S3 enterprise ainda não provisionado — sem isso, rollback é frágil.
2. As 6 decisões de órfãos não foram aprovadas (você precisa marcar A/B/C no item 2 e OK nos itens 1, 3-6).
3. A matriz de permissões dos 11 perfis canônicos precisa do seu OK explícito.
4. Não há operador on-call atribuído pra rollback em 15min.
5. Janela de manutenção PROD não foi agendada.

**O que NÃO falta mais:**
- ✅ Modelagem (ETAPA 2)
- ✅ Pre-migration audit (ETAPA 2.1)
- ✅ Dry-run funcional e reprodutível
- ✅ Red-team verde
- ✅ Hashes baseline travados

**Próxima ação que cabe à CTO (você):**

1. Ler `IAM_ORPHANS_DECISION_TABLE.md` e marcar OK/decisões.
2. Ler `IAM_PERMISSION_MATRIX.md` e aprovar a matriz.
3. Provisionar bucket S3 com Object Lock.
4. Designar operador on-call.
5. Agendar janela.

Quando os 5 estiverem feitos: rodar `python3 scripts/test_iam_v2_dry_run.py` de novo. Se ainda 9/9 verde + ✅ em todos os 8 itens da §5, eu te peço **"VOCÊ AUTORIZA ETAPA 2.5?"** e aí sim começamos a escrever em produção.

Até lá, **FREEZE mantido**.
