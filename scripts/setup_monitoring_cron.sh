#!/bin/bash
# ===========================
# LeakSight V1 — Install All Monitoring Cron Jobs
# ===========================
# Source: infra setup guide (Sections 11.2, 12.1, 12.2, 7.3)
#
# Installs all production monitoring and maintenance cron jobs:
#   - Health check every 5 minutes
#   - Disk usage alert every hour (threshold: 80%)
#   - Daily database backup at 2am
#   - Daily TLS certificate renewal attempt at 3am
#
# Usage: ./scripts/setup_monitoring_cron.sh
#
# NOTE: Replace YOUR_DOMAIN in the TLS renewal entry with your actual domain
#       before running this script.

set -euo pipefail

CRON_JOBS=(
  # Health check every 5 minutes
  "*/5 * * * * /opt/leaksight/scripts/healthcheck.sh >> /opt/leaksight/logs/healthcheck.log 2>&1"
  # Disk usage alert at 80% — check every hour
  '0 * * * * USAGE=$(df /opt/leaksight/data --output=pcent | tail -1 | tr -dc "0-9"); if [ "$USAGE" -gt 80 ]; then echo "DISK ALERT: /opt/leaksight/data at ${USAGE}% on $(date)" >> /opt/leaksight/logs/disk.log; fi'
  # Daily backup at 2am
  "0 2 * * * /opt/leaksight/scripts/backup.sh >> /opt/leaksight/logs/backup.log 2>&1"
  # TLS renewal at 3am daily (certbot only renews if cert is near expiry)
  "0 3 * * * certbot renew --quiet && cp /etc/letsencrypt/live/YOUR_DOMAIN/fullchain.pem /opt/leaksight/nginx/certs/ && cp /etc/letsencrypt/live/YOUR_DOMAIN/privkey.pem /opt/leaksight/nginx/certs/ && docker compose -f /opt/leaksight/app/docker-compose.prod.yml restart nginx"
)

echo "Installing monitoring cron jobs..."
echo ""

EXISTING_CRON=$(crontab -l 2>/dev/null || echo "")

for JOB in "${CRON_JOBS[@]}"; do
  # Extract the command part (after the schedule) for duplicate detection
  CMD_PART=$(echo "$JOB" | sed 's/^[0-9\*\/]* [0-9\*\/]* [0-9\*\/]* [0-9\*\/]* [0-9\*\/]* //')

  if echo "$EXISTING_CRON" | grep -qF "$CMD_PART" 2>/dev/null; then
    echo "  SKIP (already exists): ...${CMD_PART:0:60}..."
  else
    EXISTING_CRON=$(printf "%s\n%s" "$EXISTING_CRON" "$JOB")
    echo "  ADDED: ...${CMD_PART:0:60}..."
  fi
done

echo "$EXISTING_CRON" | crontab -

echo ""
echo "=========================================="
echo "  All monitoring cron jobs installed."
echo "=========================================="
echo ""
echo "IMPORTANT: If you haven't already, replace YOUR_DOMAIN in"
echo "the TLS renewal cron entry with your actual domain."
echo ""
echo "Verify with: crontab -l"
echo "=========================================="
