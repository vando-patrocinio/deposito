# IAM v2 — Tabela de Decisão sobre Órfãos (ETAPA 2.1 P0)

**Data:** 13/06/2026
**Status:** Aguardando aprovação CTO/Founder por linha.
**Não aplicar nada antes da aprovação.**

---

## Resumo

| Categoria | Quantidade | Risco |
|---|---:|---|
| Colaboradores **órfãos** (sem User) | 6 | médio |
| Users **sem profile_id** | 7 | baixo |
| Emails **duplicados** entre portais | 2 | médio |

## Padrão detectado

Os 6 órfãos compartilham assinatura única:
- `cpf: "ATLAZ-<hex>"` — CPF **fake** com prefixo `ATLAZ-` (import legado do sistema ATLAZ)
- `phone: ""` vazio
- `mobile_access_email: null`
- `has_mobile_access: null`
- `email` real (gmail/empresa)
- `role`: "Técnico (Atlaz)" ou "Serviço Externo · Operação" ou "Reparador Instalador"
- `cargo: tecnico` ou `instalador_reparador`

**Conclusão:** foram criados via import em massa do ATLAZ em 09/05/2026, mas **nunca tiveram User criado pra logar**. Nunca tiveram senha. Nunca acessaram nada.

---

## Tabela P0.1 — Colaboradores órfãos (6)

| # | collaborator_id | name | email | phone | cpf | cargo | role legado | profile_id | active | deactivated_at | created_at | **RECOMENDAÇÃO CTO** | Motivo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `col-dd5d2c1a` | JUNIOR GUIMARAES | juniorjkllg@gmail.com | — | ATLAZ-dd5d2c1a | tecnico | Técnico (Atlaz) | ❌ null | ✅ true | — | 2026-05-09 | **CRIAR_IDENTITY_NOVA** + Membership(profile=Colaborador, status=aguardando_ativacao) | Importado Atlaz, nunca logou, sem CPF real. Criar Identity = `aguardando_ativacao` força ativação por magic-link (ADR-002) antes de poder logar. |
| 2 | `col-f60464f5` | JEFFERSON | cabelinhopolo@gmail.com | — | ATLAZ-f60464f5 | tecnico | Técnico (Atlaz) | ❌ null | ✅ true | **2026-05-10** | 2026-05-09 | **INVESTIGAR + DESATIVAR PRELIMINAR** | `deactivated_at` setado mas `active=true` (estado inconsistente). Há um User órfão chamado Jefferson (cabelinhopolo@gmail.com, role=colaborador, profile=COLABORADOR) que **provavelmente é o mesmo**. **Decisão CTO:** VINCULAR ao User existente OU criar Identity nova? Bug do "coloquei admin e não foi" veio daqui. |
| 3 | `col-f8ec4ad8` | Eddy | eddy@ligotelecom.com | — | ATLAZ-f8ec4ad8 | tecnico | Técnico (Atlaz) | ❌ null | ✅ true | — | 2026-05-09 | **CRIAR_IDENTITY_NOVA** | Mesmo padrão Atlaz. Email corporativo (`@ligotelecom.com`) sugere funcionário ativo — checar com RH se está no quadro. |
| 4 | `col-534cbf3d` | Hudson | linkstarinternet@gmail.com | — | ATLAZ-534cbf3d | tecnico | Técnico (Atlaz) | ❌ null | ✅ true | — | 2026-05-09 | **CRIAR_IDENTITY_NOVA** | Atlaz import. Sem login. |
| 5 | `col-3b827d1b` | WELLINGTON GOMES | tonzaojr.777@gmail.com | — | ATLAZ-3b827d1b | tecnico | Serviço Externo · Operação | ✅ prof-0859304d99 (Colaborador) | ✅ true | — | 2026-05-21 | **CRIAR_IDENTITY_NOVA** com profile herdado | Já tem profile setado no colab — herdar pra Membership. |
| 6 | `col-9dd04f1b` | GEAN FERREIRA | fgean9511@gmail.com | — | ATLAZ-9dd04f1b | instalador_reparador | Reparador Instalador | ✅ prof-0859304d99 (Colaborador) | ✅ true | — | 2026-05-21 | **CRIAR_IDENTITY_NOVA** com profile herdado | Idem. |

### Decisão pendente da sua parte

**Para o item 2 (JEFFERSON):** existe um User `usr-5879f5f087` com mesmo email `cabelinhopolo@gmail.com`. **O que vc decide?**

- **A) VINCULAR** colab `col-f60464f5` → User existente. *Risco:* perpetua o bug histórico de profile dessincronizado.
- **B) MARCAR colab como duplicata, KEEP só o User.** *Risco:* perde dados Atlaz do colab (já estão no User?).
- **C) CRIAR Identity nova fundindo ambos** (Identity inherits do User + traz `cargo/role` do colab via Membership). *Recomendação CTO.*

---

## Tabela P0.2 — Users sem profile_id (7)

| # | user_id | email | name | role legado | collaborator_id | last_login | active | is_super | **RECOMENDAÇÃO** |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `usr-2100548587` | admin@empresa.com | Administrador | auditor | null | **13/06 09:40** | ✅ | ✅ true | Atribuir profile **Auditor** (`prof-51a3f88595`). Conta admin demo. |
| 2 | `usr-741cc95cca` | colaborador@empresa.com | Carlos Almeida | colaborador | col-demo-001 ✅ | **13/06 09:40** | ✅ | — | Atribuir profile **Colaborador** (`prof-0859304d99`). |
| 3 | `usr-5c1f71e2297443` | manusanttos395@gmail.com | EMANUELLE JULIA | gestor | col-f4b6cdc7 ✅ | 12/06 22:51 | null | false | Atribuir profile **Gestão** (`prof-f9ac5a96a9`). `active=null` → normalizar pra `true`. |
| 4 | `usr-25c1f77ed2` | gestor@empresa.com | Gestor | gestor | null | 13/06 01:46 | ✅ | — | Atribuir profile **Gestão**. Conta demo. |
| 5 | `usr-ef496d4e47` | gestorrede@empresa.com | Gestor de Rede | gestor_rede | null | **nunca** | ✅ | — | role="gestor_rede" **não existe** no `VALID_ROLES`. Atribuir profile **Gestão** + corrigir role pra "gestor" no compat layer. |
| 6 | `usr-135cedad81` | admin@example.com | Gestor padrão | gestor | null | 13/06 01:24 | ✅ | — | Atribuir profile **Gestão**. Conta seed. |
| 7 | `usr-e8d15cf8f7` | auditor@example.com | Auditor padrão | auditor | null | **nunca** | ✅ | — | Atribuir profile **Auditor**. Conta seed nunca usada. |

**Recomendação CTO unanime:** atribuir profile derivado do `role` legado (mapping em `iam_v2/permissions_catalog.py::LEGACY_ROLE_PERMISSIONS`). Operação **idempotente** — `python3 scripts/backfill_user_profiles.py --dry-run` (a criar em ETAPA 2.5).

---

## Tabela P0.3 — Emails duplicados entre portais (2)

| # | email | user_id (staff) | user_role | portal duplicate | **RECOMENDAÇÃO** |
|---|---|---|---|---|---|
| 1 | admin@example.com | `usr-135cedad81` | gestor | `fleet_portal_users` | **MERGE** — manter `users` como fonte canônica. Em ETAPA 2.5 Phase 5, o portal user vira `Credential(type=fleet_portal)` da mesma Identity. |
| 2 | admin@empresa.com | `usr-2100548587` | auditor | `fleet_portal_users` | **MERGE** — idem. |

**Nota:** os 2 são contas seed/demo. Risco baixo de PII conflict.

---

## Tabela P0.4 — Resumo executivo de decisões pendentes

| Decisão | Recomendação | Aguardando você |
|---|---|---|
| Órfãos 1, 3, 4, 5, 6 → CRIAR_IDENTITY_NOVA com `aguardando_ativacao` | ✅ default seguro | "OK criar?" |
| Órfão 2 (JEFFERSON) | CRIAR fundindo com User existente (opção C) | "OK opção C?" |
| 7 users sem profile_id → backfill por role | ✅ idempotente | "OK rodar dry-run?" |
| 2 portal duplicates → merge em ETAPA 2.5 | ✅ baixo risco | "OK?" |
| Os 5 colabs com `cpf=ATLAZ-XXX` (fake) → mudar pra `cpf=null` (sparse index) | ✅ remove ruído | "OK?" |
| `gestor_rede` role inexistente → normalizar pra `gestor` | ✅ correção pontual | "OK?" |

---

## Critério de aceite

Para `ready_to_migrate` virar **`true`** precisa:

1. ✅ Aprovação CTO em cada linha desta tabela.
2. ✅ Dry-run aplicado e auditado (P2).
3. ✅ Backup MongoDB feito e validado (P1).
4. ✅ Plano de rollback testado em PREVIEW.

**Estado atual:** **0/4** ✅. NÃO iniciamos migração.
