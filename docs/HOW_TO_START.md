# How to Start LeakSight Locally

Current local project folder:

```powershell
C:\Users\user\Downloads\Leaksight-master
```

## One-Time Setup

Run these from the project root after a fresh clone or laptop rebuild.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m spacy download en_core_web_sm

cd frontend
npm.cmd ci
cd ..
```

VS Code is configured locally in `.vscode/settings.json` to use `.venv\Scripts\python.exe` and auto-activate the venv in new terminals.

## Docker Desktop Requirement

Local Postgres and Redis run through Docker Desktop.

If Docker Desktop reports that WSL2 or Virtual Machine Platform is not enabled, run this once from a Windows terminal:

```powershell
wsl --install --no-distribution
```

Then reboot Windows. After reboot, open Docker Desktop and wait until it says the engine is running.

Verify Docker:

```powershell
docker ps
```

Start local database services:

```powershell
docker compose -f docker-compose.dev.yml up -d
```

Expected local services:

- PostgreSQL: `localhost:5434`, database `leaksight_dev`, user `leaksight_user`
- Redis: `localhost:6379`

The local development `.env` uses the Docker dev password from `docker-compose.dev.yml`. Do not commit `.env`.

## Database Setup

After Docker services are running:

```powershell
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
cd ..
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m backend.app.scripts.seed
```

If relative paths are awkward in PowerShell, use explicit paths:

```powershell
cd backend
& "C:\Users\user\Downloads\Leaksight-master\.venv\Scripts\python.exe" -m alembic upgrade head
cd ..
$env:PYTHONIOENCODING="utf-8"
& "C:\Users\user\Downloads\Leaksight-master\.venv\Scripts\python.exe" -m backend.app.scripts.seed
```

Create a local admin user when needed:

```powershell
.\.venv\Scripts\python.exe -m backend.app.scripts.create_tenant --name "Local Dev" --email "admin@test.com"
```

The script prints a temporary password. Store it locally and do not commit it.

## Start the App

Open three terminals in the project root.

### Terminal 1: Backend API

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 2: Celery Worker

```powershell
.\.venv\Scripts\python.exe -m celery -A backend.app.core.celery_app worker --loglevel=info --pool=solo -Q default,parse,analysis,structuring,revalidation
```

`--pool=solo` is required on Windows. The queue list must include `revalidation` for Tool C jobs.

### Terminal 3: Frontend

```powershell
cd frontend
npm.cmd run dev
```

## Verify

```powershell
curl.exe http://localhost:8000/api/v1/health
```

Expected backend response:

```json
{"status":"ok","service":"leaksight-api","version":"1.0.0"}
```

Frontend:

```text
http://localhost:5173
```

## Stop

Press `Ctrl+C` in the backend, worker, and frontend terminals.

Stop Docker services when you are done:

```powershell
docker compose -f docker-compose.dev.yml down
```

## Current Restore Notes

As of 2026-04-25 on this machine:

- Python 3.12.10 was installed with `winget`.
- `.venv` was created and backend imports were verified.
- `en_core_web_sm` 3.8.0 was installed.
- Frontend dependencies were installed with `npm.cmd ci`.
- `npm.cmd exec -- tsc --noEmit` passed.
- `npm.cmd run build` passed.
- Backend `/api/v1/health` passed without Docker.
- Docker Desktop is installed, but WSL2/Virtual Machine Platform requires a Windows reboot before Postgres/Redis containers can start.
