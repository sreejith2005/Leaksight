# LeakSight V1 — Infrastructure Setup Guide (Final, Corrected)

All four gaps identified in review have been fixed: complete Nginx config, complete Docker Compose YAML, explicit backup restore command, full deployment commands, and PaddleOCR memory management. Every section now contains copy-pasteable commands and configs — no prose-only descriptions.

***

## 0. Scope & Philosophy

- **Target**: Single-server, pilot-grade production for 1–3 clients.
- **Architecture**: Monolithic backend, single PostgreSQL, single Redis, Celery worker, Nginx reverse proxy, all via Docker Compose.
- **Storage**: Local disk for docs in V1 (on encrypted volume); S3/objects only from V2 onwards.
- **Explicitly not in scope**: Kubernetes, autoscaling, multi-region, real-time streaming, managed cloud services.

***

## 1. Hosting & Server Sizing

### 1.1 Recommended: Hetzner Cloud (Option A)

| Spec | CX41 | CX51 |
|------|------|------|
| vCPU | 4 | 8 |
| RAM | 16 GB | 32 GB |
| Storage | 160 GB NVMe | 240 GB NVMe |
| Monthly | ~€18.92 (~₹1,600) | ~€35.58 (~₹3,000) |
| Use case | 1–2 pilot clients | 3–5 clients / heavy OCR |

Start with **CX41**. Upgrade takes 2 minutes on Hetzner if needed.[^1]

- **OS**: Ubuntu 22.04 LTS (not 24.04 — wider PaddleOCR dependency support).
- **Region**: Nuremberg (EU) or Helsinki. Latency to India is acceptable for batch processing.

### 1.2 If Client Mandates AWS (Option B)

- EC2: `t3.xlarge` (4 vCPU, 16 GB RAM), ap-south-1 (Mumbai).
- RDS PostgreSQL 15 (`db.m6g.large`, 100 GB), ElastiCache Redis, S3 for documents, ALB + ACM for TLS.
- Security groups: only 80/443/22 on EC2; RDS/Redis only open to EC2 SG.

The rest of this guide assumes **Hetzner single server**.

***

## 2. Base OS Setup & Hardening

### 2.1 SSH Key Access

```bash
# On your local machine
ssh-keygen -t ed25519 -C "leaksight-pilot"
```

Add public key during Hetzner server creation, then:

```bash
ssh root@YOUR_SERVER_IP
```

### 2.2 Create Non-Root User

```bash
adduser leaksight
usermod -aG sudo leaksight
rsync --archive --chown=leaksight:leaksight ~/.ssh /home/leaksight
su - leaksight
```

All further steps run as `leaksight`, never root.

### 2.3 Harden SSH

```bash
sudo nano /etc/ssh/sshd_config
```

Set these three lines:

```text
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
```

```bash
sudo systemctl restart sshd
```

**Test immediately**: Open a new terminal and SSH as `leaksight@YOUR_SERVER_IP`. If it works, close the root session. If not, fix before closing root.

### 2.4 Firewall & Packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ufw fail2ban curl git unzip htop

sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

**Do NOT open** 5432 (Postgres) or 6379 (Redis) — internal Docker network only.

### 2.5 Timezone

```bash
sudo timedatectl set-timezone Asia/Kolkata
```

***

## 3. Docker & Docker Compose

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker leaksight
```

Log out and back in as `leaksight`:

```bash
exit
ssh leaksight@YOUR_SERVER_IP
```

Install Compose plugin:

```bash
sudo apt install -y docker-compose-plugin
```

Verify:

```bash
docker --version
docker compose version
```

***

## 4. Directory Layout

```bash
sudo mkdir -p /opt/leaksight
sudo chown leaksight:leaksight /opt/leaksight

mkdir -p /opt/leaksight/app
mkdir -p /opt/leaksight/data/postgres
mkdir -p /opt/leaksight/data/redis
mkdir -p /opt/leaksight/data/documents
mkdir -p /opt/leaksight/data/backups
mkdir -p /opt/leaksight/logs
mkdir -p /opt/leaksight/nginx/certs
mkdir -p /opt/leaksight/nginx/conf
mkdir -p /opt/leaksight/scripts
```

| Directory | Purpose |
|-----------|---------|
| `/opt/leaksight/app` | Code + docker-compose.prod.yml |
| `/opt/leaksight/data/postgres` | Postgres data volume |
| `/opt/leaksight/data/redis` | Redis persistence |
| `/opt/leaksight/data/documents` | Uploaded client documents (never public) |
| `/opt/leaksight/data/backups` | Database dumps |
| `/opt/leaksight/logs` | App, worker, nginx logs |
| `/opt/leaksight/nginx/certs` | TLS certificates |
| `/opt/leaksight/nginx/conf` | Nginx config |
| `/opt/leaksight/scripts` | Backup, healthcheck, restore scripts |

***

## 5. Environment Configuration (.env)

### 5.1 Create Production .env

```bash
cp /opt/leaksight/app/.env.example /opt/leaksight/.env
nano /opt/leaksight/.env
```

Complete contents:

```text
# Application
APP_ENV=production
SECRET_KEY=<generate: python3 -c "import secrets; print(secrets.token_hex(64))">
ALLOWED_HOSTS=yourdomain.com

# Database
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=leaksight
POSTGRES_USER=leaksight_user
POSTGRES_PASSWORD=<strong-password-no-special-chars>

# Redis
REDIS_URL=redis://redis:6379/0

# Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

# Storage
DOCUMENT_STORAGE_PATH=/app/data/documents
MAX_UPLOAD_SIZE_MB=200

# SMTP (Brevo free tier: 300 emails/day)
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=<your-brevo-login>
SMTP_PASSWORD=<your-brevo-smtp-key>
SMTP_FROM=noreply@yourdomain.com

# Tenant defaults
DEFAULT_FUZZY_THRESHOLD=0.85
DEFAULT_DUPLICATE_WINDOW_DAYS=30
DEFAULT_MANUAL_REVIEW_THRESHOLD=0.70
DEFAULT_BASE_CURRENCY=INR
```

### 5.2 Lock Permissions

```bash
chmod 600 /opt/leaksight/.env
```

**Critical**: Confirm `.env` is in `.gitignore` before any push.

***

## 6. Docker Compose (Production) — COMPLETE YAML

Create `/opt/leaksight/app/docker-compose.prod.yml`:

```yaml
version: "3.9"

services:

  postgres:
    image: postgres:15-alpine
    restart: always
    env_file: /opt/leaksight/.env
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - /opt/leaksight/data/postgres:/var/lib/postgresql/data
    networks:
      - internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    command:
      - "postgres"
      - "-c" 
      - "max_connections=100"
      - "-c"
      - "shared_buffers=4GB"
      - "-c"
      - "work_mem=32MB"
      - "-c"
      - "maintenance_work_mem=512MB"
      - "-c"
      - "effective_cache_size=12GB"
      - "-c"
      - "random_page_cost=1.1"

  redis:
    image: redis:7-alpine
    restart: always
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
    volumes:
      - /opt/leaksight/data/redis:/data
    networks:
      - internal
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  backend:
    image: leaksight/backend:latest
    restart: always
    env_file: /opt/leaksight/.env
    volumes:
      - /opt/leaksight/data/documents:/app/data/documents
      - /opt/leaksight/logs:/app/logs
    networks:
      - internal
      - external
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 1G

  worker:
    image: leaksight/backend:latest
    restart: always
    env_file: /opt/leaksight/.env
    volumes:
      - /opt/leaksight/data/documents:/app/data/documents
      - /opt/leaksight/logs:/app/logs
    networks:
      - internal
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: celery -A app.core.celery_app worker --loglevel=info --concurrency=2 --max-tasks-per-child=50
    # CRITICAL: Worker is on 'internal' network ONLY — no outbound internet
    # --max-tasks-per-child=50 forces worker process restart after 50 tasks
    # This prevents PaddleOCR memory accumulation from causing OOM kills
    deploy:
      resources:
        limits:
          memory: 10G
        reservations:
          memory: 4G
    shm_size: '2g'

  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /opt/leaksight/nginx/conf:/etc/nginx/conf.d
      - /opt/leaksight/nginx/certs:/etc/nginx/certs
      - /opt/leaksight/logs/nginx:/var/log/nginx
      - /opt/leaksight/app/frontend/dist:/usr/share/nginx/html:ro
    networks:
      - external
    depends_on:
      - backend

networks:
  internal:
    driver: bridge
    internal: true    # No outbound internet — postgres, redis, worker live here
  external:
    driver: bridge
```

### Why These Memory Limits Matter

PaddleOCR loads ML models (~300–500MB for server-grade models) and can consume 6–10GB processing large scanned PDFs, especially multi-page documents. Without limits, the worker will OOM-kill silently and tasks vanish. Three protections are in place:[^2][^3]

1. **`deploy.resources.limits.memory: 10G`** — Hard cap on worker container. If exceeded, Docker kills the container (which then auto-restarts) instead of crashing the entire server.[^4][^5]
2. **`--max-tasks-per-child=50`** — Forces Celery to restart worker processes after every 50 tasks. This clears accumulated PaddleOCR memory that garbage collection misses.[^6][^7]
3. **`shm_size: '2g'`** — PaddleOCR uses shared memory for inter-process data. Default Docker shared memory (64MB) is too small and causes silent failures.[^3]

***

## 7. Nginx Configuration — COMPLETE CONFIG

Create `/opt/leaksight/nginx/conf/leaksight.conf`:

```nginx
# ===========================
# HTTP → HTTPS redirect
# ===========================
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$host$request_uri;
}

# ===========================
# HTTPS server
# ===========================
server {
    listen 443 ssl;
    server_name yourdomain.com;

    # --- TLS ---
    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # --- Upload limit (matches master plan 200MB cap) ---
    client_max_body_size 200M;

    # --- Timeouts for long-running parse/report jobs ---
    proxy_read_timeout 300s;
    proxy_connect_timeout 75s;
    proxy_send_timeout 300s;

    # --- Security Headers ---
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header X-XSS-Protection "0" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self';" always;

    # --- API routes (proxy to FastAPI backend) ---
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Re-apply security headers inside location block
        # (Nginx drops server-level add_header in location blocks that have their own)
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
        add_header X-XSS-Protection "0" always;
        add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    }

    # --- Frontend static files (React build output) ---
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;

        # Cache static assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf)$ {
            expires 30d;
            add_header Cache-Control "public, immutable";
        }
    }

    # --- Block direct access to document storage ---
    location /data/ {
        deny all;
        return 403;
    }
}
```

Note on security headers: Nginx drops server-level `add_header` directives in any `location` block that defines its own `add_header`. The `/api/` block above re-declares security headers to prevent this.[^8][^9]

### 7.2 TLS Certificates (Let's Encrypt — Free)

```bash
# Install certbot
sudo apt install -y certbot

# Stop nginx if already running
docker compose -f /opt/leaksight/app/docker-compose.prod.yml stop nginx

# Get certificate
sudo certbot certonly --standalone -d yourdomain.com

# Copy certs to nginx directory
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem /opt/leaksight/nginx/certs/
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem /opt/leaksight/nginx/certs/
sudo chown -R leaksight:leaksight /opt/leaksight/nginx/certs/

# Restart nginx
docker compose -f /opt/leaksight/app/docker-compose.prod.yml up -d nginx
```

### 7.3 Auto-Renewal Cron

```bash
sudo crontab -e
```

Add:

```text
0 3 * * * certbot renew --quiet && cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem /opt/leaksight/nginx/certs/ && cp /etc/letsencrypt/live/yourdomain.com/privkey.pem /opt/leaksight/nginx/certs/ && docker compose -f /opt/leaksight/app/docker-compose.prod.yml restart nginx
```

***

## 8. Database Setup & RLS

After `docker compose up -d`:

### 8.1 Run Migrations

```bash
cd /opt/leaksight/app
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

### 8.2 Confirm RLS

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U leaksight_user -d leaksight
```

```sql
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
```

Every table with `tenant_id` must show `rowsecurity = true`.

### 8.3 Seed System Data

```bash
docker compose -f docker-compose.prod.yml exec backend python -m app.scripts.seed
```

Populates: `canonical_units` (MT, KG, G, L, ML, Nos, Box, Set, Sqft, Sqm, RMT), `unit_conversion_factors`, and default `tenant_settings`.

***

## 9. Redis Configuration

Already configured in docker-compose above:

- `redis:7-alpine` with AOF persistence (`--appendonly yes`).
- 512MB memory limit with LRU eviction.
- Internal network only — no port exposed to host.
- Celery broker on DB 0, result backend on DB 1.

***

## 10. Document Storage & Encryption at Rest

### 10.1 Encrypted Volume (Hetzner)

Attach a separate Volume in Hetzner console. Hetzner encrypts volumes at rest by default (AES-256).

```bash
# Format (ONLY on first use — this wipes the disk)
sudo mkfs.ext4 /dev/sdb

# Mount
sudo mount /dev/sdb /opt/leaksight/data
```

Add to `/etc/fstab` for persistence across reboots:

```text
/dev/sdb /opt/leaksight/data ext4 defaults 0 2
```

**Verify** documents and postgres data are on this volume:

```bash
df -h /opt/leaksight/data/documents
df -h /opt/leaksight/data/postgres
# Both should show /dev/sdb as the filesystem
```

***

## 11. Backups

### 11.1 Backup Script

Create `/opt/leaksight/scripts/backup.sh`:

```bash
#!/bin/bash
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/opt/leaksight/data/backups
CONTAINER=leaksight-app-postgres-1
DB_NAME=leaksight
DB_USER=leaksight_user

# Create compressed dump
docker exec $CONTAINER pg_dump -U $DB_USER $DB_NAME | gzip > $BACKUP_DIR/db_$TIMESTAMP.sql.gz

# Delete daily backups older than 14 days
find $BACKUP_DIR -name "db_*.sql.gz" -mtime +14 -delete

echo "$(date): Backup completed → db_$TIMESTAMP.sql.gz ($(du -h $BACKUP_DIR/db_$TIMESTAMP.sql.gz | cut -f1))"
```

```bash
chmod +x /opt/leaksight/scripts/backup.sh
```

### 11.2 Schedule Daily Backup

```bash
crontab -e
```

Add:

```text
0 2 * * * /opt/leaksight/scripts/backup.sh >> /opt/leaksight/logs/backup.log 2>&1
```

### 11.3 Restore Command (Exact)

This is the **exact command** to restore from a backup:

```bash
# List available backups
ls -lh /opt/leaksight/data/backups/

# Restore (replace FILENAME with actual backup name)
gunzip -c /opt/leaksight/data/backups/db_20260221_020000.sql.gz | \
  docker exec -i leaksight-app-postgres-1 psql -U leaksight_user leaksight
```

**Full disaster restore** (database completely gone):

```bash
# 1. Drop and recreate the database
docker exec leaksight-app-postgres-1 \
  psql -U leaksight_user -d postgres -c "DROP DATABASE IF EXISTS leaksight;"
docker exec leaksight-app-postgres-1 \
  psql -U leaksight_user -d postgres -c "CREATE DATABASE leaksight OWNER leaksight_user;"

# 2. Restore from backup
gunzip -c /opt/leaksight/data/backups/db_20260221_020000.sql.gz | \
  docker exec -i leaksight-app-postgres-1 psql -U leaksight_user leaksight

# 3. Verify
docker exec leaksight-app-postgres-1 \
  psql -U leaksight_user -d leaksight -c "SELECT count(*) FROM leakage_records;"
```

**Test this procedure before pilot**. Backups you have never restored are not backups.

***

## 12. Monitoring & Health Checks

### 12.1 Container Health Script

Create `/opt/leaksight/scripts/healthcheck.sh`:

```bash
#!/bin/bash

SERVICES=("leaksight-app-postgres-1" "leaksight-app-redis-1" "leaksight-app-backend-1" "leaksight-app-worker-1" "leaksight-app-nginx-1")
ALERT_LOG=/opt/leaksight/logs/healthcheck.log

for SERVICE in "${SERVICES[@]}"; do
    STATUS=$(docker inspect --format='{{.State.Status}}' $SERVICE 2>/dev/null || echo "not_found")
    HEALTH=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no_healthcheck{{end}}' $SERVICE 2>/dev/null || echo "unknown")

    if [ "$STATUS" != "running" ] || ([ "$HEALTH" != "healthy" ] && [ "$HEALTH" != "no_healthcheck" ]); then
        MSG="ALERT: $SERVICE status=$STATUS health=$HEALTH at $(date)"
        echo "$MSG" >> $ALERT_LOG
        echo "$MSG"  # stdout for cron email
    fi
done
```

```bash
chmod +x /opt/leaksight/scripts/healthcheck.sh
```

Schedule every 5 minutes:

```text
*/5 * * * * /opt/leaksight/scripts/healthcheck.sh >> /opt/leaksight/logs/healthcheck.log 2>&1
```

### 12.2 Disk Usage Alert

```text
0 * * * * USAGE=$(df /opt/leaksight/data --output=pcent | tail -1 | tr -dc '0-9'); if [ "$USAGE" -gt 80 ]; then echo "DISK ALERT: /opt/leaksight/data at ${USAGE}% on $(date)" >> /opt/leaksight/logs/disk.log; fi
```

### 12.3 Worker Memory Monitor

```bash
# Check worker memory usage (run manually when debugging)
docker stats leaksight-app-worker-1 --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}"
```

If worker consistently exceeds 8GB, reduce `--concurrency` from 2 to 1 or increase server RAM.

### 12.4 Celery Task Status

```bash
# Active tasks
docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec worker \
  celery -A app.core.celery_app inspect active

# Queued tasks
docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec worker \
  celery -A app.core.celery_app inspect reserved
```

***

## 13. Domain, DNS & Cloudflare

1. **Buy domain**: Cloudflare Registrar, Namecheap, or GoDaddy (~₹500–950/year for .com).[^10]
2. **DNS A-record**: Point `@` or `app` to `YOUR_SERVER_IP`, TTL 300.
3. **Cloudflare** (free tier, strongly recommended):[^11][^12]
   - DDoS protection
   - IP masking (server IP hidden)
   - CDN for static frontend files
   - Set SSL mode to **Full (strict)**

***

## 14. Deployment Workflow — COMPLETE COMMANDS

### 14.1 Build & Ship (From Your Local Machine)

```bash
# Build the backend Docker image
cd ~/leaksight
docker build -t leaksight/backend:latest -f Dockerfile.backend .

# Tag with version number (always tag before shipping)
docker tag leaksight/backend:latest leaksight/backend:v1.0.0

# Save as transferable tarball
docker save leaksight/backend:latest | gzip > leaksight_backend_latest.tar.gz

# Transfer to server
scp leaksight_backend_latest.tar.gz leaksight@YOUR_SERVER_IP:/opt/leaksight/app/
```

### 14.2 Deploy (On the Server)

```bash
ssh leaksight@YOUR_SERVER_IP
cd /opt/leaksight/app

# Load the new image
docker load < leaksight_backend_latest.tar.gz

# Pull latest compose/code changes if using git
git pull origin main

# Restart backend and worker with new image (postgres/redis stay running)
docker compose -f docker-compose.prod.yml up -d --no-deps backend
docker compose -f docker-compose.prod.yml up -d --no-deps worker

# Run any new database migrations
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head

# Confirm everything is healthy
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=20 backend
docker compose -f docker-compose.prod.yml logs --tail=20 worker
```

### 14.3 Rollback (If Deployment Breaks)

```bash
ssh leaksight@YOUR_SERVER_IP
cd /opt/leaksight/app

# Load previous working version
docker load < leaksight_backend_v0.9.0.tar.gz

# Retag as latest
docker tag leaksight/backend:v0.9.0 leaksight/backend:latest

# Restart with old image
docker compose -f docker-compose.prod.yml up -d --no-deps backend
docker compose -f docker-compose.prod.yml up -d --no-deps worker

# Verify
docker compose -f docker-compose.prod.yml ps
```

**Rule**: Always keep the previous version's tar on the server until the new deployment is confirmed stable. Delete old tars only after 3+ days of stable operation.

***

## 15. PaddleOCR Memory Management (Critical)

This section addresses the risk that neither the original guides covered: PaddleOCR consumes 6–10GB RAM processing large scanned PDFs, causing silent OOM failures.[^2][^3]

### Protections Already in Docker Compose

| Protection | Where | What It Does |
|-----------|-------|--------------|
| `deploy.resources.limits.memory: 10G` | Worker container | Hard cap — Docker kills container if exceeded, auto-restarts |
| `--max-tasks-per-child=50` | Celery command | Restarts worker process every 50 tasks to release leaked memory[^6] |
| `shm_size: '2g'` | Worker container | Provides shared memory PaddleOCR needs for internal data exchange[^3] |
| `--concurrency=2` | Celery command | Limits parallel OCR jobs to prevent double-memory-load |

### Application-Level Protections (Implement in Code)

Add these to `parsers/pdf_scanned_parser.py`:

1. **Process scanned PDFs page-by-page**, not as a whole document. Load one page image, OCR it, write result, discard image before next page.[^2]
2. **Force garbage collection** after every page: `gc.collect()` after processing each page.
3. **Set PaddleOCR to use mobile model** for V1 (100–200MB RAM vs 300–500MB for server model). Accuracy is still sufficient for ≥70% target.[^3]
4. **Log memory usage** after each document parse to detect creep early.

### How to Test Before Pilot

```bash
# Upload a 50-page scanned PDF and monitor worker memory in real-time
docker stats leaksight-app-worker-1

# Watch for: memory usage should rise during parse, then drop after task completes
# If it only rises and never drops: --max-tasks-per-child is not configured, or 
# your parser is not releasing page images after processing
```

If memory exceeds 8GB during testing, reduce `--concurrency` to 1 (one OCR task at a time).

***

## 16. First-Boot Checklist

Run through **every item** after setup, before any client data:

- [ ] SSH works as `leaksight` (not root)
- [ ] Root login disabled
- [ ] UFW active — only 22, 80, 443 open
- [ ] fail2ban running
- [ ] `docker compose ps` — all 5 containers healthy
- [ ] HTTPS working — browser padlock on domain
- [ ] HTTP → HTTPS redirect working
- [ ] `curl https://yourdomain.com/api/health` returns 200
- [ ] Alembic migrations applied with zero errors
- [ ] RLS active on all tenant tables (Section 8.2 query)
- [ ] Seed data loaded (canonical_units, conversion factors, tenant defaults)
- [ ] Backup script runs: `/opt/leaksight/scripts/backup.sh`
- [ ] **Restore tested** on a separate/blank database
- [ ] Worker processes a test file upload + parse task
- [ ] Logs appear in `/opt/leaksight/logs` (non-empty)
- [ ] Spot-check: zero PII/raw text/financial amounts in logs
- [ ] Document storage + Postgres data on encrypted volume (`df -h` confirms /dev/sdb)
- [ ] `.env` permissions: `ls -la /opt/leaksight/.env` shows `-rw-------`
- [ ] `.env` **not** tracked in git: `cd /opt/leaksight/app && git status`
- [ ] Worker memory stable under test load (`docker stats`)

All 20 must pass. If any fail, fix before handling client data.

***

## Appendix: Quick Reference Commands

```bash
# --- Lifecycle ---
docker compose -f /opt/leaksight/app/docker-compose.prod.yml up -d          # Start all
docker compose -f /opt/leaksight/app/docker-compose.prod.yml down            # Stop all
docker compose -f /opt/leaksight/app/docker-compose.prod.yml restart backend # Restart one

# --- Logs ---
docker compose -f /opt/leaksight/app/docker-compose.prod.yml logs -f         # All logs (live)
docker compose -f /opt/leaksight/app/docker-compose.prod.yml logs -f worker  # Worker only
docker compose -f /opt/leaksight/app/docker-compose.prod.yml logs --tail=50 backend

# --- Database ---
docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec backend alembic upgrade head
docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec postgres psql -U leaksight_user leaksight

# --- Worker ---
docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec worker \
  celery -A app.core.celery_app inspect active

# --- Monitoring ---
docker stats                                  # Real-time resource usage
du -sh /opt/leaksight/data/*                  # Disk usage per directory
/opt/leaksight/scripts/healthcheck.sh         # Manual health check
/opt/leaksight/scripts/backup.sh              # Manual backup

# --- Backup & Restore ---
ls -lh /opt/leaksight/data/backups/           # List backups
gunzip -c /opt/leaksight/data/backups/db_YYYYMMDD_HHMMSS.sql.gz | \
  docker exec -i leaksight-app-postgres-1 psql -U leaksight_user leaksight
```

---

## References

1. [Hetzner pricing 2026 | OMR Reviews](https://omr.com/en/reviews/product/hetzner/pricing) - CX51. €35.58/ Month. 8 vCPU Intel. 32 GB RAM. 240 GB NVMe SSD. 20 TB Traffic. 2 ... CX41. €18.92/ Mo...

2. [AKS/Docker: I am processing PDF's as large as 5,000 to 10,000 pages for OCR. I'm trying to run the pages concurrently in groups of 50 but running into a situtation where the memory goes to 10GB for a 200MB file. - Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/2169048/aks-docker-i-am-processing-pdfs-as-large-as-5-000) - I am processing PDF's as large as 5,000 to 10,000 pages for OCR with 200 MB files. I'm trying to run...

3. [PaddleOCR Docker部署中的内存优化实践](https://blog.csdn.net/gitblog_01426/article/details/150482485) - 文章浏览阅读361次，点赞3次，收藏3次。在当今数字化时代，光学字符识别（OCR）技术已成为企业数字化转型的关键技术之一。PaddleOCR作为业界领先的多语言OCR工具包，支持80+种语言识别，但在...

4. [How to Configure Memory Limits in Docker Compose](https://www.geeksforgeeks.org/devops/configure-docker-compose-memory-limits/) - Your All-in-One Learning Portal: GeeksforGeeks is a comprehensive educational platform that empowers...

5. [How to specify Memory & CPU limit in docker compose version 3](https://stackoverflow.com/questions/42345235/how-to-specify-memory-cpu-limit-in-docker-compose-version-3) - I am unable to specify CPU and memory limitation for services specified in version 3. With version 2...

6. [Potential memory leak in PaddleOCR? · Issue #7823 - GitHub](https://github.com/PaddlePaddle/PaddleOCR/issues/7823) - When PaddleOCR processes new images of a sequence, there is a constant increase in memory usage of t...

7. [How to set the flags correctly to reduce CPU usage or GPU ...](https://github.com/PaddlePaddle/PaddleOCR/discussions/14497) - im using paddleocr for a project and i want to limit the resources its using. The CPU usage of paddl...

8. [Securing Your Nginx Server: Setting Default Security Headers](https://wafatech.sa/blog/linux/linux-security/securing-your-nginx-server-setting-default-security-headers/) - The following steps outline how to set these security headers. Open your Nginx configuration file, t...

9. [How to Configure Security Headers in Nginx](https://linuxcapable.com/how-to-configure-security-headers-in-nginx/) - Configure NGINX security headers to block XSS, clickjacking, and downgrades. Enable HSTS, CSP, X-Fra...

10. [Cheap Domain Name Registration | Buy & Save Today - GoDaddy IN](https://www.godaddy.com/en-in/domains/cheap-domain-names) - Pay less and get cheap domain names from GoDaddy. Cheap domain registration can save you money.

11. [Cloudflare reinforces Free Tier commitment with 15 new features ...](https://ppc.land/cloudflare-reinforces-free-tier-commitment-with-15-new-features-announcement/) - Cloudflare reaffirms its dedication to free services on its 14th anniversary, unveiling 15 new featu...

12. [Cloudflare pricing and plan guide (UK) - Wise](https://wise.com/gb/blog/cloudflare-pricing) - Learn how to choose the best Cloudflare plan for your business needs and how to save on costs in the...

