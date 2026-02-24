#!/bin/bash
# ===========================
# LeakSight V1 — Install Backup Cron Job
# ===========================
# Source: infra setup guide (Section 11.2)
#
# Installs the daily backup cron job (2am) for the leaksight user.
#
# Usage: ./scripts/setup_backup_cron.sh

set -euo pipefail

CRON_ENTRY="0 2 * * * /opt/leaksight/scripts/backup.sh >> /opt/leaksight/logs/backup.log 2>&1"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "backup.sh"; then
    echo "Backup cron job already installed. Current crontab:"
    crontab -l | grep "backup.sh"
    exit 0
fi

# Install the cron job
(crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -

echo "Backup cron installed: daily at 2am"
echo "Verify with: crontab -l"
