#!/usr/bin/env bash
# Smoke tests — Estoque + Balanço + Auto-baixa Rede + Auditoria
# Executa contra REACT_APP_BACKEND_URL (live preview).
# Use: bash backend/tests/run_smoke.sh
set -e
cd "$(dirname "$0")/../.."
export REACT_APP_BACKEND_URL="$(grep REACT_APP_BACKEND_URL frontend/.env | cut -d= -f2)"
echo "→ Backend: $REACT_APP_BACKEND_URL"
exec python3 -m pytest \
  backend/tests/test_estoque_smoke.py \
  backend/tests/test_balanco_smoke.py \
  backend/tests/test_rede_fiber_smoke.py \
  -v --tb=short "$@"
