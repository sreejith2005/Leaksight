# LeakSight V1 — Nginx Configuration Guide

Source: infra setup guide (Sections 6, 7), `docs/ARCHITECTURE.md` (Section 7)

## Files

- `leaksight.conf` — Complete production Nginx configuration

## Before Deployment

### 1. Replace Domain Placeholder

Open `leaksight.conf` and replace **every** occurrence of `YOUR_DOMAIN_HERE` with your actual domain:

```bash
sed -i 's/YOUR_DOMAIN_HERE/app.leaksight.com/g' leaksight.conf
```

There are exactly 2 occurrences (HTTP server block and HTTPS server block).

### 2. Copy to Server

```bash
scp leaksight.conf leaksight@YOUR_SERVER_IP:/opt/leaksight/nginx/conf/
```

## TLS Certificate Setup (Let's Encrypt — Free)

### Obtain Certificate

Use the provided script:

```bash
./scripts/setup_tls.sh yourdomain.com
```

Or manually:

```bash
# Install certbot (on server)
sudo apt install -y certbot

# Stop nginx if running (certbot needs port 80)
docker compose -f /opt/leaksight/app/docker-compose.prod.yml stop nginx

# Get certificate
sudo certbot certonly --standalone -d yourdomain.com

# Copy certs to nginx directory
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem /opt/leaksight/nginx/certs/
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem /opt/leaksight/nginx/certs/
sudo chown -R leaksight:leaksight /opt/leaksight/nginx/certs/

# Start nginx
docker compose -f /opt/leaksight/app/docker-compose.prod.yml up -d nginx
```

### Auto-Renewal (Cron)

Certificates expire every 90 days. Set up auto-renewal:

```bash
sudo crontab -e
```

Add this line (renewal runs daily at 3am, only renews if needed):

```
0 3 * * * certbot renew --quiet && cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem /opt/leaksight/nginx/certs/ && cp /etc/letsencrypt/live/yourdomain.com/privkey.pem /opt/leaksight/nginx/certs/ && docker compose -f /opt/leaksight/app/docker-compose.prod.yml restart nginx
```

Replace `yourdomain.com` with your actual domain.

### Reload Nginx Without Downtime

After certificate renewal or config changes, reload without dropping connections:

```bash
docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec nginx nginx -s reload
```

This sends a graceful reload signal — active connections finish before the new configuration takes effect.

## Verification

After deployment, verify the configuration:

```bash
# Test Nginx config syntax (inside container)
docker compose -f /opt/leaksight/app/docker-compose.prod.yml exec nginx nginx -t

# Test HTTPS is working
curl -I https://yourdomain.com

# Test HTTP → HTTPS redirect
curl -I http://yourdomain.com
# Should return 301 to https://

# Test security headers
curl -sI https://yourdomain.com | grep -iE "strict-transport|x-frame|x-content-type|referrer-policy|x-xss|permissions-policy"

# Test /data/ path is blocked
curl -s -o /dev/null -w "%{http_code}" https://yourdomain.com/data/
# Should return 403

# Test API proxy
curl https://yourdomain.com/api/v1/health
# Should return 200 OK
```

## Security Headers Reference

| Header | Value | Purpose |
|--------|-------|---------|
| Strict-Transport-Security | max-age=31536000; includeSubDomains | Force HTTPS for 1 year |
| X-Frame-Options | SAMEORIGIN | Prevent clickjacking |
| X-Content-Type-Options | nosniff | Prevent MIME type sniffing |
| Referrer-Policy | strict-origin-when-cross-origin | Limit referrer leakage |
| X-XSS-Protection | 0 | Disable legacy XSS filter (CSP is better) |
| Permissions-Policy | camera=(), microphone=(), geolocation=() | Disable unnecessary browser APIs |

**Important:** Security headers are declared at both server-level and inside the `/api/` location block. This is because Nginx drops server-level `add_header` directives in any location block that defines its own `add_header`.
