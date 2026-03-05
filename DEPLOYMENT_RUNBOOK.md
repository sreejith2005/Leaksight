# LeakSight V1 — Deployment Runbook

> **Phase:** 11 — Deployment Preparation  
> **Environment:** Hetzner CX41 (4 vCPU, 16 GB RAM, 160 GB NVMe)  
> **OS:** Ubuntu 22.04 LTS  
> **Stack:** FastAPI + PostgreSQL 15 + Redis 7 + Celery + Nginx  
> **Alembic Head:** `b2c3d4e5f6a7`

---

## Table of Contents

1.  [Pre-Deployment Requirements](#1-pre-deployment-requirements)
2.  [Phase A — Server Provisioning](#2-phase-a--server-provisioning)
3.  [Phase B — Base OS & Docker Setup](#3-phase-b--base-os--docker-setup)
4.  [Phase C — Application Deployment](#4-phase-c--application-deployment)
5.  [Phase D — Database Initialisation](#5-phase-d--database-initialisation)
6.  [Phase E — TLS & Domain Configuration](#6-phase-e--tls--domain-configuration)
7.  [Phase F — Monitoring & Backups](#7-phase-f--monitoring--backups)
8.  [Phase G — Verification & First-Boot Checklist](#8-phase-g--verification--first-boot-checklist)
9.  [Tenant Creation](#9-tenant-creation)
10.  [Update Workflow](#10-update-workflow)
11.  [Rollback Procedure](#11-rollback-procedure)
12.  [Known Limitations (V1)](#12-known-limitations-v1)

---

## 1. Pre-Deployment Requirements

Before starting, confirm you have:

-    Hetzner Cloud account with payment method
-    Domain name with DNS access (Cloudflare recommended)
-    SSH key pair (ed25519)
-    Brevo SMTP credentials (free tier: 300 emails/day)
-    Local machine with Docker installed (for building images)
-    This repository cloned locally

---

## 2. Phase A — Server Provisioning

### 2.1 Create Hetzner Server

1.  Log into Hetzner Cloud console
2.  Create server: **CX41** (4 vCPU, 16 GB RAM, 160 GB NVMe)
3.  OS: **Ubuntu 22.04**
4.  Location: **Nuremberg (EU)** or **Helsinki**
5.  Add your SSH public key during creation
6.  Note the server IP address

### 2.2 Attach Encrypted Volume (Optional but Recommended)

1.  In Hetzner console, create a Volume (50+ GB)
2.  Attach to the server
3.  Hetzner encrypts volumes at rest (AES-256) by default

```bash
# Format (ONLY on first use — destructive)sudo mkfs.ext4 /dev/sdbsudo mount /dev/sdb /opt/leaksight/data# Persist across rebootsecho "/dev/sdb /opt/leaksight/data ext4 defaults 0 2" | sudo tee -a /etc/fstab
```

---

## 3. Phase B — Base OS & Docker Setup

### 3.1 Initial SSH & User Setup

```bash
# SSH as root (first time only)ssh root@YOUR_SERVER_IP# Create non-root useradduser leaksightusermod -aG sudo leaksightrsync --archive --chown=leaksight:leaksight ~/.ssh /home/leaksight# Harden SSHsudo sed -i 's/^#?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_configsudo sed -i 's/^#?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_configsudo systemctl restart sshd# TEST: Open new terminal, SSH as leaksight before closing root
```

### 3.2 Firewall & Base Packages

```bash
su - leaksightsudo apt update && sudo apt upgrade -ysudo apt install -y ufw fail2ban curl git unzip htop certbotsudo ufw allow OpenSSHsudo ufw allow 80/tcpsudo ufw allow 443/tcpsudo ufw enablesudo systemctl enable fail2bansudo systemctl start fail2bansudo timedatectl set-timezone Asia/Kolkata
```

### 3.3 Install Docker

```bash
curl -fsSL https://get.docker.com -o get-docker.shsudo sh get-docker.shsudo usermod -aG docker leaksight# Log out and back inexitssh leaksight@YOUR_SERVER_IPsudo apt install -y docker-compose-plugindocker --versiondocker compose version
```

### 3.4 Create Directory Layout

```bash
sudo mkdir -p /opt/leaksightsudo chown leaksight:leaksight /opt/leaksightmkdir -p /opt/leaksight/appmkdir -p /opt/leaksight/data/postgresmkdir -p /opt/leaksight/data/redismkdir -p /opt/leaksight/data/documentsmkdir -p /opt/leaksight/data/backupsmkdir -p /opt/leaksight/logsmkdir -p /opt/leaksight/logs/nginxmkdir -p /opt/leaksight/nginx/certsmkdir -p /opt/leaksight/nginx/confmkdir -p /opt/leaksight/scripts
```

---

## 4. Phase C — Application Deployment

### 4.1 Build Docker Image (On Local Machine)

```bash
cd ~/leaksightdocker build -t leaksight/backend:latest -f Dockerfile.backend .docker tag leaksight/backend:latest leaksight/backend:v1.0.0# Save as transferable tarballdocker save leaksight/backend:latest | gzip > leaksight_backend_latest.tar.gz# Transfer to serverscp leaksight_backend_latest.tar.gz leaksight@YOUR_SERVER_IP:/opt/leaksight/app/
```

### 4.2 Deploy Code to Server

```bash
# On servercd /opt/leaksight/app# Option A: Git clonegit clone YOUR_REPO_URL .# Option B: SCP the code# scp -r ./backend ./docker-compose.prod.yml leaksight@YOUR_SERVER_IP:/opt/leaksight/app/# Load Docker imagedocker load < leaksight_backend_latest.tar.gz
```

### 4.3 Configure Environment

```bash
# Generate .env with random secretscd /opt/leaksight/appbash scripts/generate_env.sh# Edit the generated .env — fill in YOUR_VALUE_HERE placeholdersnano /opt/leaksight/.env
```

**Required edits in .env:**

Variable

What to set

`ALLOWED_HOSTS`

Your actual domain (e.g., `app.leaksight.io`)

`SMTP_USER`

Brevo SMTP login

`SMTP_PASSWORD`

Brevo SMTP key

`SMTP_FROM`

`noreply@yourdomain.com`

```bash
# Lock permissionschmod 600 /opt/leaksight/.env
```

### 4.4 Deploy Nginx Config

```bash
cp /opt/leaksight/app/infra/nginx/leaksight.conf /opt/leaksight/nginx/conf/# Replace YOUR_DOMAIN with actual domainsed -i 's/YOUR_DOMAIN/app.yourdomain.com/g' /opt/leaksight/nginx/conf/leaksight.conf
```

### 4.5 Build Frontend

```bash
cd /opt/leaksight/app/frontendnpm cinpm run build# Output: /opt/leaksight/app/frontend/dist/
```

### 4.6 Start All Services

```bash
cd /opt/leaksight/appdocker compose -f docker-compose.prod.yml up -d# Wait for health checkssleep 30docker compose -f docker-compose.prod.yml ps
```

All 5 containers must show **running** and **healthy**.

---

## 5. Phase D — Database Initialisation

### 5.1 Run Alembic Migrations

```bash
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

Expected output: applies 3 migrations ending at `b2c3d4e5f6a7`.

### 5.2 Verify RLS

```bash
docker compose -f docker-compose.prod.yml exec postgres   psql -U leaksight_user -d leaksight -c   "SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
```

Every table with `tenant_id` must show `rowsecurity = true`.

### 5.3 Seed System Data

```bash
docker compose -f docker-compose.prod.yml exec backend   python -m app.scripts.seed
```

This populates:

-   **11 canonical units**: MT, KG, G, L, ML, Nos, Box, Set, Sqft, Sqm, RMT
-   **Unit conversion factors**: All conversions within WEIGHT, VOLUME, AREA, LENGTH dimensions
-   **Default tenant settings template**

The seed script is **idempotent** — safe to run multiple times.

### 5.4 Create First Tenant

```bash
docker compose -f docker-compose.prod.yml exec backend   python -m app.scripts.create_tenant --name "Pilot Client" --email "admin@client.com"
```

Output:

```
Tenant created:  Tenant ID:  <uuid>  Name:       Pilot Client  Admin email: admin@client.com  Temp password: <random-generated>⚠ Share this password securely. User must change it on first login.
```

---

## 6. Phase E — TLS & Domain Configuration

### 6.1 DNS Setup

1.  Add DNS A record: `app.yourdomain.com` → `YOUR_SERVER_IP`, TTL 300
2.  Wait for DNS propagation (check: `dig app.yourdomain.com`)

### 6.2 Get TLS Certificate

```bash
# Stop nginx temporarilydocker compose -f docker-compose.prod.yml stop nginx# Get certificatesudo certbot certonly --standalone -d app.yourdomain.com# Copy certssudo cp /etc/letsencrypt/live/app.yourdomain.com/fullchain.pem /opt/leaksight/nginx/certs/sudo cp /etc/letsencrypt/live/app.yourdomain.com/privkey.pem /opt/leaksight/nginx/certs/sudo chown -R leaksight:leaksight /opt/leaksight/nginx/certs/# Restart nginxdocker compose -f docker-compose.prod.yml up -d nginx
```

### 6.3 Verify HTTPS

```bash
curl -I https://app.yourdomain.com# Should return 200 with security headers (HSTS, X-Frame-Options, etc.)curl http://app.yourdomain.com# Should redirect to HTTPS (301)
```

---

## 7. Phase F — Monitoring & Backups

### 7.1 Install Scripts

```bash
cp /opt/leaksight/app/scripts/backup.sh /opt/leaksight/scripts/cp /opt/leaksight/app/scripts/restore.sh /opt/leaksight/scripts/cp /opt/leaksight/app/scripts/verify_backup.sh /opt/leaksight/scripts/cp /opt/leaksight/app/scripts/healthcheck.sh /opt/leaksight/scripts/cp /opt/leaksight/app/scripts/worker_status.sh /opt/leaksight/scripts/cp /opt/leaksight/app/scripts/full_status.sh /opt/leaksight/scripts/chmod +x /opt/leaksight/scripts/*.sh# Replace domain placeholderssed -i 's/YOUR_DOMAIN/app.yourdomain.com/g' /opt/leaksight/scripts/full_status.sh
```

### 7.2 Install Cron Jobs

```bash
bash /opt/leaksight/app/scripts/setup_monitoring_cron.shbash /opt/leaksight/app/scripts/setup_backup_cron.sh
```

This installs:

-   Healthcheck every 5 minutes
-   Disk alert every hour
-   Daily backup at 2 AM
-   TLS auto-renewal at 3 AM

### 7.3 Test Backup & Restore

```bash
# Run a manual backup/opt/leaksight/scripts/backup.sh# Verify the backup is restorable/opt/leaksight/scripts/verify_backup.sh /opt/leaksight/data/backups/db_*.sql.gz
```

---

## 8. Phase G — Verification & First-Boot Checklist

Run through **every item** before handling any client data.

### 20-Item First-Boot Checklist

```bash
# 1. SSH works as leaksight (not root)ssh leaksight@YOUR_SERVER_IP# 2. Root login disabledssh root@YOUR_SERVER_IP 2>&1 | grep -q "Permission denied" && echo "PASS" || echo "FAIL"# 3. UFW active — only 22, 80, 443 opensudo ufw status verbose# 4. fail2ban runningsudo systemctl is-active fail2ban# 5. All 5 containers healthydocker compose -f /opt/leaksight/app/docker-compose.prod.yml ps# 6. HTTPS working — browser padlock on domaincurl -sI https://app.yourdomain.com | head -5# 7. HTTP → HTTPS redirect workingcurl -sI http://app.yourdomain.com | grep "301|Location"# 8. Health endpoint returns 200curl -s https://app.yourdomain.com/api/v1/health# 9. Alembic migrations at headdocker compose -f /opt/leaksight/app/docker-compose.prod.yml exec backend alembic current# Expected: b2c3d4e5f6a7 (head)# 10. RLS active on all tenant tablesdocker compose -f /opt/leaksight/app/docker-compose.prod.yml exec postgres   psql -U leaksight_user -d leaksight -t -c   "SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public' AND rowsecurity=true;"# 11. Seed data loadeddocker compose -f /opt/leaksight/app/docker-compose.prod.yml exec postgres   psql -U leaksight_user -d leaksight -t -c   "SELECT count(*) FROM canonical_units;"# Expected: 11# 12. Backup script runs/opt/leaksight/scripts/backup.sh# 13. Restore tested on separate database/opt/leaksight/scripts/verify_backup.sh /opt/leaksight/data/backups/db_*.sql.gz# 14. Worker processes a test upload# Upload a test PDF via the API and confirm task completes# 15. Logs appear in /opt/leaksight/logsls -la /opt/leaksight/logs/# 16. Zero PII in logsgrep -rn "INV-|PO-|GRN-|Pvt Ltd|@.*.com" /opt/leaksight/logs/ | head -5# Expected: no output# 17. Document storage + Postgres on encrypted volumedf -h /opt/leaksight/data# 18. .env permissions lockedls -la /opt/leaksight/.env# Expected: -rw------- 1 leaksight leaksight# 19. .env not tracked in gitcd /opt/leaksight/app && git status | grep ".env"# Expected: no output (not tracked)# 20. Worker memory stable under test loaddocker stats leaksight-app-worker-1 --no-stream
```

**All 20 must pass. If any fail, fix before handling client data.**

---

## 9. Tenant Creation

### Create a New Tenant (< 5 minutes)

```bash
docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec backend   python -m app.scripts.create_tenant --name "Client Name" --email "admin@client.com"
```

The script:

1.  Creates a new `tenants` row with `is_active=true`
2.  Creates `tenant_settings` with LeakSight defaults (fuzzy=0.85, duplicate_window=30, review_threshold=0.70, base_currency=INR)
3.  Creates an `ADMIN` user with a temporary random password
4.  Prints the credentials to stdout

**Share the temporary password via a secure channel (not email).** The user should change their password on first login.

### Deactivate a Tenant

```bash
docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec postgres   psql -U leaksight_user -d leaksight -c   "UPDATE tenants SET is_active = false WHERE name = 'Client Name';"
```

---

## 10. Update Workflow

### Deploy a New Version

Time estimate: **5–10 minutes**, zero data loss.

```bash
# On local machine: build and transfercd ~/leaksightdocker build -t leaksight/backend:latest -f Dockerfile.backend .docker tag leaksight/backend:latest leaksight/backend:v1.x.xdocker save leaksight/backend:latest | gzip > leaksight_backend_latest.tar.gzscp leaksight_backend_latest.tar.gz leaksight@YOUR_SERVER_IP:/opt/leaksight/app/# On server:ssh leaksight@YOUR_SERVER_IPcd /opt/leaksight/app# 1. Pre-deployment backup/opt/leaksight/scripts/backup.sh# 2. Load new imagedocker load < leaksight_backend_latest.tar.gz# 3. Pull code updatesgit pull origin main# 4. Restart backend and worker (postgres/redis stay running)docker compose -f docker-compose.prod.yml up -d --no-deps backenddocker compose -f docker-compose.prod.yml up -d --no-deps worker# 5. Run any new migrationsdocker compose -f docker-compose.prod.yml exec backend alembic upgrade head# 6. Verifydocker compose -f docker-compose.prod.yml psdocker compose -f docker-compose.prod.yml logs --tail=20 backenddocker compose -f docker-compose.prod.yml logs --tail=20 workercurl -s https://app.yourdomain.com/api/v1/health
```

---

## 11. Rollback Procedure

**Target: Complete rollback in under 15 minutes.**

### Step-by-Step Rollback

```bash
ssh leaksight@YOUR_SERVER_IPcd /opt/leaksight/app# 1. Load previous working version (always keep one prior version on server)docker load < leaksight_backend_v_PREVIOUS.tar.gz# 2. Retag as latestdocker tag leaksight/backend:v_PREVIOUS leaksight/backend:latest# 3. Restart with old imagedocker compose -f docker-compose.prod.yml up -d --no-deps backenddocker compose -f docker-compose.prod.yml up -d --no-deps worker# 4. If migration was applied, downgradedocker compose -f docker-compose.prod.yml exec backend alembic downgrade -1# 5. Verifydocker compose -f docker-compose.prod.yml pscurl -s https://app.yourdomain.com/api/v1/health
```

### Database Rollback (If Needed)

```bash
# 1. Stop backend and workerdocker compose -f docker-compose.prod.yml stop backend worker# 2. Restore from pre-deployment backup/opt/leaksight/scripts/restore.sh /opt/leaksight/data/backups/db_PRE_DEPLOY.sql.gz# 3. Restartdocker compose -f docker-compose.prod.yml up -d backend worker
```

### Rollback Rules

-   **Always** take a backup before deploying
-   **Always** keep the previous Docker image tarball on the server
-   Delete old tarballs only after 3+ days of stable operation
-   If rollback is needed, do it immediately — don't debug in production

---

## 12. Known Limitations (V1)

These are documented, intentional scope restrictions. They are **not bugs**.

#

Limitation

Impact

Resolution

1

No real-time processing

Documents processed in batch via Celery queue

V2: webhook-triggered processing

2

No direct ERP integration

Documents uploaded manually (PDF/Excel/Word/CSV)

V2: SAP/Tally connector

3

No API-based ingestion

No programmatic upload — UI only for V1

V2: REST API for document push

4

Single-server architecture

No horizontal scaling, no HA

V2: Kubernetes, read replicas

5

Scanned PDF accuracy ≥70%

PaddleOCR mobile model; complex layouts may require manual review

V2: Server-grade OCR model, layout detection

6

Digital PDF accuracy ≥85%

pdfplumber handles most layouts; edge cases flagged for review

Continuous parser improvements

7

No SSO/SAML/OAuth

Email + password authentication only

V2: SSO integration

8

Manual FX rate management

No live FX feed; rates uploaded by admin

V2: ECB/RBI API integration

9

200MB upload limit

Enforced by nginx `client_max_body_size`

Increase in nginx config if needed

10

Quarterly/monthly analysis model

Not designed for daily continuous monitoring

V2: rolling analysis window

11

Worker memory spikes on large OCR

PaddleOCR can use 6–10GB on large scanned PDFs

Mitigated: `--max-tasks-per-child=50`, 10G limit, `shm_size: 2g`

12

No multi-region deployment

Single EU server; latency to India acceptable for batch

V2: Multi-region if needed

13

English-only document support

Parsers assume English text. Non-English invoices, contracts, or POs may produce
incorrect extractions or zero-confidence results. No language detection is performed.

V2: Evaluate multi-language OCR / parser support based on pilot feedback

14

Narrative pricing not supported

Documents containing pricing in prose paragraphs (rather than tabular line items)
may not be extracted. System requires structured or semi-structured pricing data.

V2: NLP-based extraction for narrative pricing

---

## Quick Reference Commands

```bash
# --- Lifecycle ---docker compose -f /opt/leaksight/app/docker-compose.prod.yml up -d          # Start alldocker compose -f /opt/leaksight/app/docker-compose.prod.yml down            # Stop alldocker compose -f /opt/leaksight/app/docker-compose.prod.yml restart backend # Restart one# --- Logs ---docker compose -f /opt/leaksight/app/docker-compose.prod.yml logs -f         # All (live)docker compose -f /opt/leaksight/app/docker-compose.prod.yml logs -f worker  # Worker onlydocker compose -f /opt/leaksight/app/docker-compose.prod.yml logs --tail=50 backend# --- Database ---docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec backend alembic upgrade headdocker compose -f /opt/leaksight/app/docker-compose.prod.yml exec backend alembic currentdocker compose -f /opt/leaksight/app/docker-compose.prod.yml exec postgres psql -U leaksight_user leaksight# --- Worker ---docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec worker   celery -A app.core.celery_app inspect active# --- Monitoring ---/opt/leaksight/scripts/full_status.sh     # Full system status/opt/leaksight/scripts/healthcheck.sh     # Container health/opt/leaksight/scripts/worker_status.sh   # Worker detailsdocker stats                              # Real-time resources# --- Backup ---/opt/leaksight/scripts/backup.sh          # Manual backup nowls -lh /opt/leaksight/data/backups/       # List backups/opt/leaksight/scripts/verify_backup.sh /opt/leaksight/data/backups/db_LATEST.sql.gz# --- Tenant ---docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec backend   python -m app.scripts.create_tenant --name "Name" --email "email@domain.com"
```