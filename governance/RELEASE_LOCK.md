# 🚦 SmartProv — RELEASE LOCK (V1.0)

> Subordinado a `SYSTEM_CONSTITUTION.md`.
> Define **como** e **quando** mudanças podem entrar em produção.

---

## 1. Princípio Central

**Nenhuma mudança vai para produção sem trilha documental.** Ponto.

---

## 2. Tipos de mudança e seus requisitos

| Tipo | Documenta em | Testes obrigatórios | Aprovação |
|------|-------------|---------------------|-----------|
| **Bug fix funcional** | `CHANGELOG.md` | pytest + smoke test | Agente IA ou CTO |
| **Nova feature** | `CHANGELOG.md` + `PRD.md` | pytest + testing_agent | CTO (explícito) |
| **Mudança de schema** | `DECISIONS.md` (ADR) + `DATABASE_LOCK.md` | migration test | CTO (explícito) |
| **Mudança arquitetural** | `DECISIONS.md` (ADR) + `ARCHITECTURE.md` | bateria completa | CTO (explícito) |
| **Emenda constitucional** | `SYSTEM_CONSTITUTION.md` + `DECISIONS.md` | n/a | CTO `[CONSTITUTION-AMEND]` |
| **Doc/governança** | apenas em `/app/governance/` ou `/app/releases/` | n/a | Agente IA pode |

---

## 3. Workflow de Release

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  1. CODE    │ →  │  2. TEST    │ →  │  3. DOC     │ →  │  4. APPLY   │
│  cirúrgico  │    │  pytest     │    │  CHANGELOG  │    │  git commit │
│             │    │  + smoke    │    │  + ADR if   │    │  +          │
│             │    │  test       │    │  needed     │    │  PUSH TO    │
│             │    │             │    │             │    │  GITHUB     │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
       ↑                                                        │
       │                                                        │
       └─── Se algo falhar: ROLLBACK (item 5)  ←─────────────────┘
```

---

## 4. Critérios de "Pronto para Release"

Antes de declarar uma mudança como completa, **todos** os itens abaixo devem ser verdade:

- [ ] `pytest` rodou e passou (subset relevante OU bateria completa).
- [ ] Smoke test HTTP (preview URL responde 200).
- [ ] Sem erros novos em `/var/log/supervisor/backend.err.log`.
- [ ] `CHANGELOG.md` atualizado.
- [ ] Se schema/arq mudou: `DECISIONS.md` atualizado.
- [ ] Se rota nova: validado contagem `156 → 156+N` no `server.py`.
- [ ] Se tab nova no frontend: validado em `App.js NAV_GROUPS`.
- [ ] Se collection nova: registrada em `DATABASE_LOCK.md` item 2.
- [ ] `test_credentials.md` atualizado se houve mudança de auth.

---

## 5. Procedimento de Rollback

### 5.1 — Rollback de código (working tree)

```bash
# Se a mudança ainda não foi commitada
git stash

# Se a mudança já foi commitada (último commit)
git reset --soft HEAD~1     # mantém arquivos
# OU
git revert HEAD             # cria commit de reversão (preferido)
```

### 5.2 — Rollback via stash

```bash
git stash list                          # listar (10 stashes preservados em 2026-06-09)
git stash show --stat stash@{N}         # inspecionar
git stash apply stash@{N}               # aplicar SEM dropar (recomendado)
git stash pop stash@{N}                 # aplicar E dropar (só se 100% certo)
```

### 5.3 — Rollback via plataforma (Emergent)

- Botão **Rollback** na UI da plataforma (ícone de relógio).
- Selecionar mensagem-alvo no chat.
- Opção "Erase messages only" para preservar código.

### 5.4 — Rollback de schema (Mongo)

⚠️ **GAP**: Não há snapshot binário do Mongo. Rollback de schema atualmente depende de:
- Re-executar migration inversa (se foi scriptada).
- Restaurar collection específica via `mongoexport`/`mongoimport` ad hoc.

**Ação futura obrigatória:** implementar `mongodump` agendado.

---

## 6. Travas Operacionais

### 6.1 — Proibido durante release

- `git stash drop` (sempre `apply` antes de dropar).
- `git push --force`.
- Deleção de pastas raiz (`/app/backend`, `/app/frontend`, `/app/memory`).
- Mudança em `.env` em hot-path sem registro.

### 6.2 — Obrigatório a cada milestone

- "Save to GitHub" (botão da plataforma).
- Tag de versão no formato `vMAJOR.MINOR-fase` (ex: `v9.4-market-validation`).
- Entry em `CHANGELOG.md`.

---

## 7. Gaps Conhecidos (Plano de Mitigação)

| Gap | Severidade | Mitigação atual | Mitigação futura |
|-----|-----------|----------------|------------------|
| Sem snapshot Mongo binário | 🔴 ALTA | Stashes git + backup raw via Drive | Implementar `mongodump` em cron diário |
| Sem CI/CD que ENFORCE locks | 🟡 MÉDIA | Governança escrita | Pre-commit hooks + GitHub Actions |
| Sem código review automático | 🟡 MÉDIA | Revisão manual do agente | PR templates obrigatórios |
| `lint-staged` pode stashar silenciosamente | 🟠 MÉDIA-ALTA | Monitorar `git stash list` ≥1 = alerta | Desabilitar lint-staged OU mover para post-commit hook |
| Testes E2E parciais | 🟡 MÉDIA | pytest backend + screenshot frontend | Playwright suite completa |
| `test_credentials.md` em texto plano | 🟢 BAIXA | Apenas conta de teste demo | Secret manager (futuro) |

---

## 8. Definição de "Feature Freeze" (Fase 9)

Durante a **Fase 9 — Prova de Mercado** vigora regime restritivo:

✅ **Permitido sem aprovação prévia:**
- Bug fixes funcionais (com teste)
- Documentação (governança, ADRs, drafts)
- Telemetria/instrumentação (sem nova UI)
- Whitelist de homologação (`CAUSALITY_PILOT_PHONES`)
- Conectores externos (Zabbix, Grafana) quando credenciais chegarem

❌ **Proibido sem aprovação explícita do CTO:**
- Nova tela ou módulo UI
- Novo agente de IA
- Refatoração "preventiva"
- Renomeação de coleções, rotas, env vars
- Migrações de schema não emergenciais

---

## 9. Checklist Pré-Deploy Produção

Antes de qualquer deploy em ambiente externo:

- [ ] `HOMOLOG_MODE=true` (default failsafe)
- [ ] `CAUSALITY_PILOT_PHONES` populado SOMENTE se whitelist autorizada
- [ ] Stripe em `sk_test_*` ou substituído por chave real autorizada
- [ ] Tokens de ingest (`FLEET_INGEST_TOKEN`, `SECURITY_INGEST_TOKEN`) rotacionados
- [ ] Última entry em `CHANGELOG.md` tem hash do commit
- [ ] `git stash list` salvo em snapshot (caso precise restaurar)
- [ ] "Save to GitHub" executado
- [ ] Smoke test passou no preview ANTES de promover

---

**Versão:** V1.0 — 2026-06-09
