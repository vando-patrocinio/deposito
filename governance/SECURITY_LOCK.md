# 🔒 SmartProv — SECURITY LOCK (V1.0)

> Hierarquicamente subordinado a `governance/SYSTEM_CONSTITUTION.md`.
> **Travas de segurança** que não podem ser violadas sem emenda constitucional
> aprovada pelo titular (Vando · Ligo Telecom).
>
> Toda regra abaixo é **executável**: existe um check automático em
> `scripts/security_gate/security_gate.sh` que a verifica. O número do artigo
> (ART.N) é o mesmo do código de violação do gate. Código que viola qualquer
> artigo **não pode** ser commitado nem mergeado — o portão de CI reprova.

---

## PRINCÍPIO ZERO — FAIL-CLOSED (inegociável)

> Na ausência de configuração de segurança (segredo, token, chave, política),
> o sistema **NEGA**. Nunca libera "por enquanto", "em dev", ou "pra não
> quebrar". Um caminho que libera quando o segredo falta é um defeito de
> segurança, não uma conveniência.

Todas as travas a seguir são aplicações deste princípio.

---

## ART.1 — DADOS DE CLIENTE NUNCA NO REPOSITÓRIO

- É **proibido** versionar PII real: CPF/CNPJ, RG, nome+telefone de clientes,
  transcrições/áudios de atendimento, holerites, planilhas de contatos.
- Dados de seed/teste **DEVEM** ser sintéticos (fictícios, sem corresponder a
  pessoa real).
- Uploads de clientes **DEVEM** viver em storage externo (S3/objeto), nunca em
  `backend/uploads/` versionado.
- `.gitignore` **DEVE** conter: `data/`, `backend/uploads/`, `*.xlsx`, `*.csv`
  de import, `*.ofx`, `data/holerites/`.
- **Gate:** bloqueia CPF formatado em arquivo de dados e binários de cliente no tree.
- **Sanção a violação histórica:** purgar com `git filter-repo`/BFG + rotacionar.

## ART.2 — ZERO SEGREDO HARDCODED, ZERO DEFAULT INSEGURO

- Nenhuma chave, senha, token ou secret literal no código.
- **Proibido** default funcional para segredo (`"admin123"`, `"change-me"`,
  `"default-secret"`, etc.). Default permitido é **somente** string vazia `""`,
  que obriga o fail-closed do ART.3.
- Todo segredo vem de variável de ambiente / vault.
- **Gate:** bloqueia padrões de chave conhecidos e defaults inseguros.

## ART.3 — FAIL-CLOSED OBRIGATÓRIO EM AUTENTICAÇÃO

- `os.environ.get("X_SECRET", "<algo>")` com default não-vazio é **proibido**.
- Middleware que faz `if (!TOKEN) return next()` (libera sem token) é
  **proibido**. Sem token configurado em produção → o serviço **recusa**
  requests (401/503) ou não sobe.
- Comparação de segredo **DEVE** ser constant-time (`hmac.compare_digest`,
  `crypto.timingSafeEqual`).
- **Gate:** bloqueia default não-vazio (Python) e fail-open middleware (Node).

## ART.4 — CREDENCIAL NUNCA EM QUERY STRING

- Tokens/secrets **DEVEM** trafegar em header (`Authorization`, `X-Public-Token`)
  ou cookie `HttpOnly`+`Secure`+`SameSite`. Nunca em `?token=`/`?ptoken=`/`?t=`
  (vazam em logs, histórico e Referer).
- Link compartilhável que precise de URL usa token de **uso único** e
  **curtíssima** duração.
- **Gate:** bloqueia `query_params.get("token"|...)`.

## ART.5 — TODA ROTA TEM GUARD EXPLÍCITO

- Toda rota `@router.<verb>` **DEVE** declarar `Depends(get_current_user)` ou um
  guard (`require_role` / `require_tag`), **OU** ser marcada explicitamente
  `@public_endpoint` com justificativa no docstring.
- Acesso "público com poder admin" (token público) **DEVE** respeitar o `scope`:
  o escopo é aplicado como allowlist de rotas/tags; tudo fora dele é 403.
  Capturar `scope` e não aplicar é violação.
- **Gate:** aviso lista rotas sem `Depends` para revisão obrigatória no PR.

## ART.6 — SEM SSRF: FETCH EXTERNO SEMPRE COM GUARDA

- Buscar URL fornecida por usuário/config **DEVE** passar por `safe_fetch()`:
  só `https://`, resolve host e **bloqueia** loopback, link-local
  (`169.254.0.0/16`), e ranges privados (RFC1918), e endpoints de metadata.
- **Gate:** bloqueia `urlopen()`/`requests.get()` com input dinâmico sem guarda.

## ART.7 — JWT À PROVA DE ALG-CONFUSION

- `jwt.decode` **DEVE** sempre passar `algorithms=[...]` explícito.
- `JWT_SECRET` é obrigatório do ambiente, sem fallback.
- Access token de vida curta + refresh rotativo; logout/troca de senha
  **DEVEM** invalidar a sessão via denylist server-side de `jti`/`sid`.
  (Comentário que afirma invalidar sessão **DEVE** corresponder ao código real.)
- **Gate:** bloqueia `jwt.decode` sem `algorithms=` fora de testes.

## ART.8 — SEM EXECUÇÃO DE SHELL INSEGURA

- `subprocess` **DEVE** usar lista de argumentos; `shell=True` é **proibido**.
- **Gate:** bloqueia `shell=True`.

## ART.9 — SUPERFÍCIE MÍNIMA EM PRODUÇÃO

- `/docs`, `/redoc`, `/openapi.json` **DEVEM** ser desligados em produção
  (`docs_url=None` etc. quando `ENV=production`).
- Endpoints de diagnóstico **DEVEM** exigir auth e nunca vazar caminhos,
  existência de arquivos de sessão ou tamanhos/flags de segredo.
- **Gate:** aviso quando `FastAPI()` não define `docs_url`.

## ART.10 — ISOLAMENTO MULTI-TENANT É LEI

- Toda query a dados de negócio **DEVE** ser escopada por
  `tenant_filter(user)` / `effective_company_id(user)`.
- Todo acesso a arquivo/recurso por id **DEVE** validar a posse pelo
  `company_id` efetivo antes de servir (sem IDOR cross-tenant).
- `is_super_admin` é resolvido **somente** server-side a partir do banco /
  allowlist de env — **nunca** de claim manipulável pelo cliente.

---

## EMENDA CONSTITUCIONAL (única forma de exceção)

Uma regra só pode ser relaxada por:
1. PR dedicado alterando este arquivo **e** o gate correspondente;
2. justificativa de risco escrita no PR;
3. aprovação explícita do titular (`vando@ligotelecom.com`).

Sem os três, a exceção não existe — o gate continua reprovando.

---

## DEFINITION OF DONE (cola no template de PR)

- [ ] `bash scripts/security_gate/security_gate.sh` passou localmente.
- [ ] Nenhum segredo/PII novo no diff (`--staged` verde).
- [ ] Toda rota nova tem `Depends`/guard ou `@public_endpoint` justificado.
- [ ] Fetch externo novo usa `safe_fetch`; query a dados usa `tenant_filter`.
- [ ] Acesso a recurso por id valida posse por `company_id`.
- [ ] Teste automatizado cobrindo o caminho de **negação** (não só o feliz).
