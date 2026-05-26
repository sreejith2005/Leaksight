#!/bin/bash
# ===========================
# LeakSight V1 — Backup Verification Script
# ===========================
# Source: infra setup guide (Section 11), pilot readiness checklist Section 8.3
#
# Tests restore on a separate temporary database WITHOUT touching production.
# Creates a test database, restores the backup, verifies data, then drops the test DB.
#
# Usage: ./scripts/verify_backup.sh <backup_file_path>
# Example: ./scripts/verify_backup.sh /opt/leaksight/data/backups/db_20260221_020000.sql.gz

set -euo pipefail

BACKUP_FILE=${1:?"Usage: verify_backup.sh <backup_file_path>"}
CONTAINER=leaksight-app-postgres-1
DB_USER=leaksight_user
TEST_DB=leaksight_restore_test

# Verify backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "=========================================="
echo "  LeakSight Backup Verification"
echo "=========================================="
echo ""
echo "Backup file: $BACKUP_FILE"
echo "Test database: $TEST_DB"
echo ""

echo "Creating test database $TEST_DB..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS $TEST_DB;"
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres \
  -c "CREATE DATABASE $TEST_DB OWNER $DB_USER;"

echo "Restoring $BACKUP_FILE into $TEST_DB..."
gunzip -c "$BACKUP_FILE" \
  | docker exec -i "$CONTAINER" psql -U "$DB_USER" "$TEST_DB"

echo ""
echo "Verifying restored data..."
TABLES=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$TEST_DB" \
  -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")
echo "Tables restored: $TABLES"

LEAKAGE=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$TEST_DB" \
  -t -c "SELECT count(*) FROM leakage_records;" 2>/dev/null || echo "N/A")
echo "leakage_records count: $LEAKAGE"

UNITS=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$TEST_DB" \
  -t -c "SELECT count(*) FROM canonical_units;" 2>/dev/null || echo "N/A")
echo "canonical_units count: $UNITS"

VENDORS=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$TEST_DB" \
  -t -c "SELECT count(*) FROM vendors;" 2>/dev/null || echo "N/A")
echo "vendors count: $VENDORS"

# Clean up test database
echo ""
echo "Cleaning up test database..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres \
  -c "DROP DATABASE $TEST_DB;"

echo ""
echo "=========================================="
echo "  Backup verification complete."
echo "  Test database dropped."
echo "=========================================="
