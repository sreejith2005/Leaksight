# SECURITY_RUNBOOK.md

## 1. SECRET_KEY Rotation Procedure

Rotate immediately if the key is believed compromised. Otherwise rotate every 6 months.

Effect of rotation:
- All existing JWT tokens are immediately invalidated.
- All users must log in again.

Steps:

1. Generate a new key:

```bash
python -c "import secrets; print(secrets.token_hex(64))"
```

2. Update `SECRET_KEY` in `/opt/leaksight/.env` on the server:

```bash
ssh leaksight@YOUR_SERVER_IP
cd /opt/leaksight
sudo nano /opt/leaksight/.env
```

3. Restart the backend:

```bash
cd /opt/leaksight/app
docker compose -f docker-compose.prod.yml restart backend
```

4. Verify users can log in and receive fresh tokens:

```bash
curl -X POST https://YOUR_DOMAIN/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"PZAD-QyiIWCBct2iRxvEkQ"}'
```

## 2. Database Password Rotation Procedure

1. Update `POSTGRES_PASSWORD` in `/opt/leaksight/.env`:

```bash
ssh leaksight@YOUR_SERVER_IP
cd /opt/leaksight
sudo nano /opt/leaksight/.env
```

2. Update the password inside PostgreSQL:

```bash
cd /opt/leaksight/app
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U leaksight_user -d leaksight -c "ALTER USER leaksight_user WITH PASSWORD 'NEW_STRONG_PASSWORD';"
```

3. Restart backend and worker containers so they reconnect with the new credentials:

```bash
docker compose -f docker-compose.prod.yml restart backend worker
```

4. Verify the application can still connect:

```bash
docker compose -f docker-compose.prod.yml logs --tail=50 backend
docker compose -f docker-compose.prod.yml logs --tail=50 worker
curl -s https://YOUR_DOMAIN/api/v1/health
```

## 3. If a JWT Token Is Believed Stolen

1. If the specific token is known, revoke it with the logout endpoint:

```bash
TOKEN="PASTE_STOLEN_TOKEN_HERE"
curl -X POST https://YOUR_DOMAIN/api/v1/auth/logout \
  -H "Authorization: Bearer $TOKEN"
```

2. If the exact token is not known, rotate `SECRET_KEY` immediately. This invalidates all JWTs:

```bash
python -c "import secrets; print(secrets.token_hex(64))"
```

Then follow the rotation procedure in Section 1.

3. Review audit logs for the affected user and tenant:

```bash
cd /opt/leaksight/app
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U leaksight_user -d leaksight -c "SELECT created_at, tenant_id, user_id, action, details_jsonb FROM audit_logs ORDER BY created_at DESC LIMIT 100;"
```

## 4. If the Server Is Believed Compromised

1. Immediately take a database backup:

```bash
ssh leaksight@YOUR_SERVER_IP
/opt/leaksight/scripts/backup.sh
```

2. Revoke SSH access for the affected key:

```bash
sudo rm -f /home/leaksight/.ssh/authorized_keys
sudo systemctl restart ssh
```

3. Rebuild the server from scratch using the deployment runbook in `docs/DEPLOYMENT_RUNBOOK.md`.

4. Restore from backup:

```bash
/opt/leaksight/scripts/restore.sh /opt/leaksight/data/backups/db_LATEST.sql.gz
```

5. Notify affected tenants using the incident communication process.

## 5. Regular Security Checklist (Monthly)

- [ ] Review `audit_logs` for unusual patterns such as many `LOGIN_FAILED` events from one IP or access at unusual hours.
- [ ] Check for software updates:

```bash
cd /opt/leaksight/app
pip list --outdated
```

- [ ] Verify backup restore works:

```bash
/opt/leaksight/scripts/verify_backup.sh /opt/leaksight/data/backups/db_LATEST.sql.gz
```

- [ ] Check disk encryption is active:

```bash
lsblk -f
```

- [ ] Review active users and deactivate anyone who should no longer have access:

```bash
cd /opt/leaksight/app
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U leaksight_user -d leaksight -c "SELECT id, tenant_id, email, role, is_active FROM users ORDER BY created_at DESC;"
```
