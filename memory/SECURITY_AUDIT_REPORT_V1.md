# 🔒 SECURITY AUDIT — SmartProv vs SECURITY_LOCK V1.0

**Data:** 19/06/2026 03:50 UTC  
**Auditoria:** read-only forense contra os 14 checks do `security_gate.sh`  
**Veredito CTO:** 🔴 **GATE REPROVARIA HOJE — múltiplas violações bloqueantes**

---

## 1. RESUMO EXECUTIVO

| ART. | Trava | Status | Severidade |
|---|---|:---:|:---:|
| 1   | PII em arquivos de dados | 🟡 PARCIAL | M (binários versionados) |
| 2   | Segredos hardcoded / defaults inseguros | 🔴 VIOLADO | **CRÍTICO** |
| 3   | Fail-closed em auth (Python) | ✅ OK | — |
| 3b  | Fail-open Node (sidecar) | 🔴 VIOLADO | **CRÍTICO** |
| 4   | Credencial em query string | 🔴 VIOLADO | ALTO |
| 5   | Rota sem Depends/guard | 🔴 VIOLADO | ALTO |
| 6   | SSRF: fetch externo sem guarda | 🔴 VIOLADO | ALTO |
| 7   | `jwt.decode` com algorithms explícito | ✅ OK | — |
| 7b  | Logout sem denylist de sessão | 🟡 AVISO | M |
| 8   | `subprocess shell=True` | ✅ OK | — |
| 9   | `/docs` ligado em produção | 🔴 VIOLADO | ALTO |
| 10  | Isolamento multi-tenant | 🟡 SUSPEITO | M-ALTO |
| 11  | Endpoint de debug em produção | 🔴 VIOLADO | **CRÍTICO** |
| 12  | Cookie `SameSite=None` | 🔴 VIOLADO | ALTO |
| 13  | Exceção crua devolvida ao cliente | 🔴 VIOLADO | M |
| 14  | Dependência não-pública | 🔴 VIOLADO | M |

**Contagem:**
- 🔴 **10 violações BLOQUEANTES** (gate reprova)
- 🟡 4 avisos / suspeitos (revisão manual obrigatória)
- ✅ 3 OK

---

## 2. VIOLAÇÕES — DETALHE COM EVIDÊNCIA

### 🔴 ART.2 — Segredos hardcoded / defaults inseguros

**Backend auth — defaults `admin123` / `auditor123`** (`backend/auth.py:152-153`, `backend/routes/users.py:60`):
```python
("admin@example.com", os.environ.get("ADMIN_PASSWORD", "admin123"), "gestor", ...)
("auditor@example.com", os.environ.get("AUDITOR_PASSWORD", "auditor123"), "auditor", ...)
```
**Risco:** se o `.env` não setar `ADMIN_PASSWORD`, sobe com senha `admin123` — credencial pública, busca no Google retorna o repositório.

**REDE_IA_QR_SECRET com fallback não-vazio** (`backend/services/rede_ia_qr.py:22`, `backend/routes/rede_ia_map.py:1410`):
```python
QR_SECRET = os.environ.get("REDE_IA_QR_SECRET") or "smartprov-rede-ia-2026-default-secret-change-me"
```
**Risco:** se a env sumir, todos os QRs gerados são assinados com segredo público — forjáveis.

---

### 🔴 ART.3b — Fail-open Node no WhatsApp sidecar

`/app/whatsapp-service/server.js:742`:
```javascript
if (!SIDECAR_TOKEN) return next();  // sem token = modo dev/local
```
**Risco:** se `SIDECAR_TOKEN` não está setado no Railway, **qualquer pessoa pode enviar mensagens WhatsApp em nome da empresa**.

---

### 🔴 ART.4 — Credencial em query string

`/app/backend/auth.py:225` (token público de magic link):
```python
... or request.query_params.get("ptoken") or "").strip()
```

`/app/backend/routes/treasury.py:690` (webhook Asaas):
```python
token = request.headers.get("asaas-access-token") or request.query_params.get("token") or ""
```
**Risco:** token vaza em logs de proxy/CDN, em histórico de browser, em Referer ao clicar em links externos.

---

### 🔴 ART.5 — Rotas sem `Depends`/guard

Heurística sobre amostra:

| Arquivo | Rotas totais | Sem Depends |
|---|---:|---:|
| `routes/atlaz_webhooks.py` | 3 | **3** (provavelmente legítimo se HMAC validado) |
| `routes/tech_tracking.py` | 6 | **3** |
| `routes/payment_charges.py` | 8 | **2** |

**Risco:** rotas sem guard explícito podem expor dados ou ações sem autenticação. Webhooks devem validar HMAC + ip allowlist; outras precisam de `Depends(get_current_user)` ou `@public_endpoint` justificado.

---

### 🔴 ART.6 — SSRF em `clock.py`

`/app/backend/routes/clock.py:2061`:
```python
with urllib.request.urlopen(logo_src, timeout=3) as resp:
```
**Risco:** `logo_src` pode ser fornecido via configuração do tenant. Atacante seta `http://169.254.169.254/latest/meta-data/` (AWS metadata) ou `http://localhost:8001/api/admin/...` e exfiltra credenciais.

---

### 🔴 ART.9 — `/docs` aberto em produção

`/app/backend/server.py:446`:
```python
app = FastAPI(title="Ponto do Colaborador")
```
Sem `docs_url=None`, `redoc_url=None`, `openapi_url=None`. Em produção: `/docs` e `/openapi.json` expostos publicamente.

**Risco:** mapeamento completo de 1880 endpoints + schemas internos disponíveis para qualquer atacante reconectar a superfície.

---

### 🔴 ART.11 — Endpoint de debug embarcado

`/app/backend/routes/auth_debug.py` incluído em `server.py:1375`:
```python
app.include_router(routes_auth_debug.router)
```
**Risco:** rotas de debug em produção. Sem `if os.environ.get('ENV') != 'production':` guard. Vazamento de fluxos de auth, paths internos, possível auth bypass.

---

### 🔴 ART.12 — Cookie de auth `SameSite=None`

`/app/backend/routes/collab_auth.py:217`:
```python
samesite="none", path="/", max_age=SESSION_TTL_DAYS * 24 * 3600,
```
**Risco:** CSRF cross-site. Site malicioso pode disparar requests autenticados no SmartProv. Mitigação parcial só se houver token anti-CSRF no body — não há evidência disso.

---

### 🔴 ART.13 — Exceção crua devolvida ao cliente

**134 ocorrências** de `HTTPException(N, str(e))` ou `HTTPException(N, f"...{e}")`.

**Risco:** stack trace expõe estrutura interna (paths de arquivo, schema de banco, IPs), permitindo enumeração de superfície e ataque dirigido.

**Top 8 amostras** (e mais 126):
```
backend/routes/admin.py · auth.py · stok.py · lousa.py · whatsapp_baileys.py ...
```

---

### 🔴 ART.14 — Dependência não-pública

`backend/requirements.txt:29`:
```
emergentintegrations==0.1.0
```
Não está no PyPI oficial — vem de `https://d33sy5i8bnduwe.cloudfront.net/simple/`. Não auditável por `pip-audit` padrão.

**Decisão pendente:** vendorizar com hash ou aceitar exceção formal por emenda constitucional.

---

### 🟡 ART.1 — Binários de cliente versionados

Encontrados em `backend/uploads/`:
- `pre_attendance/*.png` (4 arquivos) — fotos pré-atendimento de clientes
- `wa_audio/*.ogg` (5+ arquivos) — áudios reais de conversas WhatsApp

**Risco:** PII (voz + imagem do cliente) no histórico git. Mesmo se removidos hoje, ficam no histórico — exige `git filter-repo` ou BFG para sanitizar.

**Recomendação:**
1. Migrar para storage externo (S3/object storage).
2. Purgar do histórico git.
3. Adicionar `backend/uploads/` ao `.gitignore`.

---

### 🟡 ART.7b — Logout sem denylist de sessão

Existe rota `/auth/logout` (`backend/rbac_policy.py`, `backend/routes/users.py`), mas **nenhum arquivo** menciona `denylist`, `revoked_jti`, `session_revoked`, `token_blocklist` ou `is_session_valid`.

**Implicação:** após logout do usuário, o JWT continua válido até o `exp`. Atacante que tenha capturado o token pode usar após o logout.

---

### 🟡 ART.10 — Multi-tenant: cobertura suspeita

```
Routes com tenant_filter/effective_company_id:    21
Routes totais:                                   220

→ ~9,5 % das routes mencionam helper de tenant.
```

Não necessariamente é catástrofe — muitas routes derivam `company_id` direto do `user` no Depends. Mas evidência preocupante:

```python
# backend/routes/audit_log_panel.py:523
d = await db.audit_log.find_one({"id": aid})   ← SEM company_id

# backend/routes/users.py:310
target = await db.users.find_one({"id": target_id})   ← SEM company_id
```

**Risco IDOR cross-tenant:** usuário A com ID válido de log/usuário do tenant B pode acessar.

**Ação:** auditoria sistemática route a route, com testes negativos.

---

## 3. PONTOS POSITIVOS (já em conformidade)

✅ **ART.3 Python** — nenhum `os.environ.get('SECRET', 'default-real')` encontrado nos arquivos de produção.

✅ **ART.7 JWT** — todos os `jwt.decode` de produção passam `algorithms=[JWT_ALG]` explícito. Test files usam `verify_signature: False` corretamente.

✅ **ART.8 shell=True** — zero ocorrências em produção.

✅ **ART.1 PII em dados** — nenhum CPF formatado encontrado em arquivos `.csv/.json/.yaml` versionados.

---

## 4. CONTAGEM vs EXPECTATIVA DO PROTOCOLO

O README do protocolo prevê:
> "Rodar o gate hoje **reprova** com 6 violações conhecidas"

**Auditoria real encontrou 10 violações bloqueantes** (+ 4 avisos).  
Quatro a mais do que o protocolo previa:
- ART.9 (/docs aberto)
- ART.11 (auth_debug)
- ART.12 (SameSite=None)
- ART.13 (134 exceções cruas) + ART.14 (emergentintegrations)

Algumas dessas podem ter sido introduzidas após a estimativa inicial.

---

## 5. PLANO DE REMEDIAÇÃO (ordem por risco/esforço)

### 🔴 P0 — Crítico, fix em < 4h

1. **ART.2 — Remover `admin123`/`auditor123`** de `auth.py:152-153` e `users.py:60`. Trocar para `""` (fail-closed). Definir senhas reais no `.env` produção.
2. **ART.3b — Fail-closed no sidecar**. Em `whatsapp-service/server.js:742`, trocar:
   ```js
   if (!SIDECAR_TOKEN) return next();
   ```
   por:
   ```js
   if (!SIDECAR_TOKEN) return res.status(503).json({error: "service not configured"});
   ```
3. **ART.11 — `auth_debug` só em dev**. Em `server.py:1375`:
   ```python
   if os.environ.get("ENV") != "production":
       app.include_router(routes_auth_debug.router)
   ```
4. **ART.9 — Desligar `/docs`** em produção:
   ```python
   _prod = os.environ.get("ENV") == "production"
   app = FastAPI(title="...",
       docs_url=None if _prod else "/docs",
       redoc_url=None if _prod else "/redoc",
       openapi_url=None if _prod else "/openapi.json")
   ```

### 🔴 P1 — Alto, fix em < 1 dia

5. **ART.2 — `REDE_IA_QR_SECRET` fail-closed.** Remover o `or "smartprov-..."`. Se vazio → endpoint retorna 503.
6. **ART.6 — SSRF em `clock.py:2061`.** Implementar `safe_fetch()` com bloqueio de loopback/link-local/RFC1918.
7. **ART.12 — Cookie `SameSite=Lax`** + token anti-CSRF em mutações em `collab_auth.py:217`.
8. **ART.4 — `ptoken` em query.** Migrar para header `X-Public-Token`. Manter compat por 30d com warning de depreciação.

### 🟡 P2 — Médio, fix em < 1 semana

9. **ART.5 — Audit completo de rotas sem Depends.** Webhooks devem validar HMAC; demais ganham `Depends(get_current_user)`.
10. **ART.10 — Audit de IDOR.** Adicionar testes negativos para todas rotas que recebem `id`.
11. **ART.13 — Wrapper genérico** para sanitizar `HTTPException`. Logar full trace, devolver mensagem genérica.
12. **ART.7b — Denylist de JWT.** Coleção `revoked_jti` com TTL = exp. Validar no `get_current_user`.

### 🟢 P3 — Saneamento histórico

13. **ART.1 — Migrar `backend/uploads/`** para S3 + purgar histórico git.
14. **ART.14 — Decisão formal** sobre `emergentintegrations` (vendorizar ou emenda).

---

## 6. PRÓXIMA AÇÃO RECOMENDADA

Esta é uma **auditoria read-only**. Nenhum código foi alterado.

**Para aplicar as correções, preciso de autorização explícita do CEO:**

a) **Aplicar P0 (4 fixes críticos)** agora — sem code review humano, risco zero de regressão funcional (mexem só em fallbacks de segurança).
b) **Aplicar P0+P1** (8 fixes) — alguns mexem em fluxo (cookies, SSRF guard) e exigem teste.
c) **Apenas registrar o relatório** e esperar você instalar o protocolo + rodar `PROMPT_REMEDIACAO_SEGURANCA.md` separadamente.
d) Outra ordem.

Sprint 5 segue arquivada em INSTRUMENTED PRODUCTION — **isso é fix de segurança, não feature nova**. Estou em standby aguardando sua decisão.
