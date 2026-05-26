# LeakSight Local Development

LeakSight is a FastAPI, Celery, PostgreSQL, Redis, and React/Vite application for post-facto vendor price leakage detection and document control workflows.

For local setup and startup commands on this machine, use:

```text
docs/HOW_TO_START.md
```

Current local path:

```powershell
C:\Users\user\Downloads\Leaksight-master
```

Main local ports:

- Backend API: `http://localhost:8000`
- Frontend: `http://localhost:5173`
- PostgreSQL via Docker: `localhost:5434`
- Redis via Docker: `localhost:6379`

Secrets belong in `.env`, which is ignored by git. Do not commit credentials, API keys, SMTP passwords, or tenant admin passwords.
