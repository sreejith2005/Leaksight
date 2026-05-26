#!/bin/bash
# ===========================
# LeakSight V1 — Full System Status
# ===========================
# Source: infra setup guide (Section 16), pilot readiness checklist Section 8.5
#
# Complete system status snapshot. Run at the start of a pilot session
# to confirm everything is healthy.
#
# Usage: ./scripts/full_status.sh

set -euo pipefail

COMPOSE_FILE=/opt/leaksight/app/docker-compose.prod.yml

echo "========================================"
echo "  LeakSight System Status"
echo "  $(date)"
echo "========================================"

echo ""
echo "--- Container Status ---"
docker compose -f "$COMPOSE_FILE" ps 2>/dev/null \
  || echo "Could not get container status. Is Docker Compose running?"

echo ""
echo "--- Disk Usage ---"
df -h /opt/leaksight/data 2>/dev/null \
  || echo "Data directory not found at /opt/leaksight/data"

echo ""
echo "--- Recent Backups ---"
ls -lh /opt/leaksight/data/backups/ 2>/dev/null | tail -3 \
  || echo "No backups found"

echo ""
echo "--- API Health ---"
curl -s https://YOUR_DOMAIN/api/v1/health 2>/dev/null | python3 -m json.tool 2>/dev/null \
  || echo "Health check failed — check nginx and backend"

echo ""
echo "--- Worker Memory ---"
docker stats leaksight-app-worker-1 --no-stream \
  --format "Memory: {{.MemUsage}} ({{.MemPerc}})" 2>/dev/null \
  || echo "Worker not running"

echo ""
echo "--- Backend Memory ---"
docker stats leaksight-app-backend-1 --no-stream \
  --format "Memory: {{.MemUsage}} ({{.MemPerc}})" 2>/dev/null \
  || echo "Backend not running"

echo ""
echo "--- Database Connections ---"
docker exec leaksight-app-postgres-1 psql -U leaksight_user -d leaksight \
  -t -c "SELECT count(*) FROM pg_stat_activity WHERE datname='leaksight';" 2>/dev/null \
  || echo "Could not query database"

echo ""
echo "--- Recent Errors (last 10) ---"
grep -i "error\|alert\|failed" /opt/leaksight/logs/healthcheck.log 2>/dev/null | tail -10 \
  || echo "No recent errors in healthcheck log"

echo ""
echo "--- Alembic Version ---"
docker compose -f "$COMPOSE_FILE" exec backend alembic current 2>/dev/null \
  || echo "Could not check Alembic version"

echo ""
echo "========================================"
echo "  Status check complete."
echo "  Replace YOUR_DOMAIN in this script with your actual domain."
echo "========================================"
