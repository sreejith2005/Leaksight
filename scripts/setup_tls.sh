#!/bin/bash
# ===========================
# LeakSight V1 — TLS Certificate Setup (Let's Encrypt)
# ===========================
# Source: infra setup guide (Section 7.2)
#
# Automates Let's Encrypt certificate acquisition for the LeakSight domain.
#
# Usage: ./scripts/setup_tls.sh <domain>
# Example: ./scripts/setup_tls.sh app.leaksight.com
#
# Prerequisites:
#   - certbot installed on the server: sudo apt install -y certbot
#   - DNS A-record pointing to this server's IP
#   - Port 80 available (nginx will be stopped temporarily)

set -euo pipefail

DOMAIN=${1:?"Usage: setup_tls.sh <domain>"}
COMPOSE_FILE=/opt/leaksight/app/docker-compose.prod.yml
CERT_DIR=/opt/leaksight/nginx/certs

echo "Setting up TLS certificate for: $DOMAIN"
echo ""

# Ensure cert directory exists
mkdir -p "$CERT_DIR"

# Stop nginx if running (certbot needs port 80 for standalone verification)
echo "Stopping nginx (if running)..."
docker compose -f "$COMPOSE_FILE" stop nginx 2>/dev/null || true

# Get certificate from Let's Encrypt
echo "Requesting certificate from Let's Encrypt..."
sudo certbot certonly --standalone -d "$DOMAIN"

# Copy certificates to nginx certs directory
echo "Copying certificates..."
sudo cp /etc/letsencrypt/live/"$DOMAIN"/fullchain.pem "$CERT_DIR"/
sudo cp /etc/letsencrypt/live/"$DOMAIN"/privkey.pem "$CERT_DIR"/
sudo chown -R leaksight:leaksight "$CERT_DIR"

# Restart nginx with the new certificate
echo "Starting nginx..."
docker compose -f "$COMPOSE_FILE" up -d nginx

echo ""
echo "=========================================="
echo "  TLS setup complete for $DOMAIN"
echo "=========================================="
echo ""
echo "Verify with: curl -I https://$DOMAIN"
echo ""
echo "Set up auto-renewal by running: ./scripts/setup_monitoring_cron.sh"
echo "(includes certbot renewal at 3am daily)"
echo "=========================================="
