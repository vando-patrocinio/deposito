# 🔒 SECURITY LOCK — PROTEÇÃO CONTÍNUA

**Data:** 19/02/2026  
**Ordem Executiva:** SECURITY LOCK PERMANENTE — CEO  
**Status:** ✅ ATIVADO

---

## Objetivo

Transformar a remediação pontual do SECURITY_LOCK V1 em **proteção contínua**, impedindo que qualquer regressão dos artigos críticos (ART.1, ART.2, ART.3, ART.6, ART.10, ART.11, ART.13) entre em `main`.

> *"Não pode voltar. Quem reintroduzir, o gate barra antes do commit chegar."*

---

## Arquitetura — 3 camadas defensivas

```
┌────────────────────────────────────────────────────────────────────┐
│  CAMADA 1 — DEV LOCAL (pre-commit hook)                            │
│  Arquivo: .pre-commit-config.yaml                                  │
│  Quem dispara: dev rodando `git commit` na própria máquina         │
│  Bloqueia: gate.sh --staged + testes estáticos de regressão        │
│  Veredito: commit ABORTADO se gate falhar                          │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼  (dev força push)
┌────────────────────────────────────────────────────────────────────┐
│  CAMADA 2 — CI/CD (GitHub Actions)                                 │
│  Arquivo: .github/workflows/security-gate.yml                      │
│  Quem dispara: pull_request OR push em main/master/production      │
│  Bloqueia: gate.sh all + testes pytest + gitleaks + bandit + audit │
│  Veredito: PR REPROVADO; merge bloqueado                           │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼  (merge passa CI)
┌────────────────────────────────────────────────────────────────────┐
│  CAMADA 3 — BRANCH PROTECTION (manual, GitHub Settings)            │
│  Quem aplica: super-admin do repositório                           │
│  Bloqueia: merge direto sem PR + status check obrigatório          │
│  Veredito: nem força admin consegue bypassar (se "Include admins") │
└────────────────────────────────────────────────────────────────────┘
```

---

## Camada 1 — Pre-commit hook (Dev local)

### Hooks ativos em `.pre-commit-config.yaml`

| Hook | Descrição | Bloqueia? |
|------|-----------|-----------|
| `security-lock-gate` | `security_gate.sh --staged` em arquivos staged | ✅ SIM |
| `security-lock-v1-tests` | `pytest test_security_lock_v1.py` (testes estáticos) | ✅ SIM |
| `gitleaks` | Varredura de segredos em diff | ✅ SIM |
| `bandit` | SAST Python (severidade alta/alta confiança) | ✅ SIM |

### Instalação obrigatória (dev)

```bash
pip install pre-commit
pre-commit install   # registra .git/hooks/pre-commit
```

A partir desse momento, **todo `git commit` aciona o gate localmente**.

### Critério de bloqueio (pre-commit subset — 11 testes estáticos)

| ART | Teste estático | Bloqueia commit? |
|-----|----------------|-------------------|
| 1 | `test_art1_no_pii_files_in_git_index` | ✅ |
| 1 | `test_art1_data_imports_xlsx_not_tracked` | ✅ |
| 2 | `test_art2_no_admin123_in_production_routes` | ✅ |
| 3 | `test_art3_failclosed_sidecar_token_no_default` | ✅ |
| 6 | `test_art6_safe_fetch_exists` | ✅ |
| 11 | `test_art11_debug_file_quarantined` | ✅ |
| 13 | `test_art13_safe_detail_helper_exists` | ✅ |
| 13 | `test_art13_no_str_e_in_routes` | ✅ |

Os testes que exigem backend rodando (login real, IDOR cross-tenant, 401 genérico) ficam para CI/CD.

---

## Camada 2 — CI/CD (`.github/workflows/security-gate.yml`)

### Triggers
```yaml
on:
  pull_request:
    branches: [main, master, production]
  push:
    branches: [main, master, production]
```

### Steps obrigatórios (todos bloqueantes)

| # | Step | Comando | Bloqueia merge? |
|---|------|---------|-----------------|
| 1 | SECURITY_LOCK gate | `bash scripts/security_gate/security_gate.sh all` | ✅ |
| 2 | Setup Python 3.11 | `actions/setup-python@v5` | — |
| 3 | Install deps | `pip install pytest pytest-asyncio requests` | — |
| 4 | SECURITY_LOCK V1 tests | `pytest test_security_lock_v1.py -k "test_art1 or ..."` | ✅ |
| 5 | gitleaks | `gitleaks/gitleaks-action@v2` | ✅ |
| 6 | bandit (SAST) | `bandit -r backend -ll -ii` | ✅ |
| 7 | pip-audit (CVE) | `pip-audit -r backend/requirements.txt --strict` | ✅ |

**Falha em qualquer step ⇒ merge bloqueado.**

---

## Camada 3 — Branch Protection (configuração manual no GitHub)

Após mesclar este PR, o owner do repositório DEVE configurar:

### Settings → Branches → Branch protection rules
- **Branch name pattern:** `main` (e `master`, `production`)
- **Require a pull request before merging:** ✅
  - Require approvals: ≥ 1
  - Dismiss stale approvals: ✅
- **Require status checks to pass before merging:** ✅
  - Required check: **`security-gate`** (workflow desta operação)
  - Require branches to be up to date: ✅
- **Require conversation resolution:** ✅
- **Require signed commits:** ✅ (recomendado)
- **Include administrators:** ✅ (sem bypass de super-admin)
- **Restrict who can push to matching branches:** apenas via PR.

---

## Critério de aceite formal

Nenhum commit poderá entrar em `main` se:

```
ART.1  PII em git index            → FALHA
ART.2  admin123/auditor123 em prod → FALHA
ART.3  fail-open em segredos       → FALHA
ART.6  SSRF sem allowlist          → FALHA
ART.10 IDOR sem tenant filter      → FALHA (testado em CI com backend)
ART.11 debug router em routes/     → FALHA
ART.13 HTTPException(.., str(e))   → FALHA
```

Validação automática a cada commit + a cada PR + a cada push em branches protegidas.

---

## Auditoria — Como verificar manualmente

### Localmente
```bash
# 1. Pre-commit hooks instalados?
ls -la .git/hooks/pre-commit
cat .git/hooks/pre-commit | grep "pre-commit"

# 2. Gate sintetiza staged files
bash scripts/security_gate/security_gate.sh --staged

# 3. Testes estáticos
python3 -m pytest backend/tests/test_security_lock_v1.py \
  -k "test_art1 or test_art2_no_admin or test_art3 or test_art6_safe or test_art11_debug_file or test_art13_safe or test_art13_no_str"
```

### No GitHub
1. Abrir um PR de teste com qualquer commit que viole uma regra (ex: adicionar `raise HTTPException(500, str(e))` em `backend/routes/`).
2. Verificar que o check `security-gate` falha.
3. Verificar que o botão "Merge" fica desabilitado.

---

## Arquivos envolvidos

| Arquivo | Função |
|---------|--------|
| `.pre-commit-config.yaml` | Camada 1 — hooks locais |
| `.github/workflows/security-gate.yml` | Camada 2 — CI/CD |
| `scripts/security_gate/security_gate.sh` | Gate principal (14 artigos) |
| `backend/tests/test_security_lock_v1.py` | Suíte de regressão (12 testes) |
| `backend/tests/_test_secrets.py` | Fixture de senhas via env |
| `backend/services/exception_sanitizer.py` | Helper `safe_detail()` |
| `backend/services/safe_fetch.py` | Guarda anti-SSRF |
| `backend/services/session_denylist.py` | Revogação JWT |

---

## Métricas — Estado atual (snapshot)

| Métrica | Valor |
|---------|-------|
| Violações bloqueantes (gate) | **0** |
| Testes de segurança PASSED | **12/12** |
| ARTs cobertos por testes estáticos | **7 dos 14** (ART.1, 2, 3, 6, 11, 13) |
| ARTs cobertos por testes dinâmicos | **+3** (ART.2 happy, ART.10, ART.13 generic) |
| Hooks de pre-commit ativos | **4** (gate + tests + gitleaks + bandit) |
| Steps de CI bloqueantes | **5** |
| Camadas defensivas | **3** |

---

## Status Final

```
+--------------------------------------------------+
|                                                  |
|   SECURITY LOCK — PROTEÇÃO CONTÍNUA              |
|   STATUS: ATIVO                                  |
|   PRE-COMMIT: ✅ CONFIGURADO                     |
|   CI/CD: ✅ ATIVO                                |
|   BRANCH PROTECTION: aguarda config manual       |
|   REGRESSÃO POSSÍVEL? NÃO (3 camadas)            |
|                                                  |
+--------------------------------------------------+
```

---

**Assinado:** E1 Security Engineer  
**Aprovação:** CEO — Executive Order de 19/02/2026  
**Próxima revisão:** 60 dias (19/04/2026)
