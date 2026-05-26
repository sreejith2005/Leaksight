#!/bin/bash
# ===========================
# LeakSight V1 — Worker Status Script
# ===========================
# Source: infra setup guide (Sections 12.3, 12.4)
#
# Manual worker inspection: container stats, active tasks, queued tasks, recent logs.
#
# Usage: ./scripts/worker_status.sh

set -euo pipefail

COMPOSE_FILE=/opt/leaksight/app/docker-compose.prod.yml

echo "=========================================="
echo "  LeakSight Worker Status"
echo "  $(date)"
echo "=========================================="

echo ""
echo "=== Worker Container Stats ==="
docker stats leaksight-app-worker-1 --no-stream \
  --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}" 2>/dev/null \
  || echo "Worker container not running"

echo ""
echo "=== Active Celery Tasks ==="
docker compose -f "$COMPOSE_FILE" exec worker \
  celery -A app.core.celery_app inspect active 2>/dev/null \
  || echo "Worker not responding"

echo ""
echo "=== Queued Celery Tasks ==="
docker compose -f "$COMPOSE_FILE" exec worker \
  celery -A app.core.celery_app inspect reserved 2>/dev/null \
  || echo "Worker not responding"

echo ""
echo "=== Recent Worker Logs (last 30 lines) ==="
docker compose -f "$COMPOSE_FILE" logs --tail=30 worker 2>/dev/null \
  || echo "Could not retrieve worker logs"

echo ""
echo "=========================================="
