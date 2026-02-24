#!/bin/bash
# ===========================
# LeakSight V1 — Database Restore Script
# ===========================
# Source: infra setup guide (Section 11.3)
#
# Restores the production database from a backup file.
# WARNING: This DESTROYS the current database. Prompts for confirmation.
#
# Usage: ./scripts/restore.sh <backup_file_path>
# Example: ./scripts/restore.sh /opt/leaksight/data/backups/db_20260221_020000.sql.gz

set -euo pipefail

BACKUP_FILE=${1:?"Usage: restore.sh <backup_file_path>"}
CONTAINER=leaksight-app-postgres-1
DB_NAME=leaksight
DB_USER=leaksight_user

# Verify backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "=========================================="
echo "  LeakSight Database Restore"
echo "=========================================="
echo ""
echo "Backup file: $BACKUP_FILE"
echo "Target database: $DB_NAME"
echo ""
echo "WARNING: This will DESTROY the current database and restore from backup."
echo "Type 'YES' to confirm:"
read -r CONFIRM
if [ "$CONFIRM" != "YES" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Dropping existing database..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS $DB_NAME;"

echo "Creating fresh database..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres \
  -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

echo "Restoring from backup..."
gunzip -c "$BACKUP_FILE" \
  | docker exec -i "$CONTAINER" psql -U "$DB_USER" "$DB_NAME"

# Verify restore by checking a known table
echo ""
echo "Verifying restore..."
COUNT=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" \
  -t -c "SELECT count(*) FROM leakage_records;" 2>/dev/null || echo "0")
echo "Restore complete. leakage_records count: $COUNT"

TABLES=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" \
  -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
echo "Total tables restored: $TABLES"
echo "=========================================="
