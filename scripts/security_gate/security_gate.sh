#!/usr/bin/env bash
# ============================================================================
# SECURITY GATE — SmartProv / tudao
# Portão automático que BARRA merge/commit quando qualquer regra do
# governance/SECURITY_LOCK.md é violada. Subordinado à SYSTEM_CONSTITUTION.
#
# Uso:
#   bash scripts/security_gate/security_gate.sh            # repo inteiro
#   bash scripts/security_gate/security_gate.sh --staged   # só arquivos staged
#
# Saída: código 0 = aprovado; !=0 = bloqueado (lista as violações).
# Cada regra abaixo mapeia 1:1 com um artigo do SECURITY_LOCK.
# ============================================================================
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
cd "$ROOT"

MODE="${1:-all}"
VIOLATIONS=0
RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; NC=$'\033[0m'

# Conjunto de arquivos a inspecionar (staged ou tudo, excluindo libs/locks)
if [[ "$MODE" == "--staged" ]]; then
  FILES=$(git diff --cached --name-only --diff-filter=ACM)
else
  FILES=$(git ls-files)
fi
# filtros comuns
filter() { grep -vE '(node_modules/|/dist/|/build/|yarn\.lock|package-lock\.json|/scripts/security_gate/|SECURITY_LOCK\.md|PROMPT_REMEDIACAO)' ; }
PY=$(echo "$FILES" | grep -E '\.py$'        | filter || true)
JS=$(echo "$FILES" | grep -E '\.(js|jsx)$'  | filter || true)
ALL=$(echo "$FILES" | filter || true)

fail() { echo "${RED}✗ BLOQUEADO${NC} [$1] $2"; VIOLATIONS=$((VIOLATIONS+1)); }
note() { echo "  ${YEL}↳${NC} $1"; }

echo "=============================================="
echo " SECURITY GATE — verificando $(echo "$ALL" | grep -c . ) arquivo(s) [$MODE]"
echo "=============================================="

# --- ART.1  PII / dados reais de cliente versionados ------------------------
# Só inspeciona arquivos de DADOS/CONTEÚDO (não código-fonte: regex de CPF
# em .py/.js é legítimo). Procura CPF FORMATADO (com pontos/traço) em massa.
DATA=$(echo "$ALL" | grep -E '\.(csv|tsv|json|txt|sql|xml|yaml|yml|ndjson)$' \
        | grep -vE '(test|spec|fixture|mock|sample|schema)' || true)
hits=$(echo "$DATA" | xargs -r grep -lEI "[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}" 2>/dev/null \
        | grep -viE '000\.000\.000|111\.111\.111|123\.456\.789' || true)
[[ -n "$hits" ]] && { fail "ART.1-PII" "CPF formatado em arquivo de dados versionado"; echo "$hits" | sed 's/^/    /'; }
# binários de cliente fora do storage
bin=$(echo "$ALL" | grep -E '(uploads/.*\.(pdf|ogg|webm|jpe?g|png)|data_imports/.*\.(xlsx|csv|ofx)|/holerites/)' || true)
[[ -n "$bin" ]] && { fail "ART.1-PII" "binário/planilha de cliente versionado (deve ir pra storage externo)"; echo "$bin" | sed 's/^/    /'; }

# --- ART.2  Segredos hardcoded / defaults inseguros -------------------------
sec=$(echo "$ALL" | xargs -r grep -nEI \
        "(sk-ant-|sk_live_|AKIA[0-9A-Z]{16}|ghp_|xoxb-|whsec_|admin123|auditor123|change-me|default-secret)" 2>/dev/null \
        | grep -vE '\.(md)$' || true)
[[ -n "$sec" ]] && { fail "ART.2-SECRET" "segredo/credencial-default hardcoded"; echo "$sec" | sed 's/^/    /'; }

# --- ART.3  FAIL-OPEN: liberar quando segredo ausente -----------------------
# Python: 'if not <secret/token>: return next/True/allow' OU env.get(...,"<algo>")
fo_py=$(echo "$PY" | xargs -r grep -nE \
   "environ\.get\((['\"][A-Z_]*(SECRET|TOKEN|PASSWORD|KEY)[A-Z_]*['\"]\s*,\s*['\"][^'\"]+['\"])" 2>/dev/null \
   | grep -vE "['\"]\s*,\s*['\"]['\"]\)" || true)   # permite default "" (vazio = fail-closed)
[[ -n "$fo_py" ]] && { fail "ART.3-FAILOPEN" "env de segredo com default NÃO-vazio (use \"\" e falhe-fechado)"; echo "$fo_py" | sed 's/^/    /'; }
# Node: 'if (!TOKEN) return next()'
fo_js=$(echo "$JS" | xargs -r grep -nE "if\s*\(\s*!\s*[A-Za-z_]*(TOKEN|SECRET|KEY)[A-Za-z_]*\s*\)\s*return\s+next" 2>/dev/null || true)
[[ -n "$fo_js" ]] && { fail "ART.3-FAILOPEN" "middleware Node libera quando token ausente (fail-open)"; echo "$fo_js" | sed 's/^/    /'; }

# --- ART.4  Tokens/credenciais em query string ------------------------------
qs=$(echo "$PY" | xargs -r grep -nE "query_params\.get\(\s*['\"](ptoken|token|t|key|secret|password|apikey)['\"]" 2>/dev/null || true)
[[ -n "$qs" ]] && { fail "ART.4-TOKEN-IN-URL" "credencial lida de query string (use header/cookie)"; echo "$qs" | sed 's/^/    /'; }

# --- ART.5  Rota sem guard de auth ------------------------------------------
# heurística: @router.<verb> seguido (próximas 6 linhas) por 'def' sem Depends(
# e sem marcação explícita @public_endpoint
guardless=$(echo "$PY" | xargs -r grep -A6 -nE "@router\.(get|post|put|delete|patch)\(" 2>/dev/null \
  | awk 'BEGIN{RS="--\n"} /async def|def /{ if ($0 !~ /Depends\(/ && $0 !~ /@public_endpoint/ && $0 !~ /webhook|health|\/about|magic|signup|login|forgot|public/) print FILENAME": "$0 }' 2>/dev/null \
  | grep -oE '^[^:]+\.py' | sort -u || true)
# (heurística informativa — não bloqueia sozinha; vira aviso)
[[ -n "$guardless" ]] && { echo "${YEL}⚠ AVISO${NC} [ART.5-AUTH] revisar rotas possivelmente sem Depends de auth:"; echo "$guardless" | sed 's/^/    /'; }

# --- ART.6  SSRF: fetch de URL livre sem allowlist --------------------------
ssrf=$(echo "$PY" | xargs -r grep -nE "urllib\.request\.urlopen\(|requests\.get\(.*(payload|request|user|param)" 2>/dev/null \
   | grep -viE "allowlist|allow_list|is_private|block_private|guard_url|safe_fetch" || true)
[[ -n "$ssrf" ]] && { fail "ART.6-SSRF" "fetch de URL externa sem guarda (use safe_fetch/allowlist + bloqueio de IP privado)"; echo "$ssrf" | sed 's/^/    /'; }

# --- ART.7  jwt.decode sem algorithms explícito (exceto testes/inspeção) ----
jwtd=$(echo "$PY" | grep -vE '/tests/|_test\.py|test_' | xargs -r grep -nE "jwt\.decode\(" 2>/dev/null \
        | grep -v "algorithms=" | grep -v "verify_signature.*False" || true)
[[ -n "$jwtd" ]] && { fail "ART.7-JWT" "jwt.decode sem algorithms= (risco de alg-confusion)"; echo "$jwtd" | sed 's/^/    /'; }

# --- ART.8  subprocess com shell=True ---------------------------------------
sh=$(echo "$PY" | xargs -r grep -nE "shell\s*=\s*True" 2>/dev/null || true)
[[ -n "$sh" ]] && { fail "ART.8-SHELL" "subprocess shell=True (use lista de argumentos)"; echo "$sh" | sed 's/^/    /'; }

# --- ART.9  Docs/openapi sem desligar em produção ---------------------------
docs=$(echo "$PY" | xargs -r grep -nE "FastAPI\(" 2>/dev/null | grep -v "docs_url" || true)
[[ -n "$docs" ]] && { echo "${YEL}⚠ AVISO${NC} [ART.9-DOCS] FastAPI() sem docs_url=None — confirme desligado em produção:"; echo "$docs" | sed 's/^/    /'; }

# --- ART.11 Endpoint de debug embarcado --------------------------------------
dbg=$(echo "$PY" | grep -iE 'debug' | grep -E 'routes/' || true)
dbg_inc=$(echo "$PY" | xargs -r grep -nE "include_router\(.*debug|import .*_debug" 2>/dev/null | grep -v "ENV" || true)
{ [[ -n "$dbg" ]] || [[ -n "$dbg_inc" ]]; } && { fail "ART.11-DEBUG" "router/endpoint de debug presente — proibido em build de produção"; echo "$dbg$dbg_inc" | sed 's/^/    /'; }

# --- ART.12 Cookie de auth com SameSite=None ---------------------------------
ck=$(echo "$PY" | xargs -r grep -nE "set_cookie" 2>/dev/null | grep -iE 'samesite\s*=\s*["'\'']?none' || true)
ck2=$(echo "$PY" | xargs -r grep -nE "samesite\s*=\s*[\"']none[\"']" 2>/dev/null || true)
{ [[ -n "$ck" ]] || [[ -n "$ck2" ]]; } && { fail "ART.12-CSRF" "cookie de auth com SameSite=None (use Lax/Strict + token anti-CSRF)"; echo "$ck$ck2" | sed 's/^/    /'; }

# --- ART.13 Vazamento de exceção crua pro cliente ----------------------------
leak=$(echo "$PY" | grep -vE '/scripts/' | xargs -r grep -nE "HTTPException\([0-9]+,\s*(str\(e\)|f[\"'][^\"']*\{e[\"x]?\})" 2>/dev/null || true)
[[ -n "$leak" ]] && { fail "ART.13-INFO-LEAK" "exceção crua devolvida ao cliente (use mensagem genérica + log server-side)"; echo "$leak" | sed 's/^/    /' | head -8; [[ $(echo "$leak" | grep -c .) -gt 8 ]] && note "... e mais $(($(echo "$leak" | grep -c .)-8)) ocorrência(s)"; }

# --- ART.14 Dependência não-pública / sem pin auditável ----------------------
np=$(echo "$ALL" | grep -E 'requirements.*\.txt$' | xargs -r grep -nE "^(emergentintegrations|.*@ git\+|.*file://)" 2>/dev/null || true)
[[ -n "$np" ]] && { fail "ART.14-DEP" "dependência não-pública/não-auditável (resolva no PyPI ou vendore com hash)"; echo "$np" | sed 's/^/    /'; }

# --- ART.7b Logout/sessão revogável (heurística) -----------------------------
# Se existe rota de logout mas nenhuma denylist/revogação de sessão consultada
# no decode → aviso (token de longa duração não-revogável).
if echo "$PY" | xargs -r grep -lE "/auth/logout" 2>/dev/null >/dev/null; then
  rev=$(echo "$PY" | xargs -r grep -lE "denylist|revoked_jti|session_revoked|token_blocklist|is_session_valid" 2>/dev/null || true)
  [[ -z "$rev" ]] && echo "${YEL}⚠ AVISO${NC} [ART.7b-SESSION] logout presente sem denylist de sessão — token continua válido até exp (implemente revogação)."
fi

echo "----------------------------------------------"
if [[ "$VIOLATIONS" -gt 0 ]]; then
  echo "${RED}GATE REPROVADO — $VIOLATIONS violação(ões). Merge/commit bloqueado.${NC}"
  echo "Consulte governance/SECURITY_LOCK.md para a regra e a correção."
  exit 1
fi
echo "${GRN}GATE APROVADO — nenhuma violação bloqueante.${NC}"
exit 0
