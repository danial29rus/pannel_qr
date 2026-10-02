#!/usr/bin/env sh
# Run from the project directory on the production server via cron.
# Creates a compressed, restorable PostgreSQL dump without touching live data.
set -eu

# Shell-compatible .env generated from the supplied template.
set -a
. ./.env.production
set +a

backup_dir="${BACKUP_DIR:-/var/backups/clearpay}"
keep_days="${BACKUP_RETENTION_DAYS:-30}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"

docker compose --env-file .env.production -f docker-compose.prod.yml exec -T db \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner \
  > "$backup_dir/panel-$timestamp.dump"

# Prune only old backups created by this script inside the explicit backup dir.
find "$backup_dir" -maxdepth 1 -type f -name 'panel-*.dump' -mtime "+$keep_days" -delete
