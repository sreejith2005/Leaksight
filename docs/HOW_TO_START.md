# How to Start LeakSight Locally

## Quick Start

Open **two separate terminals** in the project folder:  
`D:\c\Downloads\Leaksight v1 -1`

### Terminal 1 — Backend (port 8000)

```powershell
.venvScriptsActivate.ps1.venvScriptspython.exe -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

or

```
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 2 — Celery Worker

```powershell
.venv\Scripts\python.exe -m celery -A backend.app.core.celery_app worker --loglevel=info --pool=solo -Q 'default,parse,analysis,structuring'
```

or

```
python -m celery -A backend.app.core.celery_app worker --loglevel=info --pool=solo -Q default,parse,analysis,structuring
```

`structuring` is the Tool A queue. It processes contract structuring runs, review export jobs, and LeakSight import writes.

### Terminal 3 — Frontend (port 5173)

```powershell
cd frontendnpm run dev
```

### Verify

-   Backend: open [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health) → should show `{"status":"ok"}`
-   Frontend: open [http://localhost:5173](http://localhost:5173)

### Stop

Press `Ctrl+C` in the respective terminal.

---

## How Long Do They Stay Running?

**Both servers run indefinitely** — they do NOT auto-shutdown or timeout. They will keep running as long as:

1.  The terminal window stays open (don't close the terminal)
2.  Your computer stays on (not sleeping/hibernating)
3.  You don't press Ctrl+C in that terminal
4.  Nothing crashes (rare — if it does, just restart)

### When you WILL need to restart:

Situation

Restart needed?

Computer restarted / woke from sleep

**Yes — both**

Terminal window was closed

**Yes — whichever was closed**

You pressed Ctrl+C

**Yes — whichever you stopped**

Edited a backend `.py` file

**No** — `--reload` flag auto-restarts it

Edited a frontend `.tsx`/`.css` file

**No** — Vite HMR auto-updates the browser

Installed a new Python package

**Yes — backend only**

Ran `npm install` in frontend

**Yes — frontend only**

Just left it running overnight

**No** — it stays up

### TL;DR

You only need to restart when your computer sleeps/restarts or you close the terminal. During a normal work session, start both once and they stay up all day.