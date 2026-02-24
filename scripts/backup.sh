#!/bin/bash
# ===========================
# LeakSight V1 — Database Backup Script
# ===========================
# Source: infra setup guide (Section 11.1)
#
# Creates a compressed PostgreSQL dump and rotates old backups.
# Designed to run daily via cron at 2am.
#
# Usage: ./scripts/backup.sh
# Cron:  0 2 * * * /opt/leaksight/scripts/backup.sh >> /opt/leaksight/logs/backup.log 2>&1

set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/opt/leaksight/data/backups
CONTAINER=leaksight-app-postgres-1
DB_NAME=leaksight
DB_USER=leaksight_user
LOG_FILE=/opt/leaksight/logs/backup.log

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

# Create compressed dump
docker exec "$CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" \
  | gzip > "$BACKUP_DIR/db_$TIMESTAMP.sql.gz"

# Verify the backup is not empty (a valid dump should be > 1KB)
SIZE=$(stat -c%s "$BACKUP_DIR/db_$TIMESTAMP.sql.gz" 2>/dev/null || stat -f%z "$BACKUP_DIR/db_$TIMESTAMP.sql.gz" 2>/dev/null || echo "0")
if [ "$SIZE" -lt 1000 ]; then
  echo "$(date): BACKUP FAILED — file too small: $SIZE bytes" >> "$LOG_FILE"
  exit 1
fi

# Rotate: delete backups older than 14 days
find "$BACKUP_DIR" -name "db_*.sql.gz" -mtime +14 -delete

echo "$(date): Backup completed → db_$TIMESTAMP.sql.gz ($(du -h "$BACKUP_DIR/db_$TIMESTAMP.sql.gz" | cut -f1))" >> "$LOG_FILE"
