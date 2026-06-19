# 🛡️ PROMPT GLOBAL — REMEDIAÇÃO TOTAL + LEI PERMANENTE (SmartProv / tudao)

> **Para:** qualquer agente de IA (Claude Code, Cursor, Copilot, Windsurf) ou
> desenvolvedor que vá tocar este repositório.
> **Natureza:** este documento é **lei suprema** do projeto. Tem duas missões
> que devem ser executadas juntas:
>   1. **CONSERTAR O PASSADO** — eliminar todas as vulnerabilidades já
>      identificadas (Bloco A).
>   2. **TRANCAR O FUTURO** — instalar os portões que impedem que qualquer
>      código novo nasça violando estas regras (Bloco B).
>
> Você não está autorizado a marcar a tarefa como concluída enquanto
> `bash scripts/security_gate/security_gate.sh all` não retornar **APROVADO**.

---

## ⚖️ ARTIGO ZERO — A REGRA QUE GOVERNA TODAS AS OUTRAS

> **FAIL-CLOSED, SEMPRE.** Na ausência de qualquer configuração de segurança
> (segredo, token, chave, assinatura, política, escopo), o sistema **NEGA**.
> Nunca libera "em dev", "por enquanto", "pra não quebrar", "modo local".
>
> Todo `if (!secret) liberar`, todo `os.environ.get("X","default-funcional")`,
> toda validação que é pulada quando o header está ausente — é defeito.
>
> Se, ao executar qualquer item, você se pegar reformulando o pedido para
> torná-lo "aceitável" (um default temporário, um bypass de dev, um TODO de
> proteger depois), **isso é o sinal para PARAR e sinalizar**, não para
> prosseguir. A conveniência nunca vence a regra.

Toda a auditoria deste sistema convergiu para uma causa-raiz: **a segurança foi
feita reativamente, peça por peça, com defaults que liberam.** Os melhores
sistemas fazem o inverso — segurança é propriedade transversal, com defaults
seguros, menor privilégio e revogabilidade. Você vai inverter essa premissa.

---

# BLOCO A — CONSERTAR O PASSADO

Execute na ordem. Cada item: **Problema → Onde → Fazer → Aceite**. Não pule o
aceite.

## A1 · CRÍTICO — PII real de clientes no repositório (LGPD)
- **Onde:** `backend/data_imports/full_contatos.xlsx` (~11.962 nomes/CPF/RG);
  `backend/uploads/wa_transcripts/*.pdf`, `wa_audio/*`, `pre_attendance/*`;
  `data/holerites/`.
- **Fazer:** purgar do histórico Git (`git filter-repo`/BFG, não só `git rm`);
  trocar seeds por dados **sintéticos**; mover uploads para storage externo;
  `.gitignore` recebe `data/`, `backend/uploads/`, `backend/data_imports/*.xlsx`,
  `*.ofx`, `data/holerites/`. Rotacionar qualquer credencial que tenha vazado.
- **Aceite:** gate ART.1 verde; `git log --all -- backend/data_imports/full_contatos.xlsx` sem conteúdo; nenhum CPF real no tree.

## A2 · CRÍTICO — Backdoor `/api/auth/admin-login`
- **Onde:** `backend/routes/users.py:57` (default `admin123`, sem rate limit, sem lockout).
- **Fazer:** **remover** o endpoint. Se houver dependência real, exigir
  `ADMIN_PASSWORD` obrigatória (sem fallback, 503 se ausente) + rate limit +
  lockout + `hmac.compare_digest`.
- **Aceite:** nenhuma rota autentica sem e-mail; nenhuma string `admin123`/`auditor123` no código (gate ART.2 verde).

## A3 · CRÍTICO — Serviço Node do WhatsApp falha aberto
- **Onde:** `whatsapp-service/server.js:742` — `if (!SIDECAR_TOKEN) return next()`.
- **Fazer:** exigir `WA_SIDECAR_TOKEN` em produção; sem ele, recusar subir ou
  responder 503 em todas as rotas. `crypto.timingSafeEqual`. Proteger `/diagnostics`.
- **Aceite:** subir sem token em produção falha; requests sem `Authorization` correto → 401 (gate ART.3 verde).

## A4 · CRÍTICO — Webhook Twilio forjável (fail-open na assinatura)
- **Onde:** `backend/routes/whatsapp_twilio.py:326` — `if sig and not _validate(...)`: pula validação quando o header está ausente; `tenant` vem da query.
- **Fazer:** exigir assinatura **sempre**; ausência de `X-Twilio-Signature` → rejeitar. Derivar o tenant de credencial autenticada, não da query string.
- **Aceite:** request sem assinatura é rejeitado; teste cobre header ausente e tenant forjado.

## A5 · CRÍTICO — Endpoint de debug público com XSS/info-disclosure
- **Onde:** `backend/routes/auth_debug.py` (`/api/auth/debug/whoami`): público, token via `?token=`, devolve payload decodificado, reflete `token[:30]` cru em HTML.
- **Fazer:** **remover** o router do build de produção. Se necessário em dev, condicionar a `ENV != production` E exigir auth; nunca refletir input em HTML; nunca aceitar token na query.
- **Aceite:** `/api/auth/debug/*` retorna 404 em produção (gate ART.11 verde).

## A6 · ALTO — Contas seed com senha fraca recriadas a cada boot
- **Onde:** `backend/auth.py:~145-152` (`123456`, `admin123`, `auditor123`).
- **Fazer:** seed só sob flag explícita `SEED_DEMO_DATA=true` (nunca em produção); senhas aleatórias + `password_reset_pending`.
- **Aceite:** em produção, `verify_password("123456", ...)` falha para todas as contas.

## A7 · ALTO — Token público dá admin total ignorando o `scope` + via query
- **Onde:** `backend/routes/public_access.py` + `backend/auth.py:246-256` (scope capturado, nunca aplicado; token em `?ptoken=`).
- **Fazer:** aplicar o `scope` como allowlist de rotas/tags (403 fora dele); reduzir o poder ao mínimo do caso de uso; transportar via header/cookie.
- **Aceite:** token `scope:"lousa"` → 403 fora de "lousa"; gate ART.4 verde.

## A8 · ALTO — JWT de 30 dias não-revogável + logout cosmético + localStorage
- **Onde:** `backend/auth.py:18` (TTL); `/auth/logout` (comentário admite que o token sobrevive); front em `localStorage`; CSP com `unsafe-eval`.
- **Fazer:** access token curto (30–60 min) + **refresh token rotativo**;
  **denylist server-side** de `jti`/`sid` consultada no `get_current_user`;
  logout e troca de senha gravam na denylist; corrigir o comentário enganoso;
  endurecer CSP (remover `unsafe-eval`); migrar token para cookie `HttpOnly`+`Secure`+`SameSite=Lax`.
- **Aceite:** após logout, token anterior → 401; trocar senha invalida sessões; CSP sem `unsafe-eval` (gate ART.7b sem aviso).

## A9 · ALTO — Magic-link de parceiro é credencial owner permanente
- **Onde:** `backend/routes/parceria.py:1039` (token sem expiração, emite JWT 30d role `owner`, sem rate limit).
- **Fazer:** magic-link de uso único e curta duração; rotacionar ao consumir; rate limit; reduzir privilégio.
- **Aceite:** link reusado/expirado → 401; teste cobre reuse.

## A10 · ALTO — Dependências com CVE conhecida no caminho de segurança
- **Onde:** `backend/requirements.txt` — `pyjwt 2.12.1` (8 CVEs), `starlette 0.37.2`, `python-multipart 0.0.27`, `aiohttp`, `urllib3`, `idna`, `cryptography`, `litellm`, `pymongo`, `pypdf`.
- **Fazer:** subir todas para versão sem CVE conhecida (mínimo: `pyjwt>=2.13.0`, `starlette` compatível com FastAPI atualizado, `python-multipart>=0.0.31`). Rodar `pip-audit` até zerar.
- **Aceite:** `pip-audit -r backend/requirements.txt` sem vulnerabilidades de severidade alta.

## A11 · ALTO — Dependência não-pública no caminho de auth
- **Onde:** `emergentintegrations==0.1.0` (fora do PyPI) e o trust anchor externo `demobackend.emergentagent.com` no `google-login` (`backend/routes/users.py:182`).
- **Fazer:** substituir por biblioteca pública auditável ou vendorizar com hash fixado; validar o OAuth contra provedor de confiança próprio. Remover dependência opaca da autenticação.
- **Aceite:** `requirements.txt` instalável só do PyPI; gate ART.14 verde.

## A12 · MÉDIO — SSRF no fetch de logo
- **Onde:** `backend/routes/clock.py:2061` (`urlopen(logo_src)` sem guarda).
- **Fazer:** criar helper `safe_fetch(url)` central: só `https://`, resolve host e **bloqueia** loopback/link-local/RFC1918/metadata; allowlist de CDN. Usar em todo fetch de URL fornecida.
- **Aceite:** URL para `169.254.169.254`/`127.0.0.1` rejeitada (gate ART.6 verde).

## A13 · MÉDIO — IDOR cross-tenant em download de transcrição
- **Onde:** `backend/routes/whatsapp_config.py:557` (só valida JWT, não posse).
- **Fazer:** validar que o documento pertence ao `company_id` efetivo antes de servir; 404 caso contrário.
- **Aceite:** usuário do tenant A → 404 ao baixar transcrição do tenant B.

## A14 · MÉDIO — CSRF no fluxo de cookie do colaborador
- **Onde:** `backend/routes/collab_auth.py:216` — `samesite="none"`, sem token anti-CSRF.
- **Fazer:** `SameSite=Lax` (ou `Strict`) + token anti-CSRF (double-submit ou header) em todo endpoint state-changing autenticado por cookie.
- **Aceite:** gate ART.12 verde; teste de CSRF cobre POST cross-site rejeitado.

## A15 · MÉDIO — Vazamento de exceção crua ao cliente (132 ocorrências)
- **Onde:** `raise HTTPException(..., str(e))` / `f"...{e}"` em ~132 pontos.
- **Fazer:** mensagem genérica ao cliente + detalhe no log server-side com correlação. Padronizar via helper.
- **Aceite:** gate ART.13 verde.

## A16 · MÉDIO — Superfície e segredos
- **Docs:** desligar `/docs`,`/redoc`,`/openapi.json` em produção (`docs_url=None` quando `ENV=production`) — `backend/server.py:428`.
- **Defaults de segredo:** remover fallbacks `REDE_IA_QR_SECRET="...change-me"` etc.; exigir env.
- **Webhook Meta:** rejeitar quando `app_secret` vazio (`whatsapp_meta.py:282`).
- **Ingest de frota:** `fleet_tracking.py:233` exigir token em produção (fail-closed).
- **Vault:** planejar migração da `SECRETS_MASTER_KEY` (env) para KMS/HSM com rotação.
- **Aceite:** docs 404 em prod; gate ART.2 verde; ingest/Meta fail-closed.

## A17 · MÉDIO — Rate limiting sem política uniforme
- **Onde:** só `/auth/login` + webhooks têm limite. Faltam: `admin-login`, `google-login`, `partner_magic_login`, magic-links.
- **Fazer:** aplicar rate limit + lockout em **toda** superfície de autenticação e de envio (anti brute-force, anti-enumeração, anti-bombing).
- **Aceite:** todas as rotas de auth têm `@limiter.limit`; teste de excesso → 429.

## A18 · MÉDIO — Código de autorização morto (falsa garantia)
- **Onde:** `backend/iam_v2/*` (76 KB) referenciado por **0 rotas**; autz real é o legado `require_role`/`access_tags`.
- **Fazer:** decidir uma fonte autoritativa. Ou (a) plugar o IAM v2 e migrar as rotas, ou (b) **remover** o IAM v2. Não manter os dois.
- **Aceite:** não há subsistema de autz não-utilizado no tree; autz tem fonte única testada.

---

# BLOCO B — TRANCAR O FUTURO (instalar a lei permanente)

Sem isto, o Bloco A vira dívida que volta na próxima sprint. Instale **todas** as
quatro camadas:

## B1 · A constituição
- Garantir `governance/SECURITY_LOCK.md` na raiz, com os artigos ART.1–ART.14 +
  ART.0 (fail-closed). É a fonte da verdade; exceção só por emenda aprovada pelo
  titular (`vando@ligotelecom.com`).

## B2 · O portão executável
- `scripts/security_gate/security_gate.sh` (já cobre ART.1–14 + avisos). Tornar
  executável (`chmod +x`). Cada artigo = um check; violação = exit≠0 = bloqueio.

## B3 · Pre-commit (barra na máquina)
- `.pre-commit-config.yaml` rodando o gate em `--staged` + gitleaks + bandit.
- `pip install pre-commit && pre-commit install`.

## B4 · CI obrigatório (barra o merge)
- `.github/workflows/security-gate.yml` rodando gate + gitleaks + bandit +
  pip-audit. Marcar como **required status check** na branch protection de
  `main`/`production`. Sem o check verde, não mergeia.

## B5 · A regra para quem escreve (humano e IA)
- `AGENTS.md` na raiz, lido por agentes de IA e devs antes de qualquer alteração.
  Resumo operacional das regras + Definition of Done. Garante que o código
  **nasça** certo, não que o gate vire jogo de gato e rato.

## B6 · Toda feature nova, daqui pra frente, obedece:
1. Rota nova → `Depends(get_current_user)`/guard, ou `@public_endpoint` justificado.
2. Segredo/token ausente → **negar** (nunca liberar).
3. Credencial → header/cookie, nunca query string.
4. Query de dados → `tenant_filter(user)`; acesso por id → validar posse por `company_id`.
5. Fetch externo → `safe_fetch` (bloqueia IP privado/metadata).
6. `jwt.decode` → sempre `algorithms=[...]`; sessão → revogável via denylist.
7. Erro → mensagem genérica ao cliente + detalhe no log.
8. Dependência → pública, pinada, sem CVE conhecida (pip-audit limpo).
9. Cookie de auth → `SameSite=Lax/Strict` + anti-CSRF.
10. **Sem** endpoints de debug no build de produção.
11. Teste do **caminho de negação** (acesso negado), não só do feliz.

---

# ENTREGA FINAL

1. PRs por bloco/severidade, cada um referenciando o item (A1…A18 / B1…B6).
2. Testes automatizados para cada **Aceite** acima — com ênfase nos caminhos de
   negação (token ausente → 401, tenant errado → 404, assinatura ausente →
   rejeição, rate limit → 429).
3. `bash scripts/security_gate/security_gate.sh all` → **APROVADO**.
4. `pip-audit` → sem CVE de severidade alta.
5. Histórico Git purgado de PII; credenciais expostas rotacionadas.
6. Relatório curto: para cada item, "resolvido / aceite atendido / como provei".

> **Critério único de pronto:** o gate está verde, o CI é obrigatório, e nenhuma
> regra do ARTIGO ZERO pode ser violada sem emenda formal. A partir daqui, nada
> entra no sistema fora destas regras — por construção, não por confiança.
