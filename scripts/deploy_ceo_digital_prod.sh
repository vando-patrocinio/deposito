#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Deploy CEO Digital · app.ligo.systems/operacional
# Roda este script NO SERVIDOR DE PRODUÇÃO, depois de `git pull`.
#
# Pré-requisito: o repo já está atualizado (Save to GitHub + git pull).
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="${1:-/app}"
TOKEN_DEV="mAYeaEOabYEPzrea3fIQfZMemMRaVAMoCCASoRekgs0"
PUBLIC_URL_DEFAULT="https://app.ligo.systems/operacional"

cd "$REPO_DIR"

echo "════════════════════════════════════════════════"
echo "  DEPLOY · CEO DIGITAL · $(date -u +%FT%TZ)"
echo "════════════════════════════════════════════════"

# 1. Confirma que os 5 arquivos chegaram do git pull
echo "→ verificando arquivos novos…"
for f in \
  backend/routes/ceo_digital.py \
  backend/services/executive_memory.py \
  backend/scripts/executive_memory_snapshot.py
do
  if [[ ! -f "$f" ]]; then
    echo "  ❌ $f não existe. Rode 'git pull' antes."
    exit 1
  fi
  echo "  ✓ $f"
done

# 2. Valida que rbac_policy.py contém o prefix /api/ceo
if ! grep -q '"/api/ceo"' backend/rbac_policy.py; then
  echo "  ❌ rbac_policy.py NÃO contém '/api/ceo' em NON_STAFF_AUTH_PREFIXES"
  echo "     Confere se o pull trouxe a alteração."
  exit 1
fi
echo "  ✓ rbac_policy.py com /api/ceo registrado"

# 3. Valida que server.py registra o router
if ! grep -q "routes_ceo_digital" backend/server.py; then
  echo "  ❌ server.py NÃO importa routes_ceo_digital"
  exit 1
fi
echo "  ✓ server.py registrando routes_ceo_digital"

# 4. .env — adiciona variáveis se não existirem (idempotente)
ENV_FILE="backend/.env"
echo "→ configurando $ENV_FILE…"
touch "$ENV_FILE"

if ! grep -q "^CEO_BRIEFING_TOKEN=" "$ENV_FILE"; then
  TOK="${CEO_BRIEFING_TOKEN_PROD:-$TOKEN_DEV}"
  echo "CEO_BRIEFING_TOKEN=$TOK" >> "$ENV_FILE"
  echo "  ✓ CEO_BRIEFING_TOKEN adicionado (use \$CEO_BRIEFING_TOKEN_PROD pra trocar)"
else
  echo "  ✓ CEO_BRIEFING_TOKEN já existe"
fi

if ! grep -q "^PUBLIC_BACKEND_URL=" "$ENV_FILE"; then
  echo "PUBLIC_BACKEND_URL=${PUBLIC_BACKEND_URL_PROD:-$PUBLIC_URL_DEFAULT}" >> "$ENV_FILE"
  echo "  ✓ PUBLIC_BACKEND_URL adicionado"
else
  echo "  ✓ PUBLIC_BACKEND_URL já existe"
fi

# 5. Restart backend
echo "→ restartando backend…"
if command -v supervisorctl >/dev/null 2>&1; then
  sudo supervisorctl restart backend
elif command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart smartprov-backend
else
  echo "  ⚠ não encontrei supervisor nem systemctl · restarte manualmente"
fi

sleep 5

# 6. Smoke test interno (porta 8001)
echo "→ smoke test interno…"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8001/api/ceo/openapi.json || echo "000")
if [[ "$STATUS" != "200" ]]; then
  echo "  ❌ /api/ceo/openapi.json local retornou $STATUS"
  echo "     Veja: tail -n 50 /var/log/supervisor/backend.err.log"
  exit 1
fi
echo "  ✓ /api/ceo/openapi.json local = 200"

# 7. Smoke test público
PUB="${PUBLIC_BACKEND_URL_PROD:-$PUBLIC_URL_DEFAULT}"
echo "→ smoke test público em $PUB …"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$PUB/api/ceo/openapi.json")
if [[ "$STATUS" != "200" ]]; then
  echo "  ❌ $PUB/api/ceo/openapi.json retornou $STATUS"
  echo "     Provável proxy nginx/apache não roteando /api/ceo. Avisa o time de infra."
  exit 1
fi
echo "  ✓ $PUB/api/ceo/openapi.json = 200"

# 8. Smoke test autenticado
TOKEN=$(grep ^CEO_BRIEFING_TOKEN= "$ENV_FILE" | cut -d= -f2)
STATUS=$(curl -s -o /tmp/ceo_brief.json -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  "$PUB/api/ceo/briefing/today")
if [[ "$STATUS" != "200" ]]; then
  echo "  ❌ /briefing/today autenticado retornou $STATUS"
  exit 1
fi
echo "  ✓ /briefing/today autenticado = 200"

# 9. Snapshot do dia + backfill 30d
echo "→ inicializando executive_memory (backfill 30d)…"
cd backend && python3 scripts/executive_memory_snapshot.py --backfill 30 >/dev/null 2>&1
echo "  ✓ president_daily populado"

echo
echo "════════════════════════════════════════════════"
echo "  ✅ DEPLOY OK"
echo "════════════════════════════════════════════════"
echo
echo "PARA O CUSTOM GPT (Painel ChatGPT → My GPTs → Edit → Actions):"
echo "  URL OpenAPI: $PUB/api/ceo/openapi.json"
echo "  Auth:        Bearer"
echo "  Token:       (oculto · veja em backend/.env CEO_BRIEFING_TOKEN)"
echo
