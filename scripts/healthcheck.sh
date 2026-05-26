#!/bin/bash
# ===========================
# LeakSight V1 — Container Health Check Script
# ===========================
# Source: infra setup guide (Section 12.1)
#
# Checks all 5 Docker services for running status and health.
# Logs alerts for any unhealthy or stopped containers.
#
# Usage: ./scripts/healthcheck.sh
# Cron:  */5 * * * * /opt/leaksight/scripts/healthcheck.sh >> /opt/leaksight/logs/healthcheck.log 2>&1

set -euo pipefail

SERVICES=(
  "leaksight-app-postgres-1"
  "leaksight-app-redis-1"
  "leaksight-app-backend-1"
  "leaksight-app-worker-1"
  "leaksight-app-nginx-1"
)
ALERT_LOG=/opt/leaksight/logs/healthcheck.log

ALL_HEALTHY=true

for SERVICE in "${SERVICES[@]}"; do
  STATUS=$(docker inspect --format='{{.State.Status}}' "$SERVICE" 2>/dev/null || echo "not_found")
  HEALTH=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no_healthcheck{{end}}' "$SERVICE" 2>/dev/null || echo "unknown")

  if [ "$STATUS" != "running" ] || \
     ([ "$HEALTH" != "healthy" ] && [ "$HEALTH" != "no_healthcheck" ]); then
    MSG="ALERT: $SERVICE status=$STATUS health=$HEALTH at $(date)"
    echo "$MSG" | tee -a "$ALERT_LOG"
    ALL_HEALTHY=false
  fi
done

if $ALL_HEALTHY; then
  echo "$(date): All services healthy" >> "$ALERT_LOG"
fi
