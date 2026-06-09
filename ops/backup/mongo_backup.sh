#!/bin/bash
# /app/ops/backup/mongo_backup.sh
# Wrapper de mongodump --gzip com rotação.
# Pode ser usado em cron host OU via endpoint /api/admin/safety/backup/snapshot.

set -e

cd /app/backend || exit 1
source .env 2>/dev/null || true

MONGO_URL="${MONGO_URL:-mongodb://localhost:27017}"
DB_NAME="${DB_NAME:-test_database}"
BACKUP_DIR="${BACKUP_DIR:-/app/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

TAG="$(date -u +%Y%m%d-%H%M%SZ)"
TARGET="${BACKUP_DIR}/mongo-${DB_NAME}-${TAG}"

mkdir -p "${TARGET}"

echo "[backup] iniciando snapshot ${TARGET}"
mongodump --uri="${MONGO_URL}" --db="${DB_NAME}" --gzip --out="${TARGET}" 2>&1 | tail -20

SIZE=$(du -sh "${TARGET}" | awk '{print $1}')
echo "[backup] snapshot pronto (${SIZE})"

# Rotação: remove backups antigos
find "${BACKUP_DIR}" -maxdepth 1 -type d -name "mongo-*" -mtime "+${RETENTION_DAYS}" -exec rm -rf {} \; 2>/dev/null || true
echo "[backup] purge concluído (retention=${RETENTION_DAYS} days)"

echo "[backup] OK ${TAG}"
