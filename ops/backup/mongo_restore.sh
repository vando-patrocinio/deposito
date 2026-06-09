#!/bin/bash
# /app/ops/backup/mongo_restore.sh
# Restore guiado de snapshot.
# Uso: ./mongo_restore.sh <snapshot-name>
# Ex:  ./mongo_restore.sh mongo-test_database-20260609-013000Z

set -e

cd /app/backend || exit 1
source .env 2>/dev/null || true

MONGO_URL="${MONGO_URL:-mongodb://localhost:27017}"
DB_NAME="${DB_NAME:-test_database}"
BACKUP_DIR="${BACKUP_DIR:-/app/backups}"

if [ -z "$1" ]; then
  echo "USO: $0 <snapshot-name>"
  echo ""
  echo "Snapshots disponíveis:"
  ls -1 "${BACKUP_DIR}" 2>/dev/null | grep "^mongo-" || echo "  (nenhum)"
  exit 1
fi

SNAP="${BACKUP_DIR}/$1"
if [ ! -d "${SNAP}" ]; then
  echo "ERRO: snapshot não encontrado em ${SNAP}"
  exit 1
fi

DB_PATH="${SNAP}/${DB_NAME}"
if [ ! -d "${DB_PATH}" ]; then
  echo "ERRO: snapshot não contém db ${DB_NAME} em ${DB_PATH}"
  exit 1
fi

echo "⚠️  ATENÇÃO: vai SOBRESCREVER o banco ${DB_NAME} a partir de ${SNAP}"
echo "   Digite 'RESTAURAR' para confirmar (case-sensitive):"
read -r CONFIRM

if [ "${CONFIRM}" != "RESTAURAR" ]; then
  echo "Cancelado."
  exit 0
fi

echo "[restore] iniciando mongorestore..."
mongorestore --uri="${MONGO_URL}" --db="${DB_NAME}" --gzip --drop "${DB_PATH}" 2>&1 | tail -20
echo "[restore] OK"
