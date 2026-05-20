#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# SmartProv — Backup MongoDB
# ----------------------------------------------------------------------------
# Uso:
#   ./backup_mongo.sh                  # backup + rotação 30 dias
#   ./backup_mongo.sh --dir /custom    # destino customizado
#
# Cron sugerido (cada 6h):
#   0 */6 * * * /app/backend/scripts/backup_mongo.sh >> /var/log/smartprov-backup.log 2>&1
#
# Restore (em caso de necessidade):
#   mongorestore --uri="$MONGO_URL" --gzip --archive=<arquivo.gz>
# ----------------------------------------------------------------------------
set -euo pipefail

# ---- Config ----
ENV_FILE="${ENV_FILE:-/app/backend/.env}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/smartprov-mongo}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

# Permite override de diretório
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) BACKUP_DIR="$2"; shift 2 ;;
    --retention) RETENTION_DAYS="$2"; shift 2 ;;
    *) echo "Argumento desconhecido: $1"; exit 1 ;;
  esac
done

# ---- Load env ----
if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERR] $ENV_FILE não encontrado"
  exit 1
fi
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

: "${MONGO_URL:?MONGO_URL não definido em $ENV_FILE}"
: "${DB_NAME:?DB_NAME não definido em $ENV_FILE}"

mkdir -p "$BACKUP_DIR"

# ---- Backup ----
TS=$(date -u +"%Y%m%dT%H%M%SZ")
OUT="$BACKUP_DIR/smartprov-${DB_NAME}-${TS}.archive.gz"

echo "[$(date -Iseconds)] Backup iniciado: $OUT"
if ! command -v mongodump >/dev/null 2>&1; then
  echo "[ERR] mongodump não encontrado. Instale mongodb-database-tools."
  echo "      Ubuntu/Debian: sudo apt-get install -y mongodb-database-tools"
  exit 2
fi

mongodump --uri="$MONGO_URL" --db="$DB_NAME" --gzip --archive="$OUT" --quiet
SIZE=$(du -h "$OUT" | cut -f1)
echo "[$(date -Iseconds)] Backup concluído: $OUT ($SIZE)"

# ---- Rotação ----
echo "[$(date -Iseconds)] Rotação: removendo backups > $RETENTION_DAYS dias"
find "$BACKUP_DIR" -name "smartprov-*.archive.gz" \
     -type f -mtime "+${RETENTION_DAYS}" -delete -print

# ---- Opcional: sync para S3/rclone se configurado ----
if [[ -n "${BACKUP_REMOTE:-}" ]]; then
  echo "[$(date -Iseconds)] Sincronizando com remote: $BACKUP_REMOTE"
  if command -v rclone >/dev/null 2>&1; then
    rclone copy "$OUT" "$BACKUP_REMOTE/" --quiet
    echo "[$(date -Iseconds)] Remote sync OK"
  else
    echo "[WARN] BACKUP_REMOTE definido mas rclone não instalado"
  fi
fi

echo "[$(date -Iseconds)] OK"
